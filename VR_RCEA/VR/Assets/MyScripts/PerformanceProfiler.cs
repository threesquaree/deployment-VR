using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using UnityEngine.EventSystems;

/// <summary>
/// 性能监测系统 - 追踪FPS、执行时间、内存占用
/// 将此脚本挂在任何GameObject上，自动监测性能
/// </summary>
public class PerformanceProfiler : MonoBehaviour
{
    private const string PERF_LOG_FILE = "C:/Users/s3533204/Downloads/Research/Research/debug_logs/unity_perf.log";
    
    private float fps = 0f;
    private float frameTime = 0f;
    private int frameCount = 0;
    private float updateTime = 0f;
    private float renderTime = 0f;
    private float maxFrameTime = 0f;
    private float maxUpdateTime = 0f;
    private float maxRenderTime = 0f;
    private int slowFrameCount = 0;
    private string selectedUiObject = "None";
    
    private Stopwatch frameStopwatch;
    private Stopwatch updateStopwatch;
    
    private List<string> activeScripts = new List<string>();
    private Dictionary<string, float> scriptTimings = new Dictionary<string, float>();
    
    private float logIntervalSeconds = 2f; // 每2秒记录一次
    private float lastFpsSampleTime = 0f;
    private float lastMetricsLogTime = 0f;
    
    private void Awake()
    {
        frameStopwatch = new Stopwatch();
        updateStopwatch = new Stopwatch();
        lastFpsSampleTime = Time.time;
        lastMetricsLogTime = Time.time;
        LogPerf("STARTUP", "PerformanceProfiler initialized");
    }
    
    private void OnEnable()
    {
        LogPerf("STARTUP", "PerformanceProfiler enabled");
    }
    
    private void Update()
    {
        frameStopwatch.Restart();
        updateStopwatch.Start();
        
        // 监测所有正在运行的脚本
        MonoBehaviour[] allScripts = FindObjectsOfType<MonoBehaviour>();
        activeScripts.Clear();
        foreach (var script in allScripts)
        {
            if (script.enabled && script.gameObject.activeInHierarchy)
            {
                activeScripts.Add(script.GetType().Name);
            }
        }
        
        updateStopwatch.Stop();
        updateTime = updateStopwatch.ElapsedMilliseconds;
        
        // 计算FPS
        frameCount++;
        if (Time.time - lastFpsSampleTime >= 1f)
        {
            fps = frameCount / (Time.time - lastFpsSampleTime);
            frameCount = 0;
            lastFpsSampleTime = Time.time;
        }
    }
    
    private void LateUpdate()
    {
        // 这里渲染命令被发送
        renderTime = frameStopwatch.ElapsedMilliseconds;
        frameTime = Time.deltaTime * 1000f; // 转换为毫秒
        maxFrameTime = Mathf.Max(maxFrameTime, frameTime);
        maxUpdateTime = Mathf.Max(maxUpdateTime, updateTime);
        maxRenderTime = Mathf.Max(maxRenderTime, renderTime);
        if (frameTime > 33.33f) slowFrameCount++;

        var eventSystem = EventSystem.current;
        selectedUiObject = eventSystem != null && eventSystem.currentSelectedGameObject != null
            ? eventSystem.currentSelectedGameObject.name
            : "None";
        
        // 定期记录性能日志
        if (Time.time - lastMetricsLogTime >= logIntervalSeconds)
        {
            LogPerformanceMetrics();
            lastMetricsLogTime = Time.time;
        }
    }
    
    private void LogPerformanceMetrics()
    {
        string memoryMB = (GC.GetTotalMemory(false) / 1048576f).ToString("F2");
        string logMessage = $"FPS={fps:F1} FrameTime={frameTime:F2}ms UpdateTime={updateTime:F2}ms RenderTime={renderTime:F2}ms ActiveScripts={activeScripts.Count} Memory={memoryMB}MB SelectedUI={selectedUiObject} SlowFrames={slowFrameCount} MaxFrame={maxFrameTime:F2}ms MaxUpdate={maxUpdateTime:F2}ms MaxRender={maxRenderTime:F2}ms";
        
        LogPerf("FRAME_PERF", logMessage);
        
        // 警告检查
        if (fps < 30)
        {
            LogPerf("PERF_WARNING", $"⚠️ FPS低于30: {fps:F1}");
        }
        
        // 详细脚本列表（采样）
        if (activeScripts.Count > 0)
        {
            string scriptsList = string.Join(", ", activeScripts);
            LogPerf("ACTIVE_SCRIPTS", $"${activeScripts.Count} 个脚本运行: {scriptsList}");
        }

        slowFrameCount = 0;
        maxFrameTime = 0f;
        maxUpdateTime = 0f;
        maxRenderTime = 0f;
    }
    
    /// <summary>
    /// 供其他脚本调用，记录执行时间
    /// </summary>
    public static void LogExecutionTime(string scriptName, string methodName, float durationMs)
    {
        string message = $"[{scriptName}.{methodName}] {durationMs:F2}ms";
        if (durationMs > 16.67f) // 60FPS threshold
        {
            message += " ⚠️ SLOW";
        }
        LogPerf("EXECUTION", message);
    }
    
    /// <summary>
    /// 记录数据库操作
    /// </summary>
    public static void LogDatabaseOperation(string operation, float durationMs, int recordCount)
    {
        string message = $"[DB] {operation} - {durationMs:F2}ms for {recordCount} records";
        if (durationMs > 100)
        {
            message += " ⚠️ SLOW";
        }
        LogPerf("DATABASE", message);
    }

    public static void LogCustom(string category, string message)
    {
        LogPerf(category, message);
    }
    
    /// <summary>
    /// 内部日志记录方法
    /// </summary>
    private static void LogPerf(string category, string message)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(PERF_LOG_FILE));
            
            string timestamp = System.DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            string logEntry = $"[{timestamp}] [{category}] {message}";
            
            File.AppendAllText(PERF_LOG_FILE, logEntry + "\n");
            UnityEngine.Debug.Log($"[PERF] {logEntry}");
        }
        catch (Exception ex)
        {
            UnityEngine.Debug.LogError($"LogPerf异常: {ex.Message}");
        }
    }
    
    private void OnGUI()
    {
        // HUD显示实时性能数据
        if (GUI.Button(new Rect(10, 10, 200, 30), "Toggle Perf Display"))
        {
            // 可选：显示/隐藏HUD
        }
        
        GUILayout.BeginArea(new Rect(10, 50, 300, 150));
        GUILayout.Label($"FPS: {fps:F1}");
        GUILayout.Label($"Frame Time: {frameTime:F2}ms");
        GUILayout.Label($"Active Scripts: {activeScripts.Count}");
        GUILayout.Label($"Memory: {(GC.GetTotalMemory(false) / 1048576f):F2}MB");
        GUILayout.EndArea();
    }
}
