# 🎯 Debug系统快速参考

## 启动方式

### 方式1：一键启动（推荐）
```powershell
cd C:\Users\Vrmuseum\Desktop\Research
python START_DEBUG.py
# 选择 5) 一键启动
```

### 方式2：直接启动Viewer
```powershell
python DEBUG_VIEWER.py
# 打开 http://localhost:8000
```

### 方式3：查看日志文件
```powershell
# Unity日志
Get-Content "C:\Users\Vrmuseum\Desktop\Research\debug_logs\unity_debug.log" -Tail 50 -Wait

# RASA日志
Get-Content "C:\Users\Vrmuseum\Desktop\Research\debug_logs\rasa_debug.log" -Tail 50 -Wait
```

---

## 流程检查清单

启动前准备：
- [ ] 创建 debug_logs 文件夹
- [ ] 修改 RasaCommunication.cs（已完成 ✅）
- [ ] 修改 actions.py（已完成 ✅）
- [ ] RASA 后端运行
- [ ] Neo4j 数据库运行

点击Play后应看到的日志：
```
1. [Unity] RasaCommunication.Awake - 脚本初始化
2. [Unity] StartDictationEngine - 开始听音
3. [Unity] StopDictationEngine - 停止听音（说完话后）
4. [Unity] HTTP请求完成 - 发送到RASA
5. [RASA] ActionGetActorID开始 - 处理用户
6. [RASA] ActionProvidingResponse开始 - 生成回复
7. [RASA] ... 完成 - 响应发送
```

---

## 日志位置

```
C:\Users\Vrmuseum\Desktop\Research\debug_logs\
├── unity_debug.log           # Unity端日志（文本）
├── rasa_debug.log            # RASA端日志（文本）
└── debug_2026-03-02_10-30.jsonl  # JSON格式日志
```

---

## 常见问题速查

| 问题 | 解决方案 |
|------|--------|
| 没有日志出现 | 检查debug_logs文件夹权限，确认RasaCommunication已挂载 |
| 只有Unity日志 | 检查RASA是否运行，actions.py是否已修改 |
| 日志文件很大 | 定期删除旧的debug_*.jsonl文件 |
| 浏览器连接失败 | 确保8000端口未被占用，检查防火墙 |

---

## 关键代码位置

**Unity**：[RasaCommunication.cs](VR_RCEA/VR/Assets/MyScripts/RasaCommunication.cs)
- LogDebug() 方法在第220行

**RASA**：[actions.py](CA/original/actions.py)
- log_debug() 函数在第34行
- 在ActionProvidingResponse中调用

---

## 性能提示

- 日志记录是**异步**的，不影响主线程
- 建议定期清理日志文件（> 10MB时）
- 如需关闭，注释掉LogDebug()调用即可

---

## 快速命令

```powershell
# 生成日志摘要report
python -c "
import json, os
from collections import Counter
from pathlib import Path

log_dir = Path('C:/Users/Vrmuseum/Desktop/Research/debug_logs')
logs = []
for f in log_dir.glob('debug_*.jsonl'):
    with open(f) as file:
        logs.extend([json.loads(l) for l in file])

print(f'总日志数: {len(logs)}')
print(f'组件分布: {dict(Counter(l[\"component\"] for l in logs))}')
print(f'时间范围: {logs[0][\"timestamp\"]} ~ {logs[-1][\"timestamp\"]}')
"
```

---

**更新日期**: 2026-03-02
**维护者**: Debug System
