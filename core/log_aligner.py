# core/log_aligner.py
import os
import json
import csv
from datetime import datetime

class LogAligner:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        # Logcat 通常不带年份，需要取当前年份补齐
        self.current_year = datetime.now().year 
        self.aligned_events = []

    def parse_mqtt(self):
        """解析云端 MQTT 日志"""
        mqtt_path = os.path.join(self.data_dir, 'mqtt_cloud.log')
        if not os.path.exists(mqtt_path): return
        
        with open(mqtt_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    dt = datetime.fromisoformat(data['timestamp'])
                    self.aligned_events.append({
                        'timestamp': dt,
                        'source': 'CLOUD_MQTT',
                        'content': line.strip()
                    })
                except Exception as e:
                    pass

    def parse_logcat(self):
        """解析车端 Logcat"""
        logcat_path = os.path.join(self.data_dir, 'tbox_logcat.txt')
        if not os.path.exists(logcat_path): return
        
        with open(logcat_path, 'r', encoding='utf-8') as f:
            for line in f:
                # 【已修复】：时间字符串长度改为 18，兼容毫秒 (如 10-04 18:05:01.500)
                time_str = line[:18].strip()
                try:
                    full_time_str = f"{self.current_year}-{time_str}"
                    dt = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M:%S.%f")
                    self.aligned_events.append({
                        'timestamp': dt,
                        'source': 'TBOX_LOGCAT',
                        # 【已修复】：相应地向后截取正文，避免混入时间戳字符
                        'content': line.strip()[19:] 
                    })
                except Exception as e:
                    # 【已修复】：打印出错误，不再生吞异常
                    print(f" 警告: Logcat 解析失败，行内容: {line.strip()}，报错: {e}")

    def parse_can(self):
        """解析底层 CAN 报文"""
        can_path = os.path.join(self.data_dir, 'can_trace.csv')
        if not os.path.exists(can_path): return
        
        with open(can_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    dt = datetime.fromtimestamp(float(row['Timestamp']))
                    self.aligned_events.append({
                        'timestamp': dt,
                        'source': 'CAN_BUS',
                        'content': f"ID: {row['ID']} | Dir: {row['Dir']} | Data: {row['Data']}"
                    })
                except Exception as e:
                    pass

    def get_aligned_logs(self, limit=15000):
        self.parse_mqtt()
        self.parse_logcat()
        self.parse_can()
        
        # 按统一的 datetime 对象进行全局绝对排序
        self.aligned_events.sort(key=lambda x: x['timestamp'])
        
        # 【新增】：日志清洗规则 (Python 粗筛)
        # 过滤掉已知的、绝对是干扰项的高频心跳报文和系统废话，保护 AI 的上下文
        ignore_keywords = ["0x1A4", "0x2B5", "WifiMonitor", "ActivityManager", "Battery level normal"]
        
        output = []
        for event in self.aligned_events:
            content_str = event['content']
            
            # 如果这行日志包含黑名单关键字，直接扔掉
            if any(kw in content_str for kw in ignore_keywords):
                continue
                
            time_str = event['timestamp'].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            output.append(f"[{time_str}] [{event['source']}] {content_str}")
            
            if len(output) >= limit:
                break
            
        return "\n".join(output)

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(__file__))
    output_dir = os.path.join(base_dir, 'data_output')
    
    aligner = LogAligner(output_dir)
    merged_logs = aligner.get_aligned_logs()
    
    merged_path = os.path.join(output_dir, 'merged_timeline.txt')
    with open(merged_path, 'w', encoding='utf-8') as f:
        f.write(merged_logs)
        
    print(f" 日志时间戳对齐完成，共合并 {len(aligner.aligned_events)} 条记录。")