#!/usr/bin/env python
"""
一键启动 Debug 系统和日志查看器
"""

import subprocess
import os
import sys
import time
from pathlib import Path

def main():
    print("=" * 60)
    print("🚀 Debug 系统启动助手")
    print("=" * 60)
    
    base_dir = Path("C:\\Users\\Vrmuseum\\Desktop\\Research")
    debug_logs_dir = base_dir / "debug_logs"
    debug_logs_dir.mkdir(exist_ok=True)
    
    print(f"\n📁 日志目录: {debug_logs_dir}")
    print(f"✅ 日志目录已创建")
    
    print("\n" + "=" * 60)
    print("选择要启动的服务:")
    print("=" * 60)
    print("1) 启动 Debug Viewer (http://localhost:8000)")
    print("2) 查看最新 Unity 日志")
    print("3) 查看最新 RASA 日志")
    print("4) 清空所有日志")
    print("5) 一键启动 Viewer + 准备运行")
    print("0) 退出")
    
    choice = input("\n👉 选择 (0-5): ").strip()
    
    if choice == "1":
        print("\n🌐 启动 Debug Viewer...")
        print("📍 打开浏览器访问: http://localhost:8000")
        print("❌ 按 Ctrl+C 停止服务\n")
        subprocess.run([sys.executable, str(base_dir / "DEBUG_VIEWER.py")])
    
    elif choice == "2":
        log_file = debug_logs_dir / "unity_debug.log"
        if log_file.exists():
            print(f"\n📖 正在查看: {log_file}\n")
            subprocess.run([
                "powershell",
                "-Command",
                f"Get-Content '{log_file}' -Tail 100"
            ])
        else:
            print(f"❌ 日志文件不存在: {log_file}")
    
    elif choice == "3":
        log_file = debug_logs_dir / "rasa_debug.log"
        if log_file.exists():
            print(f"\n📖 正在查看: {log_file}\n")
            subprocess.run([
                "powershell",
                "-Command",
                f"Get-Content '{log_file}' -Tail 100"
            ])
        else:
            print(f"❌ 日志文件不存在: {log_file}")
    
    elif choice == "4":
        print("\n🗑️  清空所有日志...")
        import shutil
        try:
            for f in debug_logs_dir.glob("*"):
                if f.is_file():
                    f.unlink()
            print("✅ 所有日志已清空")
        except Exception as e:
            print(f"❌ 清空失败: {e}")
    
    elif choice == "5":
        print("\n" + "=" * 60)
        print("🚀 一键启动模式")
        print("=" * 60)
        print("\n1️⃣  创建日志目录...")
        debug_logs_dir.mkdir(exist_ok=True)
        print("✅ 完成")
        
        print("\n2️⃣  启动 Debug Viewer...")
        print("📍 打开浏览器访问: http://localhost:8000")
        print("✅ Viewer 启动成功")
        
        print("\n3️⃣  系统准备就绪！")
        print("\n现在可以:")
        print("  - 在 http://localhost:8000 查看实时日志")
        print("  - 启动 RASA 后端: rasa run actions")
        print("  - 在 Unity 中点击 Play")
        print("  - 点击 Rasa 按钮进行交互")
        print("\n📝 日志会自动记录所有操作...")
        print("❌ 按 Ctrl+C 停止服务\n")
        
        subprocess.run([sys.executable, str(base_dir / "DEBUG_VIEWER.py")])
    
    elif choice == "0":
        print("\n👋 再见！")
    
    else:
        print("\n❌ 无效选择")

if __name__ == "__main__":
    main()
