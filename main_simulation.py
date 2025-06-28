import os
import sys
import traci
import dss
import pandas as pd
import matplotlib.pyplot as plt
import random
import csv

print("--- Cooperative Simulation Main Program Launch (V6.1 - Final Perfect Edition) ---")

# =================================================================
# 1. Global parameter definitions
# =================================================================
SIM_DURATION_SEC = 86400
TIME_STEP_SEC = 1
WARMUP_SECONDS = 600 # Simulate warm-up time to ensure that you do not start from zero vehicles.

TOTAL_24H_VEHICLES = 3000
EV_PENETRATION = 0.6
EV_BATTERY_CAPACITY_KWH = 50.0
DWC_CHARGING_POWER_KW = 70.0
DWC_DISCHARGING_POWER_KW = -25.0
KM_PER_100_KWH = 60.0 
SOC_CONSUMPTION_PER_METER = (KM_PER_100_KWH / 100 / 1000) / EV_BATTERY_CAPACITY_KWH

KEY_BUSES_TO_PLOT = ['671', '680', '646', '611', '652']
AGGREGATE_LOAD_BUS = '671'

random.seed(42)

# =================================================================
# 2. Core functionalities
# =================================================================
def generate_traffic_flow_24h_realistic():
    """
    Generate a traffic flow file containing 24-hour real traffic patterns.
    All vehicles depart from t=0, and preheating is handled by the Python main loop.
    """
    print("Traffic flows are being dynamically generated based on real 24-hour traffic patterns....")
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
        f.write('    <vType id="car_type" accel="2.6" decel="4.5" length="5" maxSpeed="11.11" speedDev="0.1"/>\n')
        f.write('    <vType id="ev_type" accel="3.0" decel="4.5" length="5" maxSpeed="11.11" speedDev="0.1"/>\n')
        for name, edges in routes_definitions.items(): f.write(f'    <route id="{name}" edges="{edges}" />\n')
        for v in vehicle_list: f.write(f'    <vehicle id="{v["id"]}" type="{v["type"]}" route="{v["route"]}" depart="{v["depart"]:.2f}" />\n')
        f.write('</routes>')
    print(f"[Success] A 24-hour traffic flow file containing {len(vehicle_list)} vehicles has been generated.")

# =================================================================
# 3. Initialisation and main loop
# =================================================================
generate_traffic_flow_24h_realistic()

if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("Please set the “SUMO_HOME” environment variable.！")

try:
    dss_engine = dss.DSS
    dss_text = dss_engine.Text
    dss_text.Command = "compile ieee13.dss"
    print("[Success] OpenDSS engine started and IEEE 13 node model successfully compiled.")
    dss_circuit = dss_engine.ActiveCircuit
    ALL_BUS_NAMES = dss_circuit.AllBusNames
    BUS_TO_IDX = {name.lower(): i for i, name in enumerate(ALL_BUS_NAMES)}
    dss_text.Command = "Set Mode=daily stepsize=1s number=1"
    dss_text.Command = (
        f"New Load.EV_Aggregate "
        f"Bus1={AGGREGATE_LOAD_BUS}.1.2.3 "
        f"Phases=3 Conn=Delta Model=2 "
        f"kV=4.16 kW=1155 kvar=660"
    )
    print(f"Creating total EV load at aggregation point Bus {AGGREGATE_LOAD_BUS}...")
except Exception as e:
    print(f"[Failure] OpenDSS initialisation failed: {e}")
    sys.exit()

ev_fleet = {} 
simulation_results = [] 
sumo_command = ["sumo", "-c", "simulation.sumocfg"] 

try:
    traci.start(sumo_command)
    
    # Perform a warm-up cycle, but do not interact with OpenDSS or record data.
    print(f"\n--- Simulation warm-up starts (running for {WARMUP_SECONDS} seconds) ---")
    for step in range(WARMUP_SECONDS):
        traci.simulationStep()
        if (step + 1) % 100 == 0:
            print(f"Warming up... {step + 1}/{WARMUP_SECONDS} 秒")
    print("--- Simulation preheating completed ---")

    print("\n--- 24-hour collaborative simulation officially begins ---")
    
    for step in range(SIM_DURATION_SEC):
        traci.simulationStep()
        
        # Separately calculate the total charging and total discharging power.
        total_charging_power = 0.0
        total_discharging_power = 0.0
        
        active_vehicles = traci.vehicle.getIDList()
        for vid in active_vehicles:
            vehicle_type = traci.vehicle.getTypeID(vid)
            
            if vehicle_type == 'ev_type':
                if vid not in ev_fleet:
                    ev_fleet[vid] = {"soc": random.uniform(0.2, 0.95)}
                
                speed_ms = traci.vehicle.getSpeed(vid)
                distance_travelled_m = speed_ms * TIME_STEP_SEC
                soc_consumed = distance_travelled_m * SOC_CONSUMPTION_PER_METER
                ev_fleet[vid]['soc'] -= soc_consumed
                
                power = 0.0
                if ev_fleet[vid]["soc"] < 0.3:
                    power = DWC_CHARGING_POWER_KW
                    total_charging_power += power
                elif ev_fleet[vid]["soc"] > 0.8:
                    power = DWC_DISCHARGING_POWER_KW
                    total_discharging_power += abs(power)
                
                energy_change_kwh = power * (TIME_STEP_SEC / 3600.0)
                ev_fleet[vid]["soc"] += energy_change_kwh / EV_BATTERY_CAPACITY_KWH
                ev_fleet[vid]["soc"] = max(0, min(1, ev_fleet[vid]["soc"]))
        
        net_power_kw = total_charging_power - total_discharging_power
        dss_circuit.Loads.Name = 'EV_Aggregate'
        dss_circuit.Loads.kW = net_power_kw
        
        dss_text.Command = "Solve"
        
        if step % 600 == 0:
            voltages_pu_array = dss_circuit.AllBusVmagPu
            result_step = {"time_sec": step}
            result_step.update({
                "traffic_flow_count": len(active_vehicles), 
                "net_load_kw": net_power_kw,
                "charging_load_kw": total_charging_power,
                "discharging_load_kw": total_discharging_power
            })
            for bus_name_lower, index in BUS_TO_IDX.items():
                result_step[f"v_{bus_name_lower}"] = voltages_pu_array[index]
            simulation_results.append(result_step)
        
            voltage_671 = dss_circuit.AllBusVmagPu[BUS_TO_IDX['671'.lower()]]
            print(f"Time: {step/3600:.2f}h, Vehicles: {len(active_vehicles):<3}, Net EV Power: {net_power_kw:<8.2f} kW, Voltage@671: {voltage_671:.4f} p.u.")

finally:
    if traci.isLoaded():
        traci.close()
    print("\n--- Simulation ended ---")

# =================================================================
# 5. Visualisation of results
# =================================================================
if not simulation_results:
    print("No simulation data was collected, so no charts could be generated.")
else:
    print("Generating results chart...")
    df = pd.DataFrame(simulation_results)
    df['time_hour'] = df['time_sec'] / 3600

    # try:
    #     plt.rcParams['font.sans-serif'] = ['SimHei']
    #     plt.rcParams['axes.unicode_minus'] = False
    # except:
    #     print("[Warning] Chinese font not found 'SimHei'。")

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(18, 15), sharex=True)
    fig.suptitle('24-hour vehicle-road-network collaborative simulation results', fontsize=18)

    ax1.plot(df['time_hour'], df['traffic_flow_count'], label='Number of vehicles on the road', color='c', linewidth=2)
    ax1.set_ylabel('Number of vehicles', fontsize=12)
    ax1.set_title('24-hour Traffic Flow Waveform', fontsize=14)
    ax1.grid(True, linestyle=':')
    ax1.legend()

    # Use the correct fill_between function to draw charging and discharging separately.
    ax2.fill_between(df['time_hour'], 0, df['charging_load_kw'], 
                     facecolor='red', alpha=0.6, label='Total charging power', interpolate=True)
    
    ax2.fill_between(df['time_hour'], 0, -df['discharging_load_kw'], 
                     facecolor='green', alpha=0.6, label='V2G total power', interpolate=True)

    ax2.plot(df['time_hour'], df['net_load_kw'], color='black', linewidth=1.5, label='Net power (kW)')
    
    ax2.set_ylabel('Net power (kW)', fontsize=12)
    ax2.set_title('Total DWC System Load on the Grid (Disaggregated)', fontsize=14)
    ax2.axhline(0, color='black', linewidth=1, linestyle='--')
    ax2.grid(True, linestyle=':')
    ax2.legend(loc='upper left')

    for bus_name in KEY_BUSES_TO_PLOT:
        col_name = f'v_{bus_name.lower()}'
        if col_name in df.columns:
            ax3.plot(df['time_hour'], df[col_name], label=f'Node {bus_name} Voltage', linewidth=2, alpha=0.8)
    
    ax3.set_ylabel('Voltage (p.u.)', fontsize=12)
    ax3.set_title('Voltage Profile of Key Nodes over 24 Hours', fontsize=14)
    ax3.set_xlabel('Simulation time (hours)', fontsize=12)
    ax3.axhline(1.05, color='orange', linestyle='--', linewidth=1.5, label='voltage upper limit (1.05 p.u.)')
    ax3.axhline(0.95, color='orange', linestyle='--', linewidth=1.5, label='voltage lower limit (0.95 p.u.)')
    ax3.grid(True, linestyle=':')
    ax3.legend(loc='best')
    ax3.set_xlim(0, 24)
    ax3.set_xticks(range(0, 25, 2))

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    plt.savefig("simulation_results_24h.png", dpi=300)
    df.to_csv("simulation_results_24h.csv", index=False)
    print("Results plot saved to simulation_results_24h_english.png")
    print("Detailed simulation data has been exported to simulation_results_24h.csv")
    
    plt.show()

print("\nThe program has finished executing.")
