using System;
using System.IO;
using System.Text;
using UnityEngine;

/// <summary>
/// Logs continuous VA samples from ColorWheelUI and discrete EVENT rows to a CSV.
/// The logger will not start until a non-empty participantId is applied (via Apply Now).
/// </summary>
public class RCEADataLogger : MonoBehaviour
{
    // ------------------ References ------------------
    [Header("Refs")]
    [Tooltip("Primary UI source for VA + sector info.")]
    public ColorWheelUI colorWheel;

    [Tooltip("Optional VA source. If null, values are read from ColorWheelUI.")]
    public GamepadVAReader source;

    // ------------------ Participant ------------------
    [Header("Participant")]
    [Tooltip("Editable in Inspector. Leave empty by default; fill it during Play, then click 'Apply Now' in the Inspector.")]
    public string participantId = "";

    [Tooltip("When true, participantId is included in the log filename.")]
    public bool includeParticipantInFilename = true;

    // Internally track which participantId we already applied (to detect changes).
    // NOTE: only used by ApplyParticipantNow; there is no auto-apply at runtime.
    string _appliedParticipant = "";

    // ------------------ Sampling / Hotkey ------------------
    [Header("Sampling / Hotkey")]
    [Tooltip("VA sampling frequency (Hz).")]
    [Range(1f, 60f)] public float sampleHz = 10f;

    [Tooltip("If true, attempts to start logging at Start(). Will still gate on participantId.")]
    public bool autoStart = false;

    [Tooltip("Keyboard toggle for start/stop logging.")]
    public KeyCode toggleKey = KeyCode.L;

    // ------------------ Output ------------------
    [Header("Output")]
    [Tooltip("Base filename (timestamp appended).")]
    public string fileBase = "rcea_log";

    [Tooltip("Leave empty to use Application.persistentDataPath. " +
             "If relative, it's created inside persistentDataPath; if absolute, it's used as-is.")]
    public string folderPath = "";

#if UNITY_EDITOR
    [ContextMenu("Pick Log Folder (Editor)...")]
    void PickFolderEditor()
    {
        string start = ResolveFolder();
        string chosen = UnityEditor.EditorUtility.OpenFolderPanel("Choose Log Folder", start, "");
        if (!string.IsNullOrEmpty(chosen)) folderPath = chosen;
        UnityEditor.EditorUtility.SetDirty(this);
    }
#endif

    // ------------------ State ------------------
    public bool IsRunning => _running;
    public bool HasParticipant => !string.IsNullOrWhiteSpace(participantId);

    bool _running;
    float _accum;
    StringBuilder _sb = new StringBuilder(4096);
    string _path;

    // ------------------ Unity lifecycle ------------------
    void Start()
    {
        // Remember whatever is typed in the Inspector before Play
        _appliedParticipant = (participantId ?? "").Trim();

        if (autoStart) StartLoggingIfReady(); // still gated on participantId
    }

    void Update()
    {
        // Manual start/stop hotkey (still gated on participant)
        if (Input.GetKeyDown(toggleKey))
        {
            if (_running) StopLogging();
            else StartLoggingIfReady();
        }

        if (!_running || colorWheel == null) return;

        _accum += Time.unscaledDeltaTime;
        float dt = 1f / Mathf.Max(1f, sampleHz);
        if (_accum < dt) return;
        _accum = 0f;

        // ----- Sample VA/angle/intensity -----
        Vector2 va = source ? source.GetLastVA() : colorWheel.CurrentVA;
        float angle = colorWheel.CurrentAngleDeg;   // 0 = +V, 90 = +A (CCW)
        float mag = colorWheel.CurrentIntensity;

        // Sector categories
        int categoryId = -1;   // 0=center, >0 wedge, -1 N/A
        int sectorIndex = -1;
        float sectorCtr = float.NaN;

        if (colorWheel.mode == ColorWheelUI.Mode.Sectors9)
        {
            sectorIndex = colorWheel.CurrentSector; // 0..7, 8=center
            if (sectorIndex == 8) categoryId = 0;
            else if (sectorIndex >= 0) { categoryId = sectorIndex + 1; sectorCtr = sectorIndex * 45f; }
        }
        else if (colorWheel.mode == ColorWheelUI.Mode.Sectors13)
        {
            sectorIndex = colorWheel.CurrentSector; // 0..11, 12=center
            if (sectorIndex == 12) categoryId = 0;
            else if (sectorIndex >= 0) { categoryId = sectorIndex + 1; sectorCtr = sectorIndex * 30f; }
        }
        else if (colorWheel.mode == ColorWheelUI.Mode.Sectors5)
        {
            // 4 diagonal wedges centered at 45/135/225/315°, center = 4
            sectorIndex = colorWheel.CurrentSector; // 0..3, 4=center
            if (sectorIndex == 4) categoryId = 0;
            else if (sectorIndex >= 0)
            {
                categoryId = sectorIndex + 1;                  // 1..4
                sectorCtr = sectorIndex * 90f + 45f;           // 45,135,225,315
            }
        }

        // Timestamps
        double unityTime = Time.unscaledTimeAsDouble;
        DateTime now = DateTime.UtcNow;
        long unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        // Write SAMPLE row
        AppendCsv(
            now, unixMs, unityTime,
            rowType: "SAMPLE",
            evt: "", detail: "", clip: "",
            uiMode: colorWheel.mode.ToString(),
            categoryId, sectorIndex, sectorCtr,
            angle, va.x, va.y, mag
        );

        if (_sb.Length > 48000) Flush();
    }

    void OnDisable() { if (_running) StopLogging(); }
    void OnApplicationQuit() { if (_running) StopLogging(); }

    // ------------------ Public API ------------------

    /// <summary>
    /// Sets the participantId field (trimmed).
    /// Does not start/stop logging on its own.
    /// </summary>
    public void SetParticipant(string id)
    {
        participantId = id?.Trim() ?? "";
        if (!HasParticipant) Debug.LogWarning("[RCEADataLogger] Participant ID cleared/empty.");
    }

    /// <summary>
    /// Click this via the custom Inspector "Apply Now" button (or call from code).
    /// - Applies the current participantId value.
    /// - Optionally splits to a new CSV if it changed while logging.
    /// - Optionally starts logging (respects empty ID gate).
    /// </summary>
    public void ApplyParticipantNow(bool startLoggingOnApply = true, bool splitIfLoggingAndChanged = false)
    {
        string next = (participantId ?? "").Trim();
        string prev = _appliedParticipant;
        bool changed = next != prev;

        if (_running && changed && splitIfLoggingAndChanged)
        {
            LogEvent("LOGGER_SPLIT", $"from:{prev} to:{next}");
            StopLogging(); // closes current CSV
        }

        SetParticipant(next);
        _appliedParticipant = next;

        if (_running) LogEvent("PARTICIPANT_SET", next);

        if (Application.isPlaying && startLoggingOnApply)
            StartLoggingIfReady();

        Debug.Log($"[RCEADataLogger] Apply Now → '{next}' (start:{startLoggingOnApply}, split:{splitIfLoggingAndChanged})");
    }

    /// <summary>
    /// Starts logging if a non-empty participantId is set and logger not already running.
    /// Creates a new CSV and writes the header.
    /// </summary>
    public void StartLoggingIfReady()
    {
        if (!HasParticipant)
        {
            Debug.LogWarning("[RCEADataLogger] Can't start logging: participant ID is empty.");
            return;
        }
        if (_running) return;

        string dir = ResolveFolder();
        Directory.CreateDirectory(dir);

        string stamp = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss");
        string name = includeParticipantInFilename && !string.IsNullOrEmpty(participantId)
                       ? $"{fileBase}_{participantId}_{stamp}.csv"
                       : $"{fileBase}_{stamp}.csv";

        _path = Path.Combine(dir, name);

        _sb.Length = 0;
        _sb.AppendLine("participant_id,iso8601_utc,unix_ms,unity_time_s,row_type,event,event_detail,clip_name,ui_mode,category_id,sector_index,sector_center_deg,angle_deg,valence,arousal,intensity");

        _accum = 0f;
        _running = true;

        Debug.Log($"[RCEADataLogger] Started -> {_path}");
        LogEvent("LOGGER_START");
    }

    /// <summary>
    /// Flushes the buffer and closes the current CSV.
    /// </summary>
    public void StopLogging()
    {
        if (!_running) return;
        LogEvent("LOGGER_STOP");
        _running = false;
        Flush();
        Debug.Log("[RCEADataLogger] Stopped. File saved.");
    }

    /// <summary>
    /// Writes an EVENT row (only when logging).
    /// evt = event name; detail = free text; clip = optional video clip name.
    /// </summary>
    public void LogEvent(string evt, string detail = "", string clip = "")
    {
        if (!_running) return;

        double unityTime = Time.unscaledTimeAsDouble;
        DateTime now = DateTime.UtcNow;
        long unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        AppendCsv(
            now, unixMs, unityTime,
            rowType: "EVENT",
            evt: evt, detail: detail, clip: clip,
            uiMode: "", categoryId: -1, sectorIndex: -1, sectorCtr: float.NaN,
            angle: float.NaN, v: float.NaN, a: float.NaN, mag: float.NaN
        );
        if (_sb.Length > 48000) Flush();
    }

    /// <summary>Convenience helpers used by your training/player code.</summary>
    public void LogKey(KeyCode key, string action) => LogEvent("KEY", $"{action}:{key}");
    public void LogSequenceStart() => LogEvent("SEQUENCE_START");
    public void LogSequenceEnd() => LogEvent("SEQUENCE_END");
    public void LogVideoStart(string clipName) => LogEvent("VIDEO_START", "", clipName);
    public void LogVideoEnd(string clipName) => LogEvent("VIDEO_END", "", clipName);

    // ------------------ Internals ------------------
    void AppendCsv(DateTime now, long unixMs, double unityTime, string rowType,
                   string evt, string detail, string clip,
                   string uiMode, int categoryId, int sectorIndex, float sectorCtr,
                   float angle, float v, float a, float mag)
    {
        _sb.Append(participantId).Append(',')
           .Append(now.ToString("o")).Append(',')
           .Append(unixMs).Append(',')
           .Append(unityTime.ToString("0.000")).Append(',')
           .Append(rowType).Append(',')
           .Append(evt).Append(',')
           .Append(detail).Append(',')
           .Append(clip).Append(',')
           .Append(uiMode).Append(',')
           .Append(categoryId).Append(',')
           .Append(sectorIndex).Append(',')
           .Append(float.IsNaN(sectorCtr) ? "" : sectorCtr.ToString("0.0")).Append(',')
           .Append(float.IsNaN(angle) ? "" : angle.ToString("0.000")).Append(',')
           .Append(float.IsNaN(v) ? "" : v.ToString("0.000")).Append(',')
           .Append(float.IsNaN(a) ? "" : a.ToString("0.000")).Append(',')
           .Append(float.IsNaN(mag) ? "" : mag.ToString("0.000")).Append('\n');
    }

    void Flush()
    {
        try
        {
            File.AppendAllText(_path, _sb.ToString());
            _sb.Length = 0;
        }
        catch (Exception e)
        {
            Debug.LogError($"[RCEADataLogger] Flush error: {e.Message}");
        }
    }

    string ResolveFolder()
    {
        if (string.IsNullOrWhiteSpace(folderPath))
            return Application.persistentDataPath;

        if (Path.IsPathRooted(folderPath))
            return folderPath;

        return Path.Combine(Application.persistentDataPath, folderPath);
    }
}
