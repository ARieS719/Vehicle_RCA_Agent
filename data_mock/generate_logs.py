# data_mock/generate_logs.py
import os
import csv
import json
import random
import uuid
from datetime import datetime, timedelta

def generate_scenario(output_dir, scenario_id, current_time):
    os.makedirs(output_dir, exist_ok=True)
    mqtt_file = os.path.join(output_dir, 'mqtt_cloud.log')
    logcat_file = os.path.join(output_dir, 'tbox_logcat.txt')
    can_file = os.path.join(output_dir, 'can_trace.csv')

    # 模拟 60 秒的运行时间窗口
    start_time = current_time - timedelta(seconds=60)
    
    with open(mqtt_file, 'w', encoding='utf-8') as f_mqtt, \
         open(logcat_file, 'w', encoding='utf-8') as f_logcat, \
         open(can_file, 'w', newline='', encoding='utf-8') as f_can:
        
        can_writer = csv.writer(f_can)
        can_writer.writerow(["Timestamp", "ID", "Dir", "DLC", "Data"])

        # ==========================================
        # 1. 铺设 60 秒的全局真实背景噪音
        # ==========================================
        for ms in range(0, 60000, 20): # 每 20 毫秒跑一次循环
            now = start_time + timedelta(milliseconds=ms)
            
            # CAN 噪音：常规的车速、转速、温度等心跳报文
            if ms % 50 == 0: can_writer.writerow([f"{now.timestamp():.6f}", "0x1A4", "RX", "8", "00 12 34 00 00 00 00 00"])
            if ms % 100 == 0: can_writer.writerow([f"{now.timestamp():.6f}", "0x2B5", "RX", "8", "AA BB CC DD EE FF 00 11"])
            
            # Logcat 噪音：Android 系统常规日志
            if ms % 1200 == 0: f_logcat.write(f"{now.strftime('%m-%d %H:%M:%S.%f')[:-3]}  1000  1050 I ActivityManager: CPU usage normal, memory stable\n")
            if ms % 5500 == 0: f_logcat.write(f"{now.strftime('%m-%d %H:%M:%S.%f')[:-3]}   850  1120 D WifiMonitor: Scanning for networks...\n")
            if ms % 8000 == 0: f_logcat.write(f"{now.strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 I TBoxMqtt: MQTT KeepAlive Ping Sent\n")
            
            # MQTT 噪音：云端心跳
            if ms % 15000 == 0:
                f_mqtt.write(json.dumps({"timestamp": now.isoformat(), "topic": "/vehicle/status", "payload": {"batt": 85, "speed": 0}, "level": "DEBUG"}) + "\n")

        # ==========================================
        # 2. 随机注入一次【完全成功】的业务干扰 (发生在 10~20 秒)
        # 目的：考验 AI 是否会被正常日志误导
        # ==========================================
        success_req = f"req_succ_{random.randint(1000,9999)}"
        s_time = start_time + timedelta(seconds=random.randint(10, 20))
        f_mqtt.write(json.dumps({"timestamp": s_time.isoformat(), "topic": "/app/req", "payload": {"cmd": "lock", "req_id": success_req}, "level": "INFO"}) + "\n")
        f_logcat.write(f"{(s_time+timedelta(seconds=0.5)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 I TBoxMqtt: Received cmd: lock, req: {success_req}\n")
        f_logcat.write(f"{(s_time+timedelta(seconds=0.6)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 I CanHal: Enqueuing CAN ID: 0x3F2, Data: 00 (Lock)\n")
        can_writer.writerow([f"{(s_time+timedelta(seconds=0.7)).timestamp():.6f}", "0x3F2", "TX", "8", "00 00 00 00 00 00 00 00"])
        f_logcat.write(f"{(s_time+timedelta(seconds=0.8)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 I CanHal: TX Success ID: 0x3F2\n")
        f_mqtt.write(json.dumps({"timestamp": (s_time+timedelta(seconds=1.5)).isoformat(), "topic": "/vehicle/tbox/status", "payload": {"status": "SUCCESS", "req_id": success_req}, "level": "INFO"}) + "\n")

        # ==========================================
        # 3. 随机注入【案发现场】 (发生在 40~50 秒)
        # ==========================================
        bug_req = f"req_fail_{random.randint(1000,9999)}"
        bug_time = start_time + timedelta(seconds=random.randint(40, 50))
        
        if scenario_id == 1:
            # 场景 1：动力域 ECM 抽风，疯狂发 0x0C1 堵死总线
            f_mqtt.write(json.dumps({"timestamp": bug_time.isoformat(), "topic": "/app/req", "payload": {"cmd": "unlock", "req_id": bug_req}, "level": "INFO"}) + "\n")
            f_logcat.write(f"{(bug_time+timedelta(seconds=0.5)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 I TBoxMqtt: Received cmd: unlock, req: {bug_req}\n")
            f_logcat.write(f"{(bug_time+timedelta(seconds=0.6)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 I CanHal: Enqueuing CAN ID: 0x3F2, Data: 01 (Unlock)\n")
            
            # 恶意的总线拥堵，持续 6 秒
            for i in range(600):
                congestion_time = bug_time + timedelta(seconds=0.7) + timedelta(milliseconds=i*10)
                can_writer.writerow([f"{congestion_time.timestamp():.6f}", "0x0C1", "RX", "8", "FF FF FF FF FF FF FF FF"])
            
            f_logcat.write(f"{(bug_time+timedelta(seconds=5.6)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 E CanHal: CAN TX Timeout! Buffer full. ID: 0x3F2\n")
            f_mqtt.write(json.dumps({"timestamp": (bug_time+timedelta(seconds=6.0)).isoformat(), "topic": "/vehicle/tbox/status", "error": "TIMEOUT_NO_RESPONSE", "req_id": bug_req, "level": "ERROR"}) + "\n")

        elif scenario_id == 2:
            # 场景 2：车库弱网，车机 MQTT 客户端静默死锁
            f_mqtt.write(json.dumps({"timestamp": bug_time.isoformat(), "topic": "/app/req", "payload": {"cmd": "unlock", "req_id": bug_req}, "level": "INFO"}) + "\n")
            f_logcat.write(f"{(bug_time-timedelta(seconds=5)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 W TBoxMqtt: Signal quality poor. RSSI: -95dBm\n")
            f_logcat.write(f"{(bug_time+timedelta(seconds=1)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 E TBoxMqtt: Ping Timeout. Client Socket Deadlock.\n")
            f_logcat.write(f"{(bug_time+timedelta(seconds=3)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 I TBoxMqtt: Attempting to restart network manager...\n")
            # 根本没走到发 CAN 的步骤
            f_mqtt.write(json.dumps({"timestamp": (bug_time+timedelta(seconds=7.0)).isoformat(), "topic": "/vehicle/tbox/status", "error": "TIMEOUT_OFFLINE", "req_id": bug_req, "level": "ERROR"}) + "\n")

        elif scenario_id == 3:
            # 场景 3：执行器损坏，BCM 硬件抛错
            f_mqtt.write(json.dumps({"timestamp": bug_time.isoformat(), "topic": "/app/req", "payload": {"cmd": "unlock", "req_id": bug_req}, "level": "INFO"}) + "\n")
            f_logcat.write(f"{(bug_time+timedelta(seconds=0.5)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2045 I TBoxMqtt: Received cmd: unlock, req: {bug_req}\n")
            f_logcat.write(f"{(bug_time+timedelta(seconds=0.6)).strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 I CanHal: Enqueuing CAN ID: 0x3F2, Data: 01 (Unlock)\n")
            
            can_time_tx = bug_time + timedelta(seconds=0.7)
            f_logcat.write(f"{can_time_tx.strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 I CanHal: TX Success ID: 0x3F2\n")
            can_writer.writerow([f"{can_time_tx.timestamp():.6f}", "0x3F2", "TX", "8", "01 00 00 00 00 00 00 00"])
            
            # 0.2秒后 BCM 回复了 0x3F3，数据中包含了 0xEE 报错
            can_time_rx = bug_time + timedelta(seconds=0.9)
            can_writer.writerow([f"{can_time_rx.timestamp():.6f}", "0x3F3", "RX", "8", "EE 00 00 00 00 00 00 00"])
            f_logcat.write(f"{can_time_rx.strftime('%m-%d %H:%M:%S.%f')[:-3]}  1011  2046 E VehicleControl: BCM reported hardware fault! Code: 0xEE\n")
            f_mqtt.write(json.dumps({"timestamp": (bug_time+timedelta(seconds=1.5)).isoformat(), "topic": "/vehicle/tbox/status", "error": "HARDWARE_FAULT_0xEE", "req_id": bug_req, "level": "ERROR"}) + "\n")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(__file__))
    
    scenarios = [
        ("case_1_can_congestion", 1),
        ("case_2_network_offline", 2),
        ("case_3_hardware_fault", 3)
    ]
    
    for folder_name, s_id in scenarios:
        output_dir = os.path.join(base_dir, 'data_output', folder_name)
        generate_scenario(output_dir, s_id, datetime.now())
        print(f" 成功生成【真实混沌测试集】: {folder_name} (包含正常业务与海量噪音)")