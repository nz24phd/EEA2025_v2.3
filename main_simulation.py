import os
import sys
import traci
import dss
import pandas as pd
import matplotlib.pyplot as plt
import random
import csv

print("--- 协同仿真主程序启动 (V5.8 - 最终修正完美版) ---")

# =================================================================
# 1. 全局参数定义
# =================================================================
SIM_DURATION_SEC = 86400
TIME_STEP_SEC = 1
TOTAL_24H_VEHICLES = 3000
EV_PENETRATION = 0.6
EV_BATTERY_CAPACITY_KWH = 50.0
DWC_CHARGING_POWER_KW = 70.0
DWC_DISCHARGING_POWER_KW = -25.0
KM_PER_100_KWH = 60.0 
SOC_CONSUMPTION_PER_METER = (KM_PER_100_KWH / 100 / 1000) / EV_BATTERY_CAPACITY_KWH

KEY_BUSES_TO_PLOT = ['671', '680', '646', '611', '652']
AGGREGATE_LOAD_BUS = '671'

random.seed(123)  # 固定随机种子以确保结果可复现

# =================================================================
# 2. 核心功能函数
# =================================================================
def generate_traffic_flow_24h_realistic():
    print("正在根据真实的24小时交通模式动态生成交通流...")
    hourly_traffic_distribution = [
        0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.06, 0.09, 0.07, 0.04, 0.04, 0.04,
        0.04, 0.04, 0.04, 0.04, 0.04, 0.08, 0.10, 0.08, 0.05, 0.04, 0.03, 0.02
    ]
    assert abs(sum(hourly_traffic_distribution) - 1.0) < 1e-9

    routes_definitions = {
        "route_main": "L_650_632 L_632_671 L_671_680",
        "route_side_1": "L_650_632 L_632_645 L_645_646",
        "route_side_2": "L_671_684 L_684_611",
        "route_side_3": "L_671_684 L_684_652",
        "route_to_634": "L_650_632 L_632_633 L_633_634",
        "route_to_675": "L_650_632 L_632_671 L_671_675"
    }
    
    vehicle_list = []
    vehicle_id_counter = 0
    for hour, percentage in enumerate(hourly_traffic_distribution):
        num_vehicles_in_hour = int(TOTAL_24H_VEHICLES * percentage)
        start_sec = hour * 3600
        end_sec = (hour + 1) * 3600
        for _ in range(num_vehicles_in_hour):
            v_type = "ev_type" if random.random() < EV_PENETRATION else "car_type"
            vehicle_list.append({
                "id": f"veh_{vehicle_id_counter}", "type": v_type,
                "route": random.choice(list(routes_definitions.keys())),
                "depart": random.uniform(start_sec, end_sec)
            })
            vehicle_id_counter += 1
    vehicle_list.sort(key=lambda v: v['depart'])
    
    with open("traffic.rou.xml", "w") as f:
        f.write('<routes>\n')
        f.write('    <vType id="car_type" accel="2.6" decel="4.5" length="5" maxSpeed="13.89" />\n')
        f.write('    <vType id="ev_type" accel="3.0" decel="4.5" length="5" maxSpeed="13.89" />\n')
        for name, edges in routes_definitions.items(): f.write(f'    <route id="{name}" edges="{edges}" />\n')
        for v in vehicle_list: f.write(f'    <vehicle id="{v["id"]}" type="{v["type"]}" route="{v["route"]}" depart="{v["depart"]:.2f}" />\n')
        f.write('</routes>')
    print(f"[成功] 已生成含 {len(vehicle_list)} 辆车的24小时交通流文件。")

# =================================================================
# 3. 初始化及主循环
# =================================================================
generate_traffic_flow_24h_realistic()

if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("请设置'SUMO_HOME'环境变量！")

try:
    dss_engine = dss.DSS
    dss_text = dss_engine.Text
    dss_text.Command = "compile ieee13.dss"
    print("[成功] OpenDSS引擎启动，并成功编译IEEE 13节点模型。")
    dss_circuit = dss_engine.ActiveCircuit
    ALL_BUS_NAMES = dss_circuit.AllBusNames
    BUS_TO_IDX = {name.lower(): i for i, name in enumerate(ALL_BUS_NAMES)}
    
    dss_text.Command = "Set Mode=daily stepsize=1s number=1"
    
    dss_text.Command = (
        f"New Load.EV_Aggregate "
        f"Bus1={AGGREGATE_LOAD_BUS}.1.2.3 "
        f"Phases=3 Conn=Wye Model=1 "
        f"kV=4.16 kW=0 kvar=0"
    )
    print(f"正在聚合点 Bus {AGGREGATE_LOAD_BUS} 创建总EV负荷...")

except Exception as e:
    print(f"[失败] OpenDSS初始化失败: {e}")
    sys.exit()

ev_fleet = {} 
simulation_results = [] 
sumo_command = ["sumo", "-c", "simulation.sumocfg"] 

try:
    traci.start(sumo_command)
    print("\n--- 协同仿真开始 (聚合负荷模型 - 真实能耗) ---")
    
    for step in range(SIM_DURATION_SEC):
        traci.simulationStep()
        
        total_dwc_power_kw = 0
        active_vehicles = traci.vehicle.getIDList()
        
        for vid in active_vehicles:
            # <<< 最终的、决定性的修正点 >>>
            # 不再通过检查ID字符串，而是直接查询车辆的类型
            vehicle_type = traci.vehicle.getTypeID(vid)
            
            if vehicle_type == 'ev_type':
                # --- EV的逻辑现在可以被正确执行了 ---
                if vid not in ev_fleet:
                    ev_fleet[vid] = {"soc": random.uniform(0.2, 0.95)}
                
                speed_ms = traci.vehicle.getSpeed(vid)
                distance_travelled_m = speed_ms * TIME_STEP_SEC
                soc_consumed = distance_travelled_m * SOC_CONSUMPTION_PER_METER
                ev_fleet[vid]['soc'] -= soc_consumed
                
                power = 0.0
                if ev_fleet[vid]["soc"] < 0.3:
                    power = DWC_CHARGING_POWER_KW
                elif ev_fleet[vid]["soc"] > 0.8:
                    power = DWC_DISCHARGING_POWER_KW
                
                total_dwc_power_kw += power
                
                energy_change_kwh = power * (TIME_STEP_SEC / 3600.0)
                ev_fleet[vid]["soc"] += energy_change_kwh / EV_BATTERY_CAPACITY_KWH
                ev_fleet[vid]["soc"] = max(0, min(1, ev_fleet[vid]["soc"]))
        
        dss_circuit.Loads.Name = 'EV_Aggregate'
        dss_circuit.Loads.kW = total_dwc_power_kw
        
        dss_text.Command = "Solve"
        
        if step % 600 == 0:
            voltages_pu_array = dss_circuit.AllBusVmagPu
            result_step = {"time_sec": step}
            result_step.update({"traffic_flow_count": len(active_vehicles), "total_load_kw": total_dwc_power_kw})
            for bus_name_lower, index in BUS_TO_IDX.items():
                result_step[f"v_{bus_name_lower}"] = voltages_pu_array[index]
            simulation_results.append(result_step)
        
            voltage_671 = dss_circuit.AllBusVmagPu[BUS_TO_IDX['671'.lower()]]
            print(f"Time: {step/3600:.2f}h, Vehicles: {len(active_vehicles):<3}, Total EV Power: {total_dwc_power_kw:<8.2f} kW, Voltage@671: {voltage_671:.4f} p.u.")

finally:
    if traci.isLoaded():
        traci.close()
    print("\n--- 仿真结束 ---")

# =================================================================
# 5. 结果可视化 (与V5.6一致)
# =================================================================
if not simulation_results:
    print("没有采集到仿真数据，无法生成图表。")
else:
    print("正在生成结果图表...")
    df = pd.DataFrame(simulation_results)
    df['time_hour'] = df['time_sec'] / 3600

    try:
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False
    except:
        print("[警告] 未找到中文字体 'SimHei'。")

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(18, 15), sharex=True)
    fig.suptitle('24小时车-路-网协同仿真结果', fontsize=18)

    ax1.plot(df['time_hour'], df['traffic_flow_count'], label='道路车辆数', color='c', linewidth=2)
    ax1.set_ylabel('车辆数', fontsize=12)
    ax1.set_title('24小时交通流波形', fontsize=14)
    ax1.grid(True, linestyle=':')
    ax1.legend()

    ax2.plot(df['time_hour'], df['total_load_kw'], label='DWC净功率 (kW)', color='k', linewidth=1.5, zorder=3)
    ax2.fill_between(df['time_hour'], 0, df['total_load_kw'], where=df['total_load_kw'] >= 0, facecolor='red', alpha=0.5, interpolate=True, label='充电')
    ax2.fill_between(df['time_hour'], 0, df['total_load_kw'], where=df['total_load_kw'] < 0, facecolor='green', alpha=0.5, interpolate=True, label='V2G放电')
    ax2.set_ylabel('功率 (kW)', fontsize=12)
    ax2.set_title('DWC系统对电网的总负荷', fontsize=14)
    ax2.axhline(0, color='black', linewidth=1, linestyle='--')
    ax2.grid(True, linestyle=':')
    ax2.legend()

    for bus_name in KEY_BUSES_TO_PLOT:
        col_name = f'v_{bus_name.lower()}'
        if col_name in df.columns:
            ax3.plot(df['time_hour'], df[col_name], label=f'节点 {bus_name} 电压', linewidth=2, alpha=0.8)
    
    ax3.set_ylabel('电压 (p.u.)', fontsize=12)
    ax3.set_title('关键节点24小时电压对比', fontsize=14)
    ax3.set_xlabel('仿真时间 (小时)', fontsize=12)
    ax3.axhline(1.05, color='orange', linestyle='--', linewidth=1.5, label='电压上限 (1.05 p.u.)')
    ax3.axhline(0.95, color='orange', linestyle='--', linewidth=1.5, label='电压下限 (0.95 p.u.)')
    ax3.grid(True, linestyle=':')
    ax3.legend(loc='best')
    ax3.set_xlim(0, 24)
    ax3.set_xticks(range(0, 25, 2))

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

print("\n程序执行完毕。")