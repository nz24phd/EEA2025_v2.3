import os
import sys
import dss
import pandas as pd
import matplotlib.pyplot as plt

print("--- 基准情景仿真启动 (V1.0 - 仅含24小时背景负荷) ---")

# =================================================================
# 1. 全局参数定义
# =================================================================
# 仿真总时长为24小时
SIM_DURATION_SEC = 86400 
# 数据采集的时间间隔（秒），每10分钟采集一次
DATA_COLLECTION_INTERVAL_SEC = 600 

# 定义我们关心的、需要绘图的关键节点
KEY_BUSES_TO_PLOT = ['671', '680', '646', '611', '652']

# =================================================================
# 2. 初始化OpenDSS
# =================================================================
try:
    dss_engine = dss.DSS
    dss_text = dss_engine.Text
    # 确保使用的是我们最终的、包含24小时负荷曲线的V7.2版本dss文件
    dss_text.Command = "compile ieee13.dss"
    print("[成功] OpenDSS引擎启动，并成功编译IEEE 13节点模型。")
    
    dss_circuit = dss_engine.ActiveCircuit
    ALL_BUS_NAMES = dss_circuit.AllBusNames
    BUS_TO_IDX = {name.lower(): i for i, name in enumerate(ALL_BUS_NAMES)}
    
    # 设定OpenDSS为按天模式，步长为1秒，每次只解一个时间步
    # 这样可以由Python的for循环来精确控制时间的推进
    dss_text.Command = "Set Mode=daily stepsize=1s number=1"

except Exception as e:
    print(f"[失败] OpenDSS初始化失败: {e}")
    sys.exit()

# =================================================================
# 3. 仿真主循环
# =================================================================
simulation_results = []
print("\n--- 正在进行24小时背景负荷仿真 ---")

for step in range(SIM_DURATION_SEC):
    # 命令OpenDSS求解当前时间步的潮流
    dss_text.Command = "Solve"
    
    # 每隔指定的时间间隔，采集一次数据
    if step % DATA_COLLECTION_INTERVAL_SEC == 0:
        voltages_pu_array = dss_circuit.AllBusVmagPu
        result_step = {"time_sec": step}
        
        # 记录所有关键节点的电压
        for bus_name in KEY_BUSES_TO_PLOT:
            bus_name_lower = bus_name.lower()
            if bus_name_lower in BUS_TO_IDX:
                index = BUS_TO_IDX[bus_name_lower]
                result_step[f"v_{bus_name_lower}"] = voltages_pu_array[index]
        
        simulation_results.append(result_step)

        # 打印进度
        print(f"仿真进度: {step/3600:.2f} 小时 / 24.00 小时 ({(step/SIM_DURATION_SEC*100):.0f}%)")

print("\n--- 基准情景仿真结束 ---")

# =================================================================
# 4. 结果处理与可视化
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

    fig, ax = plt.subplots(figsize=(18, 8))
    
    for bus_name in KEY_BUSES_TO_PLOT:
        col_name = f'v_{bus_name.lower()}'
        if col_name in df.columns:
            ax.plot(df['time_hour'], df[col_name], label=f'节点 {bus_name} 电压', linewidth=2, alpha=0.8)
    
    ax.set_ylabel('电压 (p.u.)', fontsize=12)
    ax.set_xlabel('仿真时间 (小时)', fontsize=12)
    ax.set_title('基准情景：关键节点24小时电压波形 (无EV负荷)', fontsize=16)
    ax.axhline(1.05, color='orange', linestyle='--', linewidth=1.5, label='电压上限 (1.05 p.u.)')
    ax.axhline(0.95, color='orange', linestyle='--', linewidth=1.5, label='电压下限 (0.95 p.u.)')
    ax.grid(True, linestyle=':')
    ax.legend(loc='best')
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))

    plt.tight_layout()
    
    # 将结果图和数据分别保存到独立的文件中
    plt.savefig("results_baseline.png", dpi=300)
    df.to_csv("results_baseline.csv", index=False)
    print("\n[成功] 已将基准情景结果图保存为 'results_baseline.png'")
    print("[成功] 已将基准情景详细数据导出到 'results_baseline.csv'")
    
    plt.show()

print("\n程序执行完毕。")
