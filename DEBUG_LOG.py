"""
中央调试日志系统 - 追踪完整流程
从Unity play开始 → RasaCommunication → RASA → Neo4j
"""

import os
import json
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("C:/Users/Vrmuseum/Desktop/Research/debug_logs")
LOG_DIR.mkdir(exist_ok=True)

class DebugLogger:
    def __init__(self):
        self.log_file = LOG_DIR / f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.json_log = LOG_DIR / f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        
    def log(self, component: str, event: str, data: dict = None, level: str = "INFO"):
        """
        记录日志
        component: Unity / Rasa / Neo4j
        event: 事件名称
        data: 事件数据
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # 文本日志
        text_log = f"[{timestamp}] [{level}] [{component}] {event}"
        if data:
            text_log += f" | {data}"
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(text_log + "\n")
        
        # JSON日志（便于分析）
        json_entry = {
            "timestamp": timestamp,
            "component": component,
            "event": event,
            "level": level,
            "data": data or {}
        }
        
        with open(self.json_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(json_entry, ensure_ascii=False) + "\n")
        
        print(text_log)
    
    def get_log_path(self):
        return str(self.log_file)
    
    def get_json_log_path(self):
        return str(self.json_log)


# 全局logger实例
logger = DebugLogger()

if __name__ == "__main__":
    print(f"✅ Debug日志系统就绪")
    print(f"📁 文本日志: {logger.get_log_path()}")
    print(f"📁 JSON日志: {logger.get_json_log_path()}")
