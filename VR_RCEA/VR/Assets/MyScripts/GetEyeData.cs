using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Tobii.G2OM;
using Tobii.XR;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;
using Valve.VR;
using Valve.VR.InteractionSystem;
using ViveSR.anipal.Eye;
using Stopwatch = System.Diagnostics.Stopwatch;

public class GetEyeData : MonoBehaviour
{
    // ================================================================
    // ==================== PUBLIC / GENERAL FIELDS ====================
    // ================================================================
    public string filename;
    public Text statusText;

    public Dictionary<string, int> paintingsDic;
    public GameObject FallBackIndicator;
    public string paintingName;

    public string actorNodeID;
    public string measureNodeID;

    private bool started;
    private float startTime;
    private AudioClip recording;

    [SerializeField] private Player player;
    [SerializeField] private HeatMap heatMapScript;
    [SerializeField] private string mic;
    [SerializeField] private Button btn = null;

    public Neo4jConnector graph = new Neo4jConnector();
    public SteamVR_Action_Boolean triggerAction;
    public SteamVR_Input_Sources handType;

    public float waitTime = 60f;
    [SerializeField] private AgentMode agentMode = AgentMode.Baseline;
    [SerializeField] private RasaCommunication rasa;
    [SerializeField] private RLCommunication rl;
    [SerializeField] private float stableFocusThresholdSeconds = 0.5f;
    [SerializeField] private float rawFocusFallbackWindowSeconds = 1.0f;
    private string stableCurrentObjectName = "";
    private string stableCurrentAoiName = "";
    private string pendingFocusObjectName = "";
    private string pendingFocusAoiName = "";
    private float pendingFocusStartedAt = -1f;
    private string lastValidRawObjectName = "";
    private string lastValidRawAoiName = "";
    private float lastValidRawTimestamp = -1f;
    private static readonly HashSet<string> SupportedRlObjects = new HashSet<string>
    {
        "B1", "B2", "B3", "C5", "C6"
    };

    private IGazeFocusable lastFocus;

    // ================================================================
    // ==================== WRITERS & FILE HANDLES =====================
    // ================================================================
    private StreamWriter textWriter;               // 90 Hz Neo4j stream (Tobii)
    private StreamWriter transcriptionTextWriter;
    private StreamWriter eye120Writer;             // 120 Hz SRanipal stream
    [SerializeField] private float flushIntervalSeconds = 1f;
    [SerializeField] private bool enableEye120Sampling = true;
    [SerializeField] private bool enableDataCollectionAfterActorSetup = true;
    private float nextFlushAt;

    // ================================================================
    // ==================== 120 Hz EYE SAMPLING STATE ==================
    // ================================================================
    private Coroutine _eye120Coroutine;

    private static float _latestPupilLeftMm = float.NaN;
    private static float _latestPupilRightMm = float.NaN;
    private static long _latestSraTsUs = 0;
    private static double _latestUnityTime = 0.0;
    private static long _latestUnixMs = 0;

    private float diagnosticsWindowStart;
    private int diagnosticsFrameCount;
    private int diagnosticsFallbackFrameCount;
    private int diagnosticsFocusedFrameCount;
    private int diagnosticsDbQueryCount;
    private int diagnosticsHeatmapCount;
    private int diagnosticsFileWriteCount;
    private double diagnosticsAddDataMs;
    private double diagnosticsDbMs;
    private double diagnosticsHeatmapMs;
    private double diagnosticsFileWriteMs;
    private double diagnosticsTobiiFetchMs;
    private double diagnosticsRaycastMs;
    private double diagnosticsFocusStateMs;
    private int diagnosticsRaycastHitFrames;
    private int diagnosticsNullFocusFrames;
    private string lastFocusedObject = "None";

    void Awake()
    {
        if (rasa == null)
        {
            rasa = FindObjectOfType<RasaCommunication>(true);
            if (rasa != null)
                Debug.Log($"[GetEyeData] Bound RasaCommunication on '{rasa.gameObject.name}'.");
            else if (agentMode == AgentMode.Baseline)
                Debug.LogError("[GetEyeData] RasaCommunication not found in scene.");
        }

        if (rl == null)
        {
            rl = FindObjectOfType<RLCommunication>(true);
            if (rl != null)
                Debug.Log($"[GetEyeData] Bound RLCommunication on '{rl.gameObject.name}'.");
            else if (agentMode == AgentMode.RL)
                Debug.LogError("[GetEyeData] RLCommunication not found in scene.");
        }
    }

    // ================================================================
    // =========================== UNITY START ========================
    // ================================================================
    void Start()
    {
        paintingsDic = new Dictionary<string, int>();
        diagnosticsWindowStart = Time.realtimeSinceStartup;

        foreach (var device in Microphone.devices)
            Debug.Log("Name: " + device);

        if (triggerAction == null)
            triggerAction = SteamVR_Actions.default_GrabPinch;

        StartCoroutine(PerformEveryNSeconds());
    }

    IEnumerator PerformEveryNSeconds()
    {
        while (true)
        {
            if (started && !triggerAction.GetStateDown(handType))
            {
                Debug.Log("Function performed every 60 seconds");
                if (agentMode == AgentMode.Baseline)
                {
                    if (rasa != null)
                        rasa.SendDataToRasa("prompting_user", "prompting_user");
                    else
                        Debug.LogWarning("[GetEyeData] Skip baseline prompt: rasa is null.");
                }
                else
                {
                    if (rl != null)
                        rl.SendPromptingUser(GetPreferredCurrentObjectName(), GetPreferredCurrentAoiName());
                    else
                        Debug.LogWarning("[GetEyeData] Skip RL prompt: rl is null.");
                }
            }
            yield return new WaitForSeconds(waitTime);
        }
    }

    private void SetStatus(string status)
    {
        if (statusText) statusText.text = filename + ": " + status;
        PerformanceProfiler.LogCustom("UI_STATUS", $"{filename}: {status}");
    }

    // ================================================================
    // ============================ UPDATE =============================
    // ================================================================
    private void Update()
    {
        if (started)
        {
            if (FallBackIndicator != null && FallBackIndicator.activeInHierarchy)
            {
                AddFallbackPointerData();
                FlushWritersIfDue();
                return;
            }
            AddData();
            FlushWritersIfDue();
        }

        if (triggerAction.GetStateDown(handType))
        {
            PerformanceProfiler.LogCustom("INPUT_TRIGGER", $"down hand={handType} t={Time.realtimeSinceStartup:F3}");
            if (agentMode == AgentMode.Baseline)
            {
                if (rasa != null)
                    rasa.CheckMicrophone();
                else
                    Debug.LogWarning("[GetEyeData] Skip baseline trigger: rasa is null.");
            }
            else
            {
                if (rl != null)
                    rl.CheckMicrophone();
                else
                    Debug.LogWarning("[GetEyeData] Skip RL trigger: rl is null.");
            }
        }

        if (triggerAction.GetStateUp(handType))
        {
            PerformanceProfiler.LogCustom("INPUT_TRIGGER", $"up hand={handType} t={Time.realtimeSinceStartup:F3}");
            if (agentMode == AgentMode.Baseline)
            {
                if (rasa != null)
                    rasa.StopDictationEngine();
                else
                    Debug.LogWarning("[GetEyeData] Skip baseline trigger up: rasa is null.");
            }
            else
            {
                if (rl != null)
                    rl.StopDictationEngine(GetPreferredCurrentObjectName(), GetPreferredCurrentAoiName());
                else
                    Debug.LogWarning("[GetEyeData] Skip RL trigger up: rl is null.");
            }
            waitTime = 60f;
        }
    }

    // ================================================================
    // ===================== DATA COLLECTION SETUP =====================
    // ================================================================
    public void StartDataCollection(string recordingName)
    {
        var sw = Stopwatch.StartNew();

        if (agentMode == AgentMode.Baseline)
        {
            actorNodeID = graph.CreateActorNode(recordingName, DateTime.Now.ToString("yyyyMMddHHmmss"));
            Debug.LogError($"[DEBUG] Created Actor node in Neo4j with ID: {actorNodeID}");

            measureNodeID = graph.CreateMeasureNode(actorNodeID);
            Debug.LogError($"[DEBUG] Created Measure node linked to Actor ID: {actorNodeID}, Measure ID: {measureNodeID}");

            Debug.LogError($"[DEBUG] Sending Actor ID {actorNodeID} to Rasa...");
            if (rasa != null)
                rasa.SendDataToRasa("sending_actor_id", actorNodeID);
            else
                Debug.LogWarning("[GetEyeData] Skip baseline setup: rasa is null.");
        }
        else
        {
            actorNodeID = "";
            measureNodeID = "";
            Debug.LogError("[DEBUG] Starting RL session without Neo4j actor/measure dependency.");
            if (rl != null)
                rl.StartSession(recordingName, recordingName);
            else
                Debug.LogWarning("[GetEyeData] Skip RL session start: rl is null.");
        }

        if (enableDataCollectionAfterActorSetup)
        {
            InitializeRecording(recordingName);
        }
        else
        {
            PerformanceProfiler.LogCustom("GETEYEDATA_START", "InitializeRecording skipped for A/B test");
            UnityEngine.Debug.LogWarning("[GetEyeData] InitializeRecording skipped for A/B test.");
        }
        sw.Stop();
        PerformanceProfiler.LogExecutionTime("GetEyeData", "StartDataCollection", (float)sw.Elapsed.TotalMilliseconds);
        PerformanceProfiler.LogCustom("GETEYEDATA_START", $"actor={actorNodeID} measure={measureNodeID} totalMs={sw.Elapsed.TotalMilliseconds:F2}");
        UnityEngine.Debug.Log($"[DIAG] StartDataCollection actor={actorNodeID} measure={measureNodeID} totalMs={sw.Elapsed.TotalMilliseconds:F2}");
    }

    private void InitializeRecording(string recordingName)
    {
        filename = recordingName + " (" + DateTime.Now.ToString("yyyy-MM-dd HH-mm-ss") + ")";

        // -----------------------------------------------------------------
        // === 90 Hz Unity / TobiiXR stream === (Neo4j main source)
        // -----------------------------------------------------------------
        textWriter = new StreamWriter(getPath());
        textWriter.AutoFlush = false;

        string[] rowHeader = new string[] {
            "Timestamp",
            "Player_position_x",
            "Player_position_y",
            "Player_position_z",
            "Object_name",
            "Distance_to_object",
            "Gaze_position_x",
            "Gaze_position_y",
            "Gaze_position_z",
            "Object_gaze_x",
            "Object_gaze_y"
        };
        textWriter.WriteLine(string.Join(",", rowHeader));
        Debug.Log("[EYEDATA 90Hz] Header = " + string.Join(",", rowHeader));

        transcriptionTextWriter = new StreamWriter(getPath(filename + "_transcription.txt")) { AutoFlush = true };

        // -----------------------------------------------------------------
        // === 120 Hz SRanipal-only eye stream === (sidecar file)
        // -----------------------------------------------------------------
        eye120Writer = new StreamWriter(getPath(filename + "_eye120hz.csv"));
        eye120Writer.AutoFlush = false;
        eye120Writer.WriteLine(string.Join(",", new[] {
            "sranipal_ts_us",
            "unity_time_s",
            "unix_time_ms",
            "valid_left",
            "valid_right",
            "valid_combined",
            "gaze_origin_mm_x",
            "gaze_origin_mm_y",
            "gaze_origin_mm_z",
            "gaze_dir_x",
            "gaze_dir_y",
            "gaze_dir_z",
            "pupil_left_mm",
            "pupil_right_mm"
        }));

        started = true;
        nextFlushAt = Time.realtimeSinceStartup + Mathf.Clamp(flushIntervalSeconds, 0.5f, 2f);
        recording = Microphone.Start(mic, false, 2000, 44100);
        startTime = Time.time;

        SetStatus("Recording started - " + (Microphone.devices.Length > 0 ? Microphone.devices[0] : "Mic"));

        if (enableEye120Sampling && _eye120Coroutine == null)
            _eye120Coroutine = StartCoroutine(SampleEye120Hz());
    }

    // ================================================================
    // ========================== MAIN 90Hz ============================
    // ================================================================
    private void AddFallbackPointerData()
    {
        var sw = Stopwatch.StartNew();
        var ray = Camera.main.ScreenPointToRay(Input.mousePosition);
        GameObject focusedGameObject = null;
        Vector3? hitcoord = null;
        Vector2? textureCoord = null;

        var raycastSw = Stopwatch.StartNew();
        var hits = Physics.RaycastAll(ray, 100).OrderBy(h => h.distance);
        raycastSw.Stop();
        diagnosticsRaycastMs += raycastSw.Elapsed.TotalMilliseconds;
        if (hits.Any())
        {
            diagnosticsRaycastHitFrames++;
            var hit = hits.First();
            hitcoord = hit.point;
            textureCoord = hit.textureCoord;
            var focusSw = Stopwatch.StartNew();
            var focusable = hit.transform.GetComponent<IGazeFocusable>();
            if (focusable != null)
            {
                focusedGameObject = hit.transform.gameObject;
                if (lastFocus != null) lastFocus.GazeFocusChanged(false);
                lastFocus = focusable;
                focusable.GazeFocusChanged(true);
            }
            else if (lastFocus != null) lastFocus.GazeFocusChanged(false);
            focusSw.Stop();
            diagnosticsFocusStateMs += focusSw.Elapsed.TotalMilliseconds;
        }
        else
        {
            diagnosticsNullFocusFrames++;
        }

        ProccessData((float)Time.realtimeSinceStartupAsDouble, focusedGameObject, hitcoord, textureCoord);
        sw.Stop();
        diagnosticsFallbackFrameCount++;
        diagnosticsAddDataMs += sw.Elapsed.TotalMilliseconds;
        MaybeFlushDiagnostics();
    }

    private void AddData()
    {
        var sw = Stopwatch.StartNew();
        var tobiiSw = Stopwatch.StartNew();
        var eyeTrackingDataWorld = TobiiXR.GetEyeTrackingData(TobiiXR_TrackingSpace.World);
        var eyeTrackingDataLocal = TobiiXR.GetEyeTrackingData(TobiiXR_TrackingSpace.Local);
        tobiiSw.Stop();
        diagnosticsTobiiFetchMs += tobiiSw.Elapsed.TotalMilliseconds;
        var timestamp = eyeTrackingDataLocal.Timestamp; // use LOCAL timestamp like original

        GameObject focusedGameObject = null;
        var p1 = eyeTrackingDataWorld.GazeRay.Origin;
        var dir = eyeTrackingDataWorld.GazeRay.Direction;
        var ray = new Ray(p1, dir);

        Vector3? hitcoord = null;
        Vector2? textureCoord = null;

        var raycastSw = Stopwatch.StartNew();
        var hits = Physics.RaycastAll(ray, 100).OrderBy(h => h.distance);
        raycastSw.Stop();
        diagnosticsRaycastMs += raycastSw.Elapsed.TotalMilliseconds;
        if (hits.Any())
        {
            diagnosticsRaycastHitFrames++;
            var hit = hits.First();
            hitcoord = hit.point;
            textureCoord = hit.textureCoord;
            var focusSw = Stopwatch.StartNew();
            var focusable = hit.transform.GetComponent<IGazeFocusable>();
            if (focusable != null)
            {
                focusedGameObject = hit.transform.gameObject;
                if (lastFocus != null) lastFocus.GazeFocusChanged(false);
                lastFocus = focusable;
                focusable.GazeFocusChanged(true);
            }
            else if (lastFocus != null) lastFocus.GazeFocusChanged(false);
            focusSw.Stop();
            diagnosticsFocusStateMs += focusSw.Elapsed.TotalMilliseconds;
        }
        else
        {
            diagnosticsNullFocusFrames++;
        }

        ProccessData(timestamp, focusedGameObject, hitcoord, textureCoord);
        sw.Stop();
        diagnosticsAddDataMs += sw.Elapsed.TotalMilliseconds;
        MaybeFlushDiagnostics();
    }

    // === Neo4j-compatible data structure (same as original) ===
    public void ProccessData(float timestamp, GameObject focusedGameObject, Vector3? coord, Vector2? textureCoord)
    {
        diagnosticsFrameCount++;
        var rowDataTemp = new string[11]; // no pupils ever
        rowDataTemp[0] = timestamp.ToString(CultureInfo.InvariantCulture);

        var playerPos = player && player.headCollider ? player.headCollider.transform.position : Vector3.zero;
        rowDataTemp[1] = playerPos.x.ToString(CultureInfo.InvariantCulture);
        rowDataTemp[2] = playerPos.y.ToString(CultureInfo.InvariantCulture);
        rowDataTemp[3] = playerPos.z.ToString(CultureInfo.InvariantCulture);

        if (focusedGameObject != null)
        {
            diagnosticsFocusedFrameCount++;
            lastFocusedObject = focusedGameObject.name;
            var focusobj = focusedGameObject.name.Split(new[] { "_AoI_" }, StringSplitOptions.None);
            string rawObjectName = focusobj[0];
            string parsedAoiName = focusobj.Length > 1 ? focusobj[1] : "";
            rowDataTemp[4] = rawObjectName;
            UpdateLastValidRawFocus(rawObjectName, parsedAoiName);
            UpdateStableFocusState(rawObjectName, parsedAoiName);
            rowDataTemp[5] = Vector3.Distance(focusedGameObject.transform.position, playerPos)
                .ToString(CultureInfo.InvariantCulture);

            if (coord.HasValue)
            {
                rowDataTemp[6] = coord.Value.x.ToString(CultureInfo.InvariantCulture);
                rowDataTemp[7] = coord.Value.y.ToString(CultureInfo.InvariantCulture);
                rowDataTemp[8] = coord.Value.z.ToString(CultureInfo.InvariantCulture);
            }
            else
            {
                rowDataTemp[6] = "None";
                rowDataTemp[7] = "None";
                rowDataTemp[8] = "None";
            }

            if (textureCoord.HasValue)
            {
                rowDataTemp[9] = textureCoord.Value.x.ToString(CultureInfo.InvariantCulture);
                rowDataTemp[10] = textureCoord.Value.y.ToString(CultureInfo.InvariantCulture);
                var heatmapSw = Stopwatch.StartNew();
                heatMapScript.SendData(filename, focusedGameObject, textureCoord.Value);
                heatmapSw.Stop();
                diagnosticsHeatmapCount++;
                diagnosticsHeatmapMs += heatmapSw.Elapsed.TotalMilliseconds;
            }
            else
            {
                rowDataTemp[9] = "None";
                rowDataTemp[10] = "None";
            }

            var dbSw = Stopwatch.StartNew();
            ProcessDatabaseQueries(rowDataTemp);
            dbSw.Stop();
            diagnosticsDbMs += dbSw.Elapsed.TotalMilliseconds;
            //Debug.LogError($"[EYEDATA->NEO4J] Full rowDataTemp = {string.Join(", ", rowDataTemp)}");


        }
        else
        {
            ClearPendingFocusCandidate();
            for (int i = 4; i <= 10; i++) rowDataTemp[i] = "None";
        }

        var fileSw = Stopwatch.StartNew();
        textWriter.WriteLine(string.Join(",", rowDataTemp));
        fileSw.Stop();
        diagnosticsFileWriteCount++;
        diagnosticsFileWriteMs += fileSw.Elapsed.TotalMilliseconds;
    }

    // ================================================================
    // =========================== SAVE / QUIT ========================
    // ================================================================
    public void OnApplicationQuit() => SaveData();

    public void SaveData()
    {
        if (!started) return;
        started = false;

        if (_eye120Coroutine != null)
        {
            StopCoroutine(_eye120Coroutine);
            _eye120Coroutine = null;
        }

        FlushAllWriters();
        try { textWriter?.Close(); } catch { }
        try { eye120Writer?.Close(); } catch { }
        try { transcriptionTextWriter?.Close(); } catch { }

        var micName = string.IsNullOrEmpty(mic) ? null : mic;
        int recordedPosition = -1;
        try
        {
            recordedPosition = Microphone.GetPosition(micName);
        }
        catch (Exception ex)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Microphone.GetPosition failed: {ex.Message}");
        }

        try
        {
            if (Microphone.IsRecording(micName))
                Microphone.End(micName);
        }
        catch (Exception ex)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Microphone.End failed: {ex.Message}");
        }

        if (recording == null)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", "Skip audio save: recording clip is null");
        }
        else if (recording.length <= 0 || recording.samples <= 0)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Skip audio save: invalid clip length={recording.length} samples={recording.samples}");
        }
        else
        {
            int channelCount = Mathf.Max(1, recording.channels);
            int frequency = Mathf.Max(1, recording.frequency);
            int availableFrames = Mathf.Max(0, recording.samples);
            int targetFrames = recordedPosition > 0 ? Mathf.Min(recordedPosition, availableFrames) : 0;

            if (targetFrames <= 0)
            {
                var elapsedSeconds = Mathf.Max(0f, Time.time - startTime);
                targetFrames = Mathf.Min(
                    availableFrames,
                    Mathf.Max(0, Mathf.RoundToInt(elapsedSeconds * frequency))
                );
            }

            PerformanceProfiler.LogCustom(
                "AUDIO_SAVE",
                $"Prepare audio save: mic={micName ?? "<default>"} position={recordedPosition} availableFrames={availableFrames} channels={channelCount} hz={frequency} targetFrames={targetFrames}"
            );

            if (targetFrames <= 0)
            {
                PerformanceProfiler.LogCustom("AUDIO_SAVE", "Skip audio save: targetFrames <= 0");
            }
            else
            {
                try
                {
                    float[] samples = new float[targetFrames * channelCount];
                    recording.GetData(samples, 0);

                    var trimmedRecording = AudioClip.Create("RecordedSound", targetFrames, channelCount, frequency, false, false);
                    trimmedRecording.SetData(samples, 0);
                    SavWav.Save(filename + "_Recording", trimmedRecording);
                    PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Saved trimmed audio frames={targetFrames}, sampleValues={samples.Length}");
                }
                catch (Exception ex)
                {
                    PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Audio save failed: {ex.GetType().Name}: {ex.Message}");
                    Debug.LogException(ex);
                }
            }
        }

        if (agentMode == AgentMode.RL && rl != null)
            rl.EndSession("save_data");

        heatMapScript.SaveData();
        SetStatus("Data saved succesfully!");
    }

    // ================================================================
    // ========================= PATH HANDLING ========================
    // ================================================================
    private string getPath() => getPath(filename + ".csv");
    public static string getPath(string filename)
    {
#if UNITY_EDITOR
        return Application.dataPath + "/OUTPUT/" + filename;
#else
        return Application.dataPath + "/" + filename;
#endif
    }

    // ================================================================
    // ===================== DATABASE QUERIES =========================
    // ================================================================
    private void ProcessDatabaseQueries(string[] rowData)
    {
        if (agentMode == AgentMode.RL)
            return;

        string[] names = {
            "A1", "A2", "A3", "B1",
            "B2", "B3", "B4", "B5",
            "C1", "C2", "C3", "C4",
            "C5", "C6", "D1", "D2",
            "D3", "D4", "D5"
        };

        string aoiName = "";
        string objectName = "";

        if (rowData[4].Length >= 2 && names.Contains(rowData[4].Substring(0, 2)))
        {
            diagnosticsDbQueryCount += 6;
            graph.BuildActionCreationQuery(rowData, actorNodeID);

            graph.BuildDurationCalculationQuery(actorNodeID);

            //this is fucked
            //if (rowData[4].Contains("Painting")) aoiName = "Background";
            //else if (rowData[4].Contains("Text")) aoiName = rowData[4].Substring(0, 2) + "_Text";
            //else if (rowData[4].Length >= 3) aoiName = rowData[4].Substring(3);

            objectName = rowData[4].Substring(0, 2);
            paintingName = objectName;

            graph.BuildTimeSpentOnObjectQuery("objectName", objectName, actorNodeID, measureNodeID);
            graph.BuildFixationCountQuery("objectName", objectName, actorNodeID, measureNodeID);
            graph.BuildTransitionCountQuery("objectName", objectName, actorNodeID, measureNodeID);
            graph.BuildTransitionCountBetweenAOIsQuery(objectName, actorNodeID, measureNodeID);

            if (!string.IsNullOrEmpty(aoiName))
            {
                graph.BuildTimeSpentOnObjectQuery("name", aoiName, actorNodeID, measureNodeID);
                graph.BuildFixationCountQuery("name", aoiName, actorNodeID, measureNodeID);
                graph.BuildTransitionCountQuery("name", aoiName, actorNodeID, measureNodeID);
            }
        }
    }

    private void UpdateStableFocusState(string objectName, string aoiName)
    {
        string normalizedObjectName = NormalizeSupportedRlObjectName(objectName);
        if (string.IsNullOrEmpty(normalizedObjectName))
        {
            stableCurrentObjectName = "";
            stableCurrentAoiName = "";
            ClearPendingFocusCandidate();
            return;
        }

        if (pendingFocusObjectName != normalizedObjectName || pendingFocusAoiName != aoiName)
        {
            pendingFocusObjectName = normalizedObjectName;
            pendingFocusAoiName = aoiName;
            pendingFocusStartedAt = Time.realtimeSinceStartup;
            return;
        }

        if (pendingFocusStartedAt < 0f)
            pendingFocusStartedAt = Time.realtimeSinceStartup;

        if ((Time.realtimeSinceStartup - pendingFocusStartedAt) >= stableFocusThresholdSeconds)
        {
            stableCurrentObjectName = normalizedObjectName;
            stableCurrentAoiName = aoiName;
        }
    }

    private void UpdateLastValidRawFocus(string objectName, string aoiName)
    {
        string normalizedObjectName = NormalizeSupportedRlObjectName(objectName);
        if (string.IsNullOrEmpty(normalizedObjectName))
            return;

        lastValidRawObjectName = normalizedObjectName;
        lastValidRawAoiName = aoiName;
        lastValidRawTimestamp = Time.realtimeSinceStartup;
    }

    private void ClearPendingFocusCandidate()
    {
        pendingFocusObjectName = "";
        pendingFocusAoiName = "";
        pendingFocusStartedAt = -1f;
    }

    public string GetStableCurrentObjectName()
    {
        return stableCurrentObjectName;
    }

    public string GetStableCurrentAoiName()
    {
        return stableCurrentAoiName;
    }

    private string GetPreferredCurrentObjectName()
    {
        if (!string.IsNullOrEmpty(stableCurrentObjectName))
            return stableCurrentObjectName;

        if (HasRecentValidRawFocus())
            return lastValidRawObjectName;

        return "";
    }

    private string GetPreferredCurrentAoiName()
    {
        if (!string.IsNullOrEmpty(stableCurrentAoiName))
            return stableCurrentAoiName;

        if (HasRecentValidRawFocus())
            return lastValidRawAoiName;

        return "";
    }

    private string NormalizeSupportedRlObjectName(string objectName)
    {
        if (string.IsNullOrEmpty(objectName))
            return "";

        string candidate = objectName.Split(new[] { "_AoI_" }, StringSplitOptions.None)[0];
        if (candidate.Contains("_"))
            candidate = candidate.Split('_')[0];

        if (candidate.Length >= 2)
            candidate = candidate.Substring(0, 2);

        return SupportedRlObjects.Contains(candidate) ? candidate : "";
    }

    private bool HasRecentValidRawFocus()
    {
        if (string.IsNullOrEmpty(lastValidRawObjectName) || lastValidRawTimestamp < 0f)
            return false;

        return (Time.realtimeSinceStartup - lastValidRawTimestamp) <= rawFocusFallbackWindowSeconds;
    }

    private void FlushWritersIfDue()
    {
        if (!started) return;
        if (Time.realtimeSinceStartup < nextFlushAt) return;

        FlushAllWriters();
        nextFlushAt = Time.realtimeSinceStartup + Mathf.Clamp(flushIntervalSeconds, 0.5f, 2f);
    }

    private void FlushAllWriters()
    {
        try { textWriter?.Flush(); } catch { }
        try { eye120Writer?.Flush(); } catch { }
        try { transcriptionTextWriter?.Flush(); } catch { }
    }

    private void MaybeFlushDiagnostics()
    {
        if (!started) return;

        float elapsed = Time.realtimeSinceStartup - diagnosticsWindowStart;
        if (elapsed < 2f) return;

        float avgAddDataMs = diagnosticsFrameCount > 0 ? (float)(diagnosticsAddDataMs / diagnosticsFrameCount) : 0f;
        float avgDbMs = diagnosticsDbQueryCount > 0 ? (float)(diagnosticsDbMs / Math.Max(1, diagnosticsFocusedFrameCount)) : 0f;
        float avgHeatmapMs = diagnosticsHeatmapCount > 0 ? (float)(diagnosticsHeatmapMs / diagnosticsHeatmapCount) : 0f;
        float avgFileMs = diagnosticsFileWriteCount > 0 ? (float)(diagnosticsFileWriteMs / diagnosticsFileWriteCount) : 0f;
        float avgTobiiFetchMs = diagnosticsFrameCount > 0 ? (float)(diagnosticsTobiiFetchMs / diagnosticsFrameCount) : 0f;
        float avgRaycastMs = diagnosticsFrameCount > 0 ? (float)(diagnosticsRaycastMs / diagnosticsFrameCount) : 0f;
        float avgFocusStateMs = diagnosticsRaycastHitFrames > 0 ? (float)(diagnosticsFocusStateMs / diagnosticsRaycastHitFrames) : 0f;

        string summary =
            $"window={elapsed:F2}s frames={diagnosticsFrameCount} focused={diagnosticsFocusedFrameCount} fallback={diagnosticsFallbackFrameCount} " +
            $"hits={diagnosticsRaycastHitFrames} noFocus={diagnosticsNullFocusFrames} dbCalls~={diagnosticsDbQueryCount} heatmapCalls={diagnosticsHeatmapCount} fileWrites={diagnosticsFileWriteCount} " +
            $"avgAddDataMs={avgAddDataMs:F3} avgTobiiFetchMs={avgTobiiFetchMs:F3} avgRaycastMs={avgRaycastMs:F3} avgFocusStateMs={avgFocusStateMs:F3} " +
            $"avgDbWindowMs={avgDbMs:F3} avgHeatmapMs={avgHeatmapMs:F3} avgFileWriteMs={avgFileMs:F3} lastFocus={lastFocusedObject}";

        UnityEngine.Debug.Log($"[DIAG][GetEyeData] {summary}");
        PerformanceProfiler.LogCustom("DIAG_GETEYEDATA", summary);

        PerformanceProfiler.LogExecutionTime("GetEyeData", "AddDataWindowAvg", avgAddDataMs);
        if (diagnosticsDbMs > 0)
            PerformanceProfiler.LogDatabaseOperation("GetEyeData.ProcessDatabaseQueriesWindow", (float)diagnosticsDbMs, diagnosticsDbQueryCount);

        diagnosticsWindowStart = Time.realtimeSinceStartup;
        diagnosticsFrameCount = 0;
        diagnosticsFallbackFrameCount = 0;
        diagnosticsFocusedFrameCount = 0;
        diagnosticsDbQueryCount = 0;
        diagnosticsHeatmapCount = 0;
        diagnosticsFileWriteCount = 0;
        diagnosticsAddDataMs = 0;
        diagnosticsDbMs = 0;
        diagnosticsHeatmapMs = 0;
        diagnosticsFileWriteMs = 0;
        diagnosticsTobiiFetchMs = 0;
        diagnosticsRaycastMs = 0;
        diagnosticsFocusStateMs = 0;
        diagnosticsRaycastHitFrames = 0;
        diagnosticsNullFocusFrames = 0;
    }

    // ================================================================
    // ====================== 120 Hz EYE POLLER ========================
    // ================================================================
    private IEnumerator SampleEye120Hz()
    {
        var wait = new WaitForSecondsRealtime(1f / 120f);
        EyeData eyeData = new EyeData();
        VerboseData verbose;
        int emptyFrames = 0;

        while (started)
        {
            long sraTsUs = 0;
            var err = SRanipal_Eye_API.GetEyeData(ref eyeData);
            if (err == ViveSR.Error.WORK)
                sraTsUs = eyeData.timestamp;
            else if (++emptyFrames == 30)
                Debug.LogWarning("[SRanipal] EyeData not ready (is SRanipal running?)");

            bool gotVerbose = SRanipal_Eye.GetVerboseData(out verbose);

            Vector3 origin_mm = Vector3.zero;
            Vector3 dir_norm = Vector3.forward;
            float pupilL = float.NaN, pupilR = float.NaN;
            int validL = 0, validR = 0, validC = 0;

            if (gotVerbose)
            {
                var comb = verbose.combined.eye_data;
                origin_mm = new Vector3(
                    comb.gaze_origin_mm.x, comb.gaze_origin_mm.y, comb.gaze_origin_mm.z);
                dir_norm = new Vector3(
                    comb.gaze_direction_normalized.x, comb.gaze_direction_normalized.y, comb.gaze_direction_normalized.z);

                pupilL = verbose.left.pupil_diameter_mm;
                pupilR = verbose.right.pupil_diameter_mm;
                if (pupilL > 0f) validL = 1; else pupilL = float.NaN;
                if (pupilR > 0f) validR = 1; else pupilR = float.NaN;
                validC = (validL + validR > 0) ? 1 : 0;
                emptyFrames = 0;
            }

            _latestPupilLeftMm = pupilL;
            _latestPupilRightMm = pupilR;
            _latestSraTsUs = sraTsUs;
            _latestUnityTime = Time.realtimeSinceStartupAsDouble;
            _latestUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            if (eye120Writer != null)
            {
                string line = string.Join(",",
                    sraTsUs.ToString(CultureInfo.InvariantCulture),
                    _latestUnityTime.ToString(CultureInfo.InvariantCulture),
                    _latestUnixMs.ToString(CultureInfo.InvariantCulture),
                    validL.ToString(),
                    validR.ToString(),
                    validC.ToString(),
                    origin_mm.x.ToString(CultureInfo.InvariantCulture),
                    origin_mm.y.ToString(CultureInfo.InvariantCulture),
                    origin_mm.z.ToString(CultureInfo.InvariantCulture),
                    dir_norm.x.ToString(CultureInfo.InvariantCulture),
                    dir_norm.y.ToString(CultureInfo.InvariantCulture),
                    dir_norm.z.ToString(CultureInfo.InvariantCulture),
                    float.IsNaN(pupilL) ? "NaN" : pupilL.ToString(CultureInfo.InvariantCulture),
                    float.IsNaN(pupilR) ? "NaN" : pupilR.ToString(CultureInfo.InvariantCulture)
                );
                eye120Writer.WriteLine(line);
            }

            yield return wait;
        }
    }
}






