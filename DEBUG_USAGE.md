# 🔍 Debug日志系统使用指南

## 功能描述
追踪从Unity点击Play开始，整个流程的所有关键步骤：
- **Unity端**: RasaCommunication 脚本的执行
- **RASA端**: 对话处理和聊天逻辑  
- **Neo4j端**: 数据库操作（可选）

---

## 快速开始

### 1️⃣ **启动Debug Viewer（可视化查看）**
```powershell
cd C:\Users\Vrmuseum\Desktop\Research
python DEBUG_VIEWER.py
```
然后在浏览器打开：`http://localhost:8000`

### 2️⃣ **运行你的系统**
- 启动Unity项目，点击Play
- 点击Rasa按钮触发语音识别
- 说话并等待响应

### 3️⃣ **查看日志**
日志会自动显示在：
- 📊 **浏览器界面** (http://localhost:8000) - 实时刷新
- 📝 **文本日志**: `C:\Users\Vrmuseum\Desktop\Research\debug_logs\unity_debug.log`
- 📝 **RASA日志**: `C:\Users\Vrmuseum\Desktop\Research\debug_logs\rasa_debug.log`
- 📄 **JSON格式**: `C:\Users\Vrmuseum\Desktop\Research\debug_logs\debug_*.jsonl`

---

## 日志查看方式

### 方式A：浏览器界面（推荐）
- 打开 http://localhost:8000
- 自动每2秒刷新一次
- 可以搜索、过滤、导出日志
- 显示各组件的执行统计

### 方式B：直接查看文件
```powershell
# 查看最新日志（实时跟踪）
Get-Content "C:\Users\Vrmuseum\Desktop\Research\debug_logs\unity_debug.log" -Tail 50 -Wait

# RASA日志
Get-Content "C:\Users\Vrmuseum\Desktop\Research\debug_logs\rasa_debug.log" -Tail 50 -Wait
```

### 方式C：JSON格式分析
```powershell
# 查看所有日志的JSON格式
Get-Content "C:\Users\Vrmuseum\Desktop\Research\debug_logs\debug_*.jsonl" | ConvertFrom-Json
```

---

## 关键日志检查点

### ✅ 正常流程
1. `[Unity] RasaCommunication.Awake` - 脚本初始化
2. `[Unity] StartDictationEngine` - 开始听音
3. `[Unity] StopDictationEngine` - 停止听音并准备发送
4. `[Unity] HTTP请求完成` - 发送到RASA完成
5. `[RASA] ActionProvidingResponse开始` - RASA处理请求
6. `[RASA] ActionProvidingResponse完成` - RASA返回响应

### ⚠️ 常见问题排查

#### Q1: Unity端没有日志？
```
检查：
1. RasaCommunication 脚本是否挂在RasaManager上
2. Unity Console是否显示[DEBUG_LOG]日志
3. debug_logs文件夹是否存在
```

#### Q2: RASA端没有日志？
```
检查：
1. RASA服务是否运行 (http://localhost:5005)
2. actions.py是否已修改
3. debug_logs文件夹权限是否正确
```

#### Q3: 网络请求没有返回？
```
查看日志中的：
- [Unity] HTTP请求完成 状态=Success/Failed
- 响应代码（200=成功, 5xx=服务器错误）
- Neo4j连接状态
```

---

## 日志格式说明

### 文本格式
```
[2026-03-02 10:30:45.123] [Unity] StartDictationEngine | 开始听音
[2026-03-02 10:30:48.456] [Unity] HTTP请求完成 | 状态=Success, 代码=200
[2026-03-02 10:30:49.789] [RASA] ActionProvidingResponse开始 | turn_id=xyz, msg_text=hello
```

### JSON格式 (.jsonl)
```json
{
  "timestamp": "2026-03-02 10:30:45.123",
  "component": "Unity",
  "event": "StartDictationEngine",
  "level": "INFO",
  "data": {"status": "started"}
}
```

---

## 常用命令

```powershell
# 1. 启动Debug Viewer
python DEBUG_VIEWER.py

# 2. 实时查看Unity日志
Get-Content "debug_logs\unity_debug.log" -Tail 50 -Wait

# 3. 清空所有日志
Remove-Item "debug_logs\*" -Force

# 4. 导出所有日志到Excel
python -c "import pandas as pd; import json; logs=[json.loads(l) for l in open('debug_logs/debug_*.jsonl')]; pd.DataFrame(logs).to_excel('debug_export.xlsx')"

# 5. 统计各组件的事件数
python -c "import json; logs=[json.loads(l) for l in open('debug_logs/debug_*.jsonl')]; from collections import Counter; print(Counter(l['component'] for l in logs))"
```

---

## 性能提示

- 日志写入是**同步**的，可能轻微影响性能
- 建议在调试时启用，正式运行时禁用
- JSON日志更详细，但文件更大

---

## 注意事项

⚠️ **重要**：
- 确保 `C:\Users\Vrmuseum\Desktop\Research\debug_logs\` 文件夹可写
- 日志会不断增长，定期清理旧文件
- 敏感信息（如密码）可能被记录在日志中

---

需要帮助？检查这些文件：
- 日志目录: `C:\Users\Vrmuseum\Desktop\Research\debug_logs\`
- Debug主脚本: `C:\Users\Vrmuseum\Desktop\Research\DEBUG_LOG.py`
- 查看器: `C:\Users\Vrmuseum\Desktop\Research\DEBUG_VIEWER.py`
