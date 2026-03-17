"""
日志查看器 - 实时追踪完整流程
在浏览器中打开 http://localhost:8000 即可查看
"""

import json
import os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

LOG_DIR = Path("C:/Users/Vrmuseum/Desktop/Research/debug_logs")
LOG_DIR.mkdir(exist_ok=True)

class LogViewerHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/logs':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # 读取最新的日志
            latest_log = None
            for log_file in sorted(LOG_DIR.glob('debug_*.jsonl'))[-1:]:
                latest_log = log_file
                break
            
            if latest_log:
                with open(latest_log, 'r', encoding='utf-8') as f:
                    logs = [json.loads(line) for line in f]
                self.wfile.write(json.dumps(logs).encode())
            else:
                self.wfile.write(json.dumps([]).encode())
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Debug Log Viewer</title>
    <style>
        body { font-family: 'Courier New', monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #4ec9b0; }
        .log-entry { 
            border-left: 3px solid #4ec9b0; 
            padding: 10px;
            margin: 5px 0;
            background: #252526;
            border-radius: 3px;
        }
        .timestamp { color: #ce9178; }
        .component { color: #569cd6; font-weight: bold; }
        .event { color: #4ec9b0; }
        .data { color: #9cdcfe; }
        .level-ERROR { border-left-color: #f48771; }
        .level-WARNING { border-left-color: #dcdcaa; }
        .level-INFO { border-left-color: #4ec9b0; }
        button { 
            padding: 8px 16px; 
            background: #0e639c; 
            color: white; 
            border: none; 
            border-radius: 3px; 
            cursor: pointer;
            margin: 10px 0;
        }
        button:hover { background: #1177bb; }
        #filter { 
            padding: 8px; 
            margin: 10px 0; 
            width: 100%; 
            background: #252526;
            color: #d4d4d4;
            border: 1px solid #3e3e42;
            border-radius: 3px;
        }
        .stats { 
            background: #252526; 
            padding: 10px; 
            border-radius: 3px;
            margin: 10px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Debug Log Viewer</h1>
        
        <div class="stats">
            <h3>流程统计</h3>
            <p>Unity: <span id="unity-count">0</span> | RASA: <span id="rasa-count">0</span> | Neo4j: <span id="neo4j-count">0</span></p>
            <p>刷新时间: <span id="refresh-time">-</span></p>
        </div>
        
        <input type="text" id="filter" placeholder="搜索 (组件/事件/数据)...">
        <button onclick="loadLogs()">🔄 刷新</button>
        <button onclick="clearLogs()">🗑️ 清空日志</button>
        <button onclick="exportLogs()">📥 导出JSON</button>
        
        <div id="logs"></div>
    </div>

    <script>
        let allLogs = [];
        
        async function loadLogs() {
            try {
                const response = await fetch('/api/logs');
                allLogs = await response.json();
                renderLogs(allLogs);
                document.getElementById('refresh-time').textContent = new Date().toLocaleTimeString();
            } catch(e) {
                console.error('加载日志失败:', e);
            }
        }
        
        function renderLogs(logs) {
            const logsDiv = document.getElementById('logs');
            
            // 统计
            const stats = {
                Unity: 0,
                Rasa: 0,
                Neo4j: 0
            };
            
            logs.forEach(log => {
                if (log.component === 'Unity') stats.Unity++;
                else if (log.component === 'Rasa') stats.Rasa++;
                else if (log.component === 'Neo4j') stats.Neo4j++;
            });
            
            document.getElementById('unity-count').textContent = stats.Unity;
            document.getElementById('rasa-count').textContent = stats.Rasa;
            document.getElementById('neo4j-count').textContent = stats.Neo4j;
            
            // 渲染日志
            logsDiv.innerHTML = logs.map(log => `
                <div class="log-entry level-${log.level}">
                    <span class="timestamp">[${log.timestamp}]</span>
                    <span class="component">[${log.component}]</span>
                    <span class="event">${log.event}</span>
                    ${log.data && Object.keys(log.data).length > 0 ? 
                        `<span class="data">| ${JSON.stringify(log.data)}</span>` : ''}
                </div>
            `).join('');
        }
        
        function clearLogs() {
            const logsDiv = document.getElementById('logs');
            logsDiv.innerHTML = '<p>日志已清空</p>';
        }
        
        function exportLogs() {
            const dataStr = JSON.stringify(allLogs, null, 2);
            const dataBlob = new Blob([dataStr], {type: 'application/json'});
            const url = URL.createObjectURL(dataBlob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'debug_logs_' + new Date().getTime() + '.json';
            link.click();
        }
        
        // 每2秒自动刷新
        loadLogs();
        setInterval(loadLogs, 2000);
        
        // 搜索过滤
        document.getElementById('filter').addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            const filtered = allLogs.filter(log => 
                JSON.stringify(log).toLowerCase().includes(query)
            );
            renderLogs(filtered);
        });
    </script>
</body>
</html>
            """
            self.wfile.write(html.encode())

if __name__ == '__main__':
    print("🚀 Debug Log Viewer 启动中...")
    print("📍 打开浏览器访问: http://localhost:8000")
    print("按 Ctrl+C 停止服务")
    
    server = HTTPServer(('localhost', 8000), LogViewerHandler)
    server.serve_forever()
