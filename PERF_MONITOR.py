"""
性能监测系统 - 追踪执行时间、数据写入、脚本运行情况
"""

import time
import json
import threading
from datetime import datetime
from pathlib import Path
from collections import defaultdict

PERF_LOG_DIR = Path("C:/Users/Vrmuseum/Desktop/Research/debug_logs")
PERF_LOG_DIR.mkdir(exist_ok=True)

class PerformanceMonitor:
    def __init__(self):
        self.perf_file = PERF_LOG_DIR / f"perf_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self.metrics = defaultdict(list)
        self.lock = threading.Lock()
        
    def log_execution(self, script_name: str, method_name: str, duration_ms: float, 
                     details: dict = None, level: str = "INFO"):
        """
        记录脚本执行时间
        duration_ms: 执行时间（毫秒）
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # 警告：执行时间过长
        if duration_ms > 16.67:  # 60FPS = 16.67ms per frame
            level = "WARNING"
        elif duration_ms > 33.33:  # 30FPS
            level = "ERROR"
        
        entry = {
            "timestamp": timestamp,
            "component": "PERFORMANCE",
            "script": script_name,
            "method": method_name,
            "duration_ms": round(duration_ms, 3),
            "level": level,
            "details": details or {}
        }
        
        with self.lock:
            with open(self.perf_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
            self.metrics[script_name].append(duration_ms)
    
    def log_database_write(self, db_type: str, query_type: str, row_count: int, 
                          duration_ms: float, details: dict = None):
        """记录数据库写入操作"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        level = "WARNING" if duration_ms > 100 else "INFO"
        
        entry = {
            "timestamp": timestamp,
            "component": "DATABASE",
            "db_type": db_type,
            "query_type": query_type,
            "row_count": row_count,
            "duration_ms": round(duration_ms, 3),
            "level": level,
            "details": details or {}
        }
        
        with self.lock:
            with open(self.perf_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def log_frame_time(self, fps: float, frame_time_ms: float,
                      update_time_ms: float = 0, render_time_ms: float = 0):
        """记录帧性能数据"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        level = "INFO"
        if fps < 30:
            level = "WARNING"
        elif fps < 15:
            level = "ERROR"
        
        entry = {
            "timestamp": timestamp,
            "component": "FRAME",
            "fps": round(fps, 1),
            "frame_time_ms": round(frame_time_ms, 2),
            "update_time_ms": round(update_time_ms, 2),
            "render_time_ms": round(render_time_ms, 2),
            "level": level
        }
        
        with self.lock:
            with open(self.perf_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def get_summary(self):
        """获取性能摘要"""
        summary = {}
        for script, times in self.metrics.items():
            if times:
                summary[script] = {
                    "calls": len(times),
                    "avg_ms": round(sum(times) / len(times), 3),
                    "max_ms": round(max(times), 3),
                    "min_ms": round(min(times), 3)
                }
        return summary


# 全局实例
perf_monitor = PerformanceMonitor()

if __name__ == "__main__":
    print(f"✅ 性能监测系统就绪")
    print(f"📁 日志: {perf_monitor.perf_file}")
