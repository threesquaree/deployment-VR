using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
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
    private string sessionOutputBaseName = "";
    private string sessionFolderName = "";
    private string localSessionId = "";
    private string sessionStartUtcTag = "";
    private string sessionStartUtcIso = "";
    private string sessionStartLocalIso = "";
    private string sessionStartLocalTag = "";
    private const string SESSION_DATA_BASE = @"C:\Users\s3533204\Downloads\Research\Research\data\sessions";
    // Each study arm writes into its own subfolder so baseline and RL data never mix.
    // Set from agentMode in Awake(); static because getPath() is static and is also
    // called from SavWav / HeatMap / RecordingReplay. Defaults to the baseline arm.
    private static string SESSION_DATA_ROOT = Path.Combine(SESSION_DATA_BASE, "baseline");
    public Text statusText;

    public Dictionary<string, int> paintingsDic;
    public GameObject FallBackIndicator;
    public string paintingName;

    public string actorNodeID;
    public string measureNodeID;

    private bool started;
    private bool sessionInitialized;
    private float startTime;
    private AudioClip recording;

    // Mic capture buffer. NON-LOOPING, so once MIC_BUFFER_SECONDS elapses the
    // device stops and Microphone.GetPosition returns 0 for the rest of the
    // session. One 2026-07-22 session hit this exactly (audio.wav was precisely
    // 2000.00s). That used to cost only the tail of audio.wav; with speech now
    // sliced out of this same buffer it would kill every remaining turn, so
    // MicHealthCheckIfDue() detects the stop, saves the segment and restarts.
    private const int MIC_BUFFER_SECONDS = 2000;
    private const int MIC_SAMPLE_RATE = 44100;
    private int micSegmentIndex;
    private float nextMicHealthCheckAt = -1f;
    private WhisperSpeechCapture speechCapture;

    [SerializeField] private Player player;
    [SerializeField] private HeatMap heatMapScript;
    [SerializeField] private string mic;
    // Set to e.g. F8 to drive press-to-talk from the keyboard when bench testing
    // without a headset. Leave as None for real sessions.
    [SerializeField] private KeyCode benchPressKey = KeyCode.None;
    [SerializeField] private Button btn = null;

    public Neo4jConnector graph = new Neo4jConnector();
    public SteamVR_Action_Boolean triggerAction;
    public SteamVR_Input_Sources handType;

    public float waitTime = 40f;
    [SerializeField] private AgentMode agentMode = AgentMode.Baseline;
    [SerializeField] private RasaCommunication rasa;
    [SerializeField] private RLCommunication rl;
    [SerializeField] private bool enablePeriodicPrompting = true;
    // RETIRED: the focus-change opener (agent introduces a painting as soon as the
    // visitor settles on it, RL arm only). Kill switch lives here in code rather than on
    // the Inspector flag below, because the scene has enableFocusChangeGreeting
    // serialized to 1 -- changing that field's default would be silently overridden, and
    // an Inspector tick could re-enable the behaviour mid-study by accident.
    // Flip this to true to restore it; the implementation below is untouched.
    private const bool FocusChangeGreetingEnabled = false;
    // Open on a painting as soon as the visitor settles on it (RL arm only).
    [SerializeField] private bool enableFocusChangeGreeting = true;
    // How long the visitor must stay on a new painting before the agent opens on it.
    // Must be well above stableFocusThresholdSeconds (0.5 s), which is only meant to
    // answer "what are they looking at" and clears on a passing glance.
    [SerializeField] private float focusChangeDwellSeconds = 3f;
    [SerializeField] private float focusChangeCooldownSeconds = 8f;
    // Quiet period after ANY agent turn, so an opener never lands on top of a reply
    // the agent is still speaking.
    [SerializeField] private float focusChangeQuietAfterTurnSeconds = 6f;
    private readonly HashSet<string> focusChangeGreetedExhibits = new HashSet<string>();
    private float nextFocusChangeAllowedAt = -1f;
    private float stableFocusSince = -1f;
    [SerializeField] private int maxBaselineSilencePrompts = 3;
    [SerializeField] private float stableFocusThresholdSeconds = 0.5f;
    [SerializeField] private float rawFocusFallbackWindowSeconds = 1.0f;
    [SerializeField] private float enterNoneThresholdSeconds = 2.0f;
    private string stableCurrentObjectName = "";
    private string stableCurrentAoiName = "";
    private string pendingFocusObjectName = "";
    private string pendingFocusAoiName = "";
    private float pendingFocusStartedAt = -1f;
    private string lastValidRawObjectName = "";
    private string lastValidRawAoiName = "";
    private float lastValidRawTimestamp = -1f;
    private float noSupportedFocusStartedAt = -1f;
    private bool periodicPromptArmed = false;
    private float nextPromptAt = -1f;
    private int lastObservedSuccessfulUserTurnCount = 0;
    private int baselineSilencePromptCount = 0;
    private Coroutine baselinePromptArmCoroutine = null;
    private bool loggedSkippedLegacyNeo4jQueries = false;
    private static readonly HashSet<string> SupportedRlObjects = new HashSet<string>
    {
        "B1", "B2", "B3", "C5", "C6"
    };

    [System.Serializable]
    private class SessionTurnRecord
    {
        public string record_type;
        public string turn_id;
        public int turn_number;
        public string trigger_source;
        public string agent_tts_end_ts;
    }

    public string CurrentSessionId => localSessionId;
    public string CurrentParticipantId => actorNodeID;
    public string CurrentSessionFolderName
    {
        get
        {
            if (!string.IsNullOrEmpty(sessionFolderName))
                return sessionFolderName;
            if (string.IsNullOrEmpty(localSessionId) || string.IsNullOrEmpty(sessionStartLocalTag))
                return "";
            string sourceTag = agentMode == AgentMode.RL ? "rl" : "ca";
            return sourceTag + "_" + localSessionId + "_" + sessionStartLocalTag;
        }
    }

    private IGazeFocusable lastFocus;

    // ================================================================
    // ==================== WRITERS & FILE HANDLES =====================
    // ================================================================
    private StreamWriter textWriter;               // 90 Hz Neo4j stream (Tobii)
    private StreamWriter transcriptionTextWriter;
    private StreamWriter eye120Writer;             // 120 Hz SRanipal stream
    private StreamWriter fixationWriter;           // fixation event stream
    [SerializeField] private float flushIntervalSeconds = 1f;
    [SerializeField] private bool enableEye120Sampling = true;
    [SerializeField] private bool enableFixationEventStream = true;
    [SerializeField] private float fixationMinDurationMs = 100f;
    [SerializeField] private float fixationMaxGapMs = 120f;
    [SerializeField] private string fixationAlgorithmVersion = "focus_segment_v1";
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

    private bool fixationActive;
    private int fixationIdCounter;
    private long fixationStartTsMs;
    private long fixationLastTsMs;
    private int fixationSampleCount;
    private int fixationValidFocusCount;
    private float fixationSumX;
    private float fixationSumY;
    private float fixationSumZ;
    private float fixationMaxObservedGapMs;
    private string fixationObjectNameNorm = "";
    private string fixationAoiNameNorm = "";
    private string fixationFocusSource = "none";
    private string fixationSessionId = "";

    void Awake()
    {
        SESSION_DATA_ROOT = Path.Combine(SESSION_DATA_BASE, agentMode == AgentMode.RL ? "rl" : "baseline");
        Directory.CreateDirectory(SESSION_DATA_ROOT);
        Debug.Log($"[GetEyeData] Agent mode = {agentMode}; session data root = {SESSION_DATA_ROOT}");

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
            if (enablePeriodicPrompting && started && agentMode == AgentMode.RL && rl != null)
            {
                if (rl.HasReceivedSuccessfulUserTurn && !periodicPromptArmed)
                {
                    periodicPromptArmed = true;
                    nextPromptAt = Time.realtimeSinceStartup + waitTime;
                    lastObservedSuccessfulUserTurnCount = rl.SuccessfulUserTurnCount;
                }

                if (periodicPromptArmed && rl.SuccessfulUserTurnCount > lastObservedSuccessfulUserTurnCount)
                {
                    lastObservedSuccessfulUserTurnCount = rl.SuccessfulUserTurnCount;
                    nextPromptAt = Time.realtimeSinceStartup + waitTime;
                }
            }

            if (enablePeriodicPrompting && started && periodicPromptArmed && Time.realtimeSinceStartup >= nextPromptAt && !triggerAction.GetStateDown(handType) && !SpeechInProgress())
            {
                Debug.Log($"[GetEyeData] Silence timer fired after {waitTime:F0} seconds.");
                if (agentMode == AgentMode.Baseline)
                {
                    if (rasa != null)
                    {
                        rasa.SendDataToRasa("prompting_user", "prompting_user", GetPreferredCurrentObjectName(), GetPreferredCurrentAoiName());
                        BeginWaitingForBaselineAgentTtsEnd(true);
                    }
                    else
                        Debug.LogWarning("[GetEyeData] Skip baseline prompt: rasa is null.");
                }
                else
                {
                    if (rl != null)
                        rl.SendSilenceTurn(GetPreferredCurrentObjectName(), GetPreferredCurrentAoiName(), waitTime);
                    else
                        Debug.LogWarning("[GetEyeData] Skip RL silence turn: rl is null.");
                }
                periodicPromptArmed = false;
            }

            yield return new WaitForSeconds(1f);
        }
    }

    private void SetStatus(string status)
    {
        if (statusText) statusText.text = filename + ": " + status;
        PerformanceProfiler.LogCustom("UI_STATUS", $"{filename}: {status}");
    }

    private void StopBaselinePromptArmWatcher()
    {
        if (baselinePromptArmCoroutine != null)
        {
            StopCoroutine(baselinePromptArmCoroutine);
            baselinePromptArmCoroutine = null;
        }
    }

    private void CancelBaselinePromptScheduling()
    {
        StopBaselinePromptArmWatcher();
        periodicPromptArmed = false;
        nextPromptAt = -1f;
    }

    private string GetTurnsJsonlPath()
    {
        if (string.IsNullOrEmpty(sessionFolderName))
            return null;
        return Path.Combine(SESSION_DATA_ROOT, sessionFolderName, "turns.jsonl");
    }

    private bool TryGetLatestInteractionTurn(string turnsPath, out SessionTurnRecord latestTurn)
    {
        latestTurn = null;
        if (string.IsNullOrEmpty(turnsPath) || !File.Exists(turnsPath))
            return false;

        try
        {
            foreach (string raw in File.ReadAllLines(turnsPath))
            {
                if (string.IsNullOrWhiteSpace(raw))
                    continue;
                SessionTurnRecord parsed = JsonUtility.FromJson<SessionTurnRecord>(raw);
                if (parsed == null || parsed.record_type != "interaction")
                    continue;
                latestTurn = parsed;
            }
            return latestTurn != null;
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[GetEyeData] Failed reading turns.jsonl: " + ex.Message);
            return false;
        }
    }

    private void BeginWaitingForBaselineAgentTtsEnd(bool countSilencePromptOnSuccess = false)
    {
        if (!enablePeriodicPrompting || !started || agentMode != AgentMode.Baseline)
            return;
        if (baselineSilencePromptCount >= maxBaselineSilencePrompts)
            return;

        string turnsPath = GetTurnsJsonlPath();
        string previousTurnId = "";
        if (TryGetLatestInteractionTurn(turnsPath, out SessionTurnRecord latestTurn) && latestTurn != null)
            previousTurnId = latestTurn.turn_id ?? "";

        StopBaselinePromptArmWatcher();
        baselinePromptArmCoroutine = StartCoroutine(WaitForBaselineAgentTtsEndAndArm(turnsPath, previousTurnId, countSilencePromptOnSuccess));
    }

    private IEnumerator WaitForBaselineAgentTtsEndAndArm(string turnsPath, string previousTurnId, bool countSilencePromptOnSuccess)
    {
        float startedAt = Time.realtimeSinceStartup;
        const float timeoutSeconds = 120f;

        while (started && agentMode == AgentMode.Baseline && Time.realtimeSinceStartup - startedAt <= timeoutSeconds)
        {
            if (TryGetLatestInteractionTurn(turnsPath, out SessionTurnRecord latestTurn) &&
                latestTurn != null &&
                !string.IsNullOrEmpty(latestTurn.turn_id) &&
                latestTurn.turn_id != previousTurnId &&
                !string.IsNullOrEmpty(latestTurn.agent_tts_end_ts))
            {
                if (countSilencePromptOnSuccess && latestTurn.trigger_source == "proactive_prompt")
                    baselineSilencePromptCount += 1;
                ArmPeriodicPromptTimer(latestTurn.agent_tts_end_ts);
                baselinePromptArmCoroutine = null;
                yield break;
            }

            yield return new WaitForSeconds(0.25f);
        }

        baselinePromptArmCoroutine = null;
    }

    private void ArmPeriodicPromptTimer(string agentTtsEndTs = null)
    {
        if (agentMode == AgentMode.Baseline && baselineSilencePromptCount >= maxBaselineSilencePrompts)
        {
            periodicPromptArmed = false;
            nextPromptAt = -1f;
            return;
        }

        float remainingSeconds = waitTime;
        if (!string.IsNullOrEmpty(agentTtsEndTs))
        {
            try
            {
                DateTime parsed = DateTime.Parse(agentTtsEndTs, null, DateTimeStyles.RoundtripKind);
                double elapsedSeconds = (DateTime.UtcNow - parsed.ToUniversalTime()).TotalSeconds;
                remainingSeconds = Mathf.Max(0f, waitTime - (float)elapsedSeconds);
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[GetEyeData] Failed to parse agent_tts_end_ts: " + ex.Message);
                remainingSeconds = waitTime;
            }
        }
        periodicPromptArmed = true;
        nextPromptAt = Time.realtimeSinceStartup + remainingSeconds;
    }

    // ================================================================
    // ============================ UPDATE =============================
    // ================================================================
    private void Update()
    {
        if (started)
        {
            // Mouse-pointer gaze when the SteamVR fallback objects are active,
            // eye-tracked gaze otherwise. This must NOT return early: the
            // press-to-talk handling below is the desk-test affordance, and it is
            // needed precisely when the fallback path is the one running. Returning
            // here made the two no-headset affordances mutually exclusive, so F8
            // never reached the trigger block.
            if (FallBackIndicator != null && FallBackIndicator.activeInHierarchy)
                AddFallbackPointerData();
            else
                AddData();

            FlushWritersIfDue();
        }

        // Bench affordance: lets the whole press-to-talk path be exercised at a
        // desk without the headset. Defaults to None, so it is inert in a study.
        bool benchDown = benchPressKey != KeyCode.None && Input.GetKeyDown(benchPressKey);
        bool benchUp = benchPressKey != KeyCode.None && Input.GetKeyUp(benchPressKey);

        if (triggerAction.GetStateDown(handType) || benchDown)
        {
            PerformanceProfiler.LogCustom("INPUT_TRIGGER", $"down hand={handType} t={Time.realtimeSinceStartup:F3}");
            if (agentMode == AgentMode.Baseline)
            {
                if (enablePeriodicPrompting && started)
                    CancelBaselinePromptScheduling();

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

        if (triggerAction.GetStateUp(handType) || benchUp)
        {
            PerformanceProfiler.LogCustom("INPUT_TRIGGER", $"up hand={handType} t={Time.realtimeSinceStartup:F3}");
            if (agentMode == AgentMode.Baseline)
            {
                if (rasa != null)
                    rasa.StopDictationEngine(GetPreferredCurrentObjectName(), GetPreferredCurrentAoiName());
                else
                    Debug.LogWarning("[GetEyeData] Skip baseline trigger up: rasa is null.");

                if (enablePeriodicPrompting && started)
                    BeginWaitingForBaselineAgentTtsEnd(false);
            }
            else
            {
                if (rl != null)
                    rl.StopDictationEngine(GetPreferredCurrentObjectName(), GetPreferredCurrentAoiName());
                else
                    Debug.LogWarning("[GetEyeData] Skip RL trigger up: rl is null.");
            }
        }
    }

    // ================================================================
    // ===================== DATA COLLECTION SETUP =====================
    // ================================================================
    public void StartDataCollection(string recordingName)
    {
        var sw = Stopwatch.StartNew();

        if (sessionInitialized)
        {
            PerformanceProfiler.LogCustom("GETEYEDATA_START", "Ignored duplicate StartDataCollection call (session already initialized)");
            UnityEngine.Debug.LogWarning("[GetEyeData] StartDataCollection ignored: session already initialized.");
            return;
        }
        sessionInitialized = true;
        EnsureSessionIdentity();

        if (agentMode == AgentMode.Baseline)
        {
            actorNodeID = recordingName;
            measureNodeID = "";
            Debug.LogError($"[DEBUG] Starting baseline session without Neo4j actor/measure dependency. participant_id={actorNodeID}");

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
                rl.StartSession(recordingName, recordingName, localSessionId, sessionStartUtcIso, sessionStartLocalIso);
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
        stableCurrentObjectName = "";
        stableCurrentAoiName = "";
        lastValidRawObjectName = "";
        lastValidRawAoiName = "";
        lastValidRawTimestamp = -1f;
        ClearPendingFocusCandidate();
        ClearNoSupportedFocusWindow();
        // Each session gets a fresh set of openers.
        focusChangeGreetedExhibits.Clear();
        nextFocusChangeAllowedAt = -1f;
        stableFocusSince = -1f;
        StopBaselinePromptArmWatcher();
        periodicPromptArmed = false;
        nextPromptAt = -1f;
        lastObservedSuccessfulUserTurnCount = 0;
        baselineSilencePromptCount = 0;
        PerformanceProfiler.LogExecutionTime("GetEyeData", "StartDataCollection", (float)sw.Elapsed.TotalMilliseconds);
        PerformanceProfiler.LogCustom("GETEYEDATA_START", $"actor={actorNodeID} measure={measureNodeID} totalMs={sw.Elapsed.TotalMilliseconds:F2}");
        UnityEngine.Debug.Log($"[DIAG] StartDataCollection actor={actorNodeID} measure={measureNodeID} totalMs={sw.Elapsed.TotalMilliseconds:F2}");
    }

    private void InitializeRecording(string recordingName)
    {
        string sessionStem = recordingName + " (" + DateTime.Now.ToString("yyyy-MM-dd HH-mm-ss") + ")";
        filename = sessionStem;
        EnsureSessionIdentity();
        string sourceTag = agentMode == AgentMode.RL ? "rl" : "ca";
        sessionFolderName = sourceTag + "_" + localSessionId + "_" + sessionStartLocalTag;
        sessionOutputBaseName = sessionFolderName;
        Directory.CreateDirectory(getPath(sessionFolderName));
        WriteSessionMeta(sourceTag);

        // -----------------------------------------------------------------
        // === 90 Hz Unity / TobiiXR stream === (Neo4j main source)
        // -----------------------------------------------------------------
        textWriter = new StreamWriter(getPath(Path.Combine(sessionFolderName, "gaze_90hz.csv")));
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
            "Object_gaze_y",
            "aoi_name_raw",
            "aoi_name_norm",
            "object_name_norm",
            "focus_source",
            "is_valid_focus",
            "session_id",
            "sample_ts"
        };
        textWriter.WriteLine(string.Join(",", rowHeader));
        Debug.Log("[EYEDATA 90Hz] Header = " + string.Join(",", rowHeader));

        transcriptionTextWriter = new StreamWriter(getPath(Path.Combine(sessionFolderName, "transcript.txt"))) { AutoFlush = true };

        // -----------------------------------------------------------------
        // === 120 Hz SRanipal-only eye stream === (sidecar file)
        // -----------------------------------------------------------------
        eye120Writer = new StreamWriter(getPath(Path.Combine(sessionFolderName, "gaze_120hz.csv")));
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

        if (enableFixationEventStream)
        {
            fixationWriter = new StreamWriter(getPath(Path.Combine(sessionFolderName, "fixations.csv")));
            fixationWriter.AutoFlush = false;
            fixationWriter.WriteLine(string.Join(",", new[] {
                "session_id",
                "fix_id",
                "start_ts",
                "end_ts",
                "duration_ms",
                "centroid_x",
                "centroid_y",
                "centroid_z",
                "object_name_norm",
                "aoi_name_norm",
                "n_samples",
                "quality_score",
                "algorithm_version",
                "focus_source",
                "is_valid_focus"
            }));
        }

        ResetFixationState();

        started = true;
        nextFlushAt = Time.realtimeSinceStartup + Mathf.Clamp(flushIntervalSeconds, 0.5f, 2f);
        // Resolve the device once, the same way the save path does -- passing the
        // raw (empty) `mic` here while normalizing to null elsewhere meant Start
        // and GetPosition could target different devices.
        string micDevice = ResolvedMicDevice();
        recording = Microphone.Start(micDevice, false, MIC_BUFFER_SECONDS, MIC_SAMPLE_RATE);
        startTime = Time.time;
        micSegmentIndex = 0;
        nextMicHealthCheckAt = Time.realtimeSinceStartup + 2f;
        PerformanceProfiler.LogCustom(
            "AUDIO",
            $"mic_started device={micDevice ?? "<default>"} hz={MIC_SAMPLE_RATE} buffer_s={MIC_BUFFER_SECONDS} samples={(recording == null ? "null" : recording.samples.ToString())}"
        );

        SetStatus("Recording started - " + (Microphone.devices.Length > 0 ? Microphone.devices[0] : "Mic"));

        if (enableEye120Sampling && _eye120Coroutine == null)
            _eye120Coroutine = StartCoroutine(SampleEye120Hz());
    }

    // ================================================================
    // ===================== MIC ACCESS (Whisper STT) =================
    // ================================================================
    // Read-only surface used by WhisperSpeechCapture to slice the utterance out
    // of the live mic buffer. Nothing here mutates capture state.

    /// <summary>Called by WhisperSpeechCapture.Attach so the mic watchdog can avoid
    /// rotating the buffer mid-utterance.</summary>
    public void RegisterSpeechCapture(WhisperSpeechCapture capture) => speechCapture = capture;

    /// <summary>True while a visitor utterance is being captured OR transcribed. Proactive
    /// turns must stay quiet across this whole window: releasing the trigger only starts the
    /// STT round-trip, and a prompt sent before the transcript lands claims the single
    /// in-flight request slot that the visitor's own question then needs.</summary>
    private bool SpeechInProgress() => speechCapture != null && speechCapture.IsBusy;

    public bool IsMicCaptureActive => started && recording != null;
    public AudioClip MicClip => recording;
    public int MicFrequency => recording != null ? recording.frequency : MIC_SAMPLE_RATE;
    public int MicChannels => recording != null ? Mathf.Max(1, recording.channels) : 1;

    /// <summary>Single normalization point for the mic device name. Returns null
    /// (system default) for blank or unknown names so we never throw on a device
    /// that has been unplugged between sessions.</summary>
    public string ResolvedMicDevice()
    {
        string want = string.IsNullOrWhiteSpace(mic) ? null : mic.Trim();
        if (want == null)
            return null;
        var devices = Microphone.devices ?? new string[0];
        if (Array.IndexOf(devices, want) < 0)
        {
            PerformanceProfiler.LogCustom(
                "AUDIO", $"mic '{want}' not present in [{string.Join(" | ", devices)}] -> default");
            return null;
        }
        return want;
    }

    public int GetMicSamplePosition()
    {
        try { return Microphone.GetPosition(ResolvedMicDevice()); }
        catch (Exception ex)
        {
            PerformanceProfiler.LogCustom("AUDIO", $"GetPosition failed: {ex.Message}");
            return -1;
        }
    }

    public bool IsMicHardwareRecording()
    {
        try { return Microphone.IsRecording(ResolvedMicDevice()); }
        catch (Exception) { return false; }
    }

    /// <summary>Where per-utterance WAVs go. Falls back to an orphan folder so a
    /// turn captured before/after a session is still kept rather than dropped.</summary>
    public string SessionSpeechFolder()
    {
        string folder = string.IsNullOrEmpty(sessionFolderName)
            ? Path.Combine("_orphan_speech", DateTime.Now.ToString("yyyy-MM-dd"))
            : Path.Combine(sessionFolderName, "speech");
        return getPath(folder);
    }

    /// <summary>Copy [startSample, startSample+frames) out of the live mic clip and
    /// encode it as a mono 16-bit WAV. Mono is required: WavUtility's size math
    /// ignores channel count, so a stereo clip would produce a malformed file.</summary>
    public byte[] EncodeMicWindowToWav(int startSample, int frames)
    {
        float peak, rms;
        return EncodeMicWindowToWav(startSample, frames, out peak, out rms);
    }

    /// <summary>Also reports the window's signal level so the caller can tell a
    /// dead microphone (digital silence) apart from a participant who simply did
    /// not speak. Measured on a real test run: silent windows peak at 0.0004-0.003
    /// while genuine speech peaks at 0.10-0.54.</summary>
    public byte[] EncodeMicWindowToWav(int startSample, int frames, out float peak, out float rms)
    {
        peak = 0f;
        rms = 0f;
        if (recording == null || frames <= 0)
            return null;

        int channels = Mathf.Max(1, recording.channels);
        int available = Mathf.Max(0, recording.samples - startSample);
        frames = Mathf.Min(frames, available);
        if (frames <= 0)
            return null;

        var interleaved = new float[frames * channels];
        recording.GetData(interleaved, startSample);

        float[] mono;
        if (channels == 1)
        {
            mono = interleaved;
        }
        else
        {
            mono = new float[frames];
            for (int i = 0; i < frames; i++)
            {
                float sum = 0f;
                for (int c = 0; c < channels; c++) sum += interleaved[i * channels + c];
                mono[i] = sum / channels;
            }
        }

        double sumSq = 0.0;
        for (int i = 0; i < frames; i++)
        {
            float v = mono[i];
            if (v < 0f) v = -v;
            if (v > peak) peak = v;
            sumSq += (double)mono[i] * mono[i];
        }
        rms = frames > 0 ? Mathf.Sqrt((float)(sumSq / frames)) : 0f;

        var clip = AudioClip.Create("utterance", frames, 1, recording.frequency, false, false);
        clip.SetData(mono, 0);
        return WavUtility.FromAudioClip(clip);
    }

    /// <summary>Detect the non-looping buffer running out (or the device being
    /// lost), preserve what was captured, and restart into a fresh clip so speech
    /// capture keeps working for the rest of the session.</summary>
    private void MicHealthCheckIfDue()
    {
        if (!started || recording == null) return;
        if (Time.realtimeSinceStartup < nextMicHealthCheckAt) return;
        nextMicHealthCheckAt = Time.realtimeSinceStartup + 2f;

        if (IsMicHardwareRecording()) return;
        // Never rotate mid-utterance -- retry on the next tick instead.
        if (speechCapture != null && speechCapture.IsArmed) return;

        PerformanceProfiler.LogCustom(
            "AUDIO", $"mic_stopped detected (buffer cap or device loss) -> rotating segment {micSegmentIndex}");

        SaveMicSegment(micSegmentIndex == 0 ? "audio" : $"audio_part{micSegmentIndex:D2}");
        micSegmentIndex++;

        try { Microphone.End(ResolvedMicDevice()); } catch (Exception) { }
        recording = Microphone.Start(ResolvedMicDevice(), false, MIC_BUFFER_SECONDS, MIC_SAMPLE_RATE);
        startTime = Time.time;
        PerformanceProfiler.LogCustom(
            "AUDIO", $"mic_restarted segment={micSegmentIndex} samples={(recording == null ? "null" : recording.samples.ToString())}");
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

            // Take the nearest FOCUSABLE hit rather than requiring the nearest hit
            // overall to be focusable. Desk mode only: with the mouse ray, colliders
            // that sit between the camera and a painting (teleport areas, UI planes,
            // the fallback hand) are closest every frame and would swallow focus --
            // observed as hits=1483 focused=0. The eye-tracked path in AddData() is
            // deliberately left alone so study behaviour is unchanged.
            IGazeFocusable focusable = null;
            foreach (var candidate in hits)
            {
                var f = candidate.transform.GetComponent<IGazeFocusable>();
                if (f != null)
                {
                    focusable = f;
                    focusedGameObject = candidate.transform.gameObject;
                    hitcoord = candidate.point;
                    textureCoord = candidate.textureCoord;
                    break;
                }
            }

            if (focusable != null)
            {
                if (lastFocus != null && !ReferenceEquals(lastFocus, focusable))
                    lastFocus.GazeFocusChanged(false);
                lastFocus = focusable;
                focusable.GazeFocusChanged(true);
            }
            else if (lastFocus != null)
            {
                lastFocus.GazeFocusChanged(false);
            }
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
        var rowDataTemp = new string[18];
        rowDataTemp[0] = timestamp.ToString(CultureInfo.InvariantCulture);

        var playerPos = player && player.headCollider ? player.headCollider.transform.position : Vector3.zero;
        rowDataTemp[1] = playerPos.x.ToString(CultureInfo.InvariantCulture);
        rowDataTemp[2] = playerPos.y.ToString(CultureInfo.InvariantCulture);
        rowDataTemp[3] = playerPos.z.ToString(CultureInfo.InvariantCulture);

        if (focusedGameObject != null)
        {
            diagnosticsFocusedFrameCount++;
            lastFocusedObject = focusedGameObject.name;
            string rawObjectName;
            string parsedAoiName;
            ExtractFocusNames(focusedGameObject.name, out rawObjectName, out parsedAoiName);
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
                heatMapScript.SendData(Path.Combine(sessionFolderName, "heatmaps"), focusedGameObject, textureCoord.Value);
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
            BeginNoSupportedFocusWindow();
            ClearPendingFocusCandidate();
            for (int i = 4; i <= 10; i++) rowDataTemp[i] = "None";
        }

        string objectNameRaw = (focusedGameObject != null && rowDataTemp[4] != "None") ? rowDataTemp[4] : "";
        string aoiNameRaw = "";
        if (focusedGameObject != null)
        {
            string parsedObjectName;
            ExtractFocusNames(focusedGameObject.name, out parsedObjectName, out aoiNameRaw);
        }

        string objectNameNorm = NormalizeSupportedRlObjectName(objectNameRaw);
        string aoiNameNorm = NormalizeAoiNameForRl(aoiNameRaw);

        string focusSource;
        if (HasConfirmedNoFocus())
            focusSource = "none";
        else if (!string.IsNullOrEmpty(stableCurrentObjectName))
            focusSource = "stable";
        else if (HasRecentValidRawFocus())
            focusSource = "raw_fallback";
        else
            focusSource = "none";

        string isValidFocus = (!string.IsNullOrEmpty(objectNameNorm) && focusSource != "none") ? "1" : "0";

        rowDataTemp[11] = string.IsNullOrEmpty(aoiNameRaw) ? "None" : aoiNameRaw;
        rowDataTemp[12] = string.IsNullOrEmpty(aoiNameNorm) ? "None" : aoiNameNorm;
        rowDataTemp[13] = string.IsNullOrEmpty(objectNameNorm) ? "None" : objectNameNorm;
        rowDataTemp[14] = focusSource;
        rowDataTemp[15] = isValidFocus;
        rowDataTemp[16] = string.IsNullOrEmpty(localSessionId) ? "None" : localSessionId;
        rowDataTemp[17] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString(CultureInfo.InvariantCulture);

        var fileSw = Stopwatch.StartNew();
        textWriter.WriteLine(string.Join(",", rowDataTemp));
        UpdateFixationEventStream(rowDataTemp);
        fileSw.Stop();
        diagnosticsFileWriteCount++;
        diagnosticsFileWriteMs += fileSw.Elapsed.TotalMilliseconds;
    }

    private string NormalizeAoiNameForRl(string aoiName)
    {
        if (string.IsNullOrEmpty(aoiName))
            return "";

        string candidate = aoiName.Trim();
        if (string.Equals(candidate, "The ivory tusk", StringComparison.OrdinalIgnoreCase))
            return "Ivory tusk";

        return candidate;
    }

    private void ExtractFocusNames(string focusedObjectName, out string rawObjectName, out string parsedAoiName)
    {
        rawObjectName = "";
        parsedAoiName = "";

        if (string.IsNullOrEmpty(focusedObjectName))
            return;

        var legacySplit = focusedObjectName.Split(new[] { "_AoI_" }, StringSplitOptions.None);
        rawObjectName = legacySplit[0];
        if (legacySplit.Length > 1)
        {
            parsedAoiName = legacySplit[1];
            return;
        }

        string normalizedObjectName = NormalizeSupportedRlObjectName(focusedObjectName);
        rawObjectName = string.IsNullOrEmpty(normalizedObjectName) ? legacySplit[0] : normalizedObjectName;
        string prefix = string.IsNullOrEmpty(normalizedObjectName) ? "" : normalizedObjectName + "_";
        if (!string.IsNullOrEmpty(prefix) && focusedObjectName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            string suffix = focusedObjectName.Substring(prefix.Length).Trim();
            if (!ShouldIgnoreAoiLikeSuffix(suffix))
                parsedAoiName = suffix;
        }
    }

    private bool ShouldIgnoreAoiLikeSuffix(string suffix)
    {
        if (string.IsNullOrEmpty(suffix))
            return true;

        string candidate = suffix.Trim();
        return string.Equals(candidate, "Painting", StringComparison.OrdinalIgnoreCase)
            || string.Equals(candidate, "Text", StringComparison.OrdinalIgnoreCase)
            || string.Equals(candidate, "Button", StringComparison.OrdinalIgnoreCase)
            || candidate.EndsWith("-CA", StringComparison.OrdinalIgnoreCase)
            || string.Equals(candidate, "Diego Bemba", StringComparison.OrdinalIgnoreCase)
            || string.Equals(candidate, "Dom Miguel", StringComparison.OrdinalIgnoreCase)
            || string.Equals(candidate, "King Caspar", StringComparison.OrdinalIgnoreCase);
    }

    // ================================================================
    // =========================== SAVE / QUIT ========================
    // ================================================================
    public void OnApplicationQuit() => SaveData();

    // Play-mode stop, scene unload and Editor domain reload all reach OnDestroy
    // but NOT OnApplicationQuit. That gap is why participants 04, 07, 14 and 19
    // have full gaze CSVs (flushed every <=2s) but no audio.wav at all -- the
    // WAV is only written here, once, at the end. Idempotent: SaveData() clears
    // `started` first and its !started branch returns immediately.
    private void OnDestroy()
    {
        try { SaveData(); }
        catch (Exception ex) { Debug.LogError("[GetEyeData] OnDestroy SaveData failed: " + ex); }
    }

    private void OnApplicationPause(bool paused)
    {
        if (!paused) return;
        try { SaveData(); }
        catch (Exception ex) { Debug.LogError("[GetEyeData] OnApplicationPause SaveData failed: " + ex); }
    }

    /// <summary>Write the current mic buffer to &lt;session&gt;/&lt;baseName&gt;.wav.
    /// Shared by the end-of-session save and the buffer-cap watchdog.</summary>
    private void SaveMicSegment(string baseName, int knownPosition = -1)
    {
        if (recording == null)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", "Skip audio save: recording clip is null");
            return;
        }
        if (recording.length <= 0 || recording.samples <= 0)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Skip audio save: invalid clip length={recording.length} samples={recording.samples}");
            return;
        }

        int position = knownPosition;
        if (position < 0)
            position = GetMicSamplePosition();

        int channelCount = Mathf.Max(1, recording.channels);
        int frequency = Mathf.Max(1, recording.frequency);
        int availableFrames = Mathf.Max(0, recording.samples);
        int targetFrames = position > 0 ? Mathf.Min(position, availableFrames) : 0;

        if (targetFrames <= 0)
        {
            // GetPosition returns 0 once a non-looping clip has stopped, so fall
            // back to elapsed wall-clock time to recover what was captured.
            var elapsedSeconds = Mathf.Max(0f, Time.time - startTime);
            targetFrames = Mathf.Min(
                availableFrames,
                Mathf.Max(0, Mathf.RoundToInt(elapsedSeconds * frequency))
            );
        }

        PerformanceProfiler.LogCustom(
            "AUDIO_SAVE",
            $"Prepare audio save: name={baseName} position={position} availableFrames={availableFrames} channels={channelCount} hz={frequency} targetFrames={targetFrames}"
        );

        if (targetFrames <= 0)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", "Skip audio save: targetFrames <= 0");
            return;
        }

        try
        {
            float[] samples = new float[targetFrames * channelCount];
            recording.GetData(samples, 0);

            var trimmedRecording = AudioClip.Create("RecordedSound", targetFrames, channelCount, frequency, false, false);
            trimmedRecording.SetData(samples, 0);
            string recordingBaseName = string.IsNullOrEmpty(sessionFolderName)
                ? baseName
                : Path.Combine(sessionFolderName, baseName);
            SavWav.Save(recordingBaseName, trimmedRecording);
            PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Saved audio '{baseName}' frames={targetFrames}, sampleValues={samples.Length}");
        }
        catch (Exception ex)
        {
            PerformanceProfiler.LogCustom("AUDIO_SAVE", $"Audio save failed: {ex.GetType().Name}: {ex.Message}");
            Debug.LogException(ex);
        }
    }

    public void SaveData()
    {
        if (!started)
        {
            StopBaselinePromptArmWatcher();
            sessionInitialized = false;
            localSessionId = "";
            sessionStartUtcTag = "";
            sessionStartUtcIso = "";
            sessionStartLocalIso = "";
            sessionStartLocalTag = "";
            sessionFolderName = "";
            return;
        }
        started = false;
        StopBaselinePromptArmWatcher();

        if (_eye120Coroutine != null)
        {
            StopCoroutine(_eye120Coroutine);
            _eye120Coroutine = null;
        }

        FinalizeActiveFixationIfNeeded();
        FlushAllWriters();
        try { fixationWriter?.Close(); } catch { }
        try { textWriter?.Close(); } catch { }
        try { eye120Writer?.Close(); } catch { }
        try { transcriptionTextWriter?.Close(); } catch { }

        var micName = ResolvedMicDevice();
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

        SaveMicSegment(micSegmentIndex == 0 ? "audio" : $"audio_part{micSegmentIndex:D2}", recordedPosition);

        speechCapture?.OnSessionEnding("save_data");

        if (agentMode == AgentMode.RL && rl != null)
            rl.EndSession("save_data");

        // Guarded: reached from OnDestroy the heatmap object may already be torn
        // down, and an exception here would abort the rest of the save.
        try { heatMapScript?.SaveData(); }
        catch (Exception ex) { Debug.LogException(ex); }
        SetStatus("Data saved succesfully!");
        sessionInitialized = false;
        localSessionId = "";
        sessionStartUtcTag = "";
        sessionStartUtcIso = "";
        sessionStartLocalIso = "";
        sessionStartLocalTag = "";
        sessionFolderName = "";
    }

    // ================================================================
    // ========================= PATH HANDLING ========================
    // ================================================================
    private string getPath() => getPath(filename + ".csv");
    public static string getPath(string filename)
    {
        if (string.IsNullOrEmpty(filename))
            return SESSION_DATA_ROOT;

        string fullPath = Path.IsPathRooted(filename)
            ? filename
            : Path.Combine(SESSION_DATA_ROOT, filename);
        string directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(directory))
            Directory.CreateDirectory(directory);
        return fullPath;
    }

    private void EnsureSessionIdentity()
    {
        if (string.IsNullOrEmpty(localSessionId))
            localSessionId = Guid.NewGuid().ToString("N");
        if (string.IsNullOrEmpty(sessionStartUtcIso))
            sessionStartUtcIso = DateTime.UtcNow.ToString("o");
        if (string.IsNullOrEmpty(sessionStartLocalIso))
            sessionStartLocalIso = DateTime.Now.ToString("o");
        if (string.IsNullOrEmpty(sessionStartUtcTag))
            sessionStartUtcTag = DateTime.UtcNow.ToString("yyyy-MM-ddTHH-mm-ssZ");
        if (string.IsNullOrEmpty(sessionStartLocalTag))
            sessionStartLocalTag = DateTime.Now.ToString("yyyy-MM-ddTHH-mm-ss");
    }

    private void WriteSessionMeta(string sourceTag)
    {
        try
        {
            string metaPath = getPath(Path.Combine(sessionFolderName, "meta.json"));
            string startedAtUtc = DateTime.UtcNow.ToString("o");
            string participantValue = string.IsNullOrEmpty(filename) ? "unknown" : filename.Replace("\\", "\\\\").Replace("\"", "'");
            string actorValue = string.IsNullOrEmpty(actorNodeID) ? "" : actorNodeID.Replace("\\", "\\\\").Replace("\"", "'");
            string json =
                "{\n" +
                $"  \"source\": \"{sourceTag}\",\n" +
                $"  \"session_id\": \"{localSessionId}\",\n" +
                $"  \"started_at_utc\": \"{(string.IsNullOrEmpty(sessionStartUtcIso) ? startedAtUtc : sessionStartUtcIso)}\",\n" +
                $"  \"started_at_local\": \"{(string.IsNullOrEmpty(sessionStartLocalIso) ? DateTime.Now.ToString("o") : sessionStartLocalIso)}\",\n" +
                $"  \"participant_id\": \"{participantValue}\",\n" +
                $"  \"actor_id\": \"{actorValue}\",\n" +
                $"  \"agent_mode\": \"{agentMode}\",\n" +
                "  \"schema_version\": \"sessions_v1\"\n" +
                "}";
            File.WriteAllText(metaPath, json, Encoding.UTF8);
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[GetEyeData] Failed to write session meta: " + ex.Message);
        }
    }

    // ================================================================
    // ===================== DATABASE QUERIES =========================
    // ================================================================
    private void ProcessDatabaseQueries(string[] rowData)
    {
        if (agentMode == AgentMode.RL)
            return;

        if (string.IsNullOrEmpty(actorNodeID) || string.IsNullOrEmpty(measureNodeID))
        {
            if (!loggedSkippedLegacyNeo4jQueries)
            {
                Debug.Log("[GetEyeData] Skipping legacy Neo4j metric queries for baseline improved mode.");
                loggedSkippedLegacyNeo4jQueries = true;
            }
            return;
        }

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
            BeginNoSupportedFocusWindow();
            ClearPendingFocusCandidate();
            return;
        }

        ClearNoSupportedFocusWindow();

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
            string previousStable = stableCurrentObjectName;
            stableCurrentObjectName = normalizedObjectName;
            stableCurrentAoiName = aoiName;

            // stableFocusThresholdSeconds (0.5 s) is the threshold for "which exhibit
            // is the visitor looking at" and is deliberately twitchy. The greeting
            // needs a much stronger signal -- that they have SETTLED on the painting,
            // not swept past it -- so it runs on its own, longer dwell clock.
            if (normalizedObjectName != previousStable)
                stableFocusSince = Time.realtimeSinceStartup;

            if (stableFocusSince > 0f
                && (Time.realtimeSinceStartup - stableFocusSince) >= focusChangeDwellSeconds)
            {
                MaybeSendFocusChangeTurn(normalizedObjectName, aoiName);
            }
        }
    }

    /// <summary>Open on a painting the visitor has just settled on, rather than making
    /// them wait out the 40 s silence timer. Deployment-only behaviour: in training the
    /// visitor always spoke, so "moved without speaking" had no analogue. Logged with
    /// trigger_source=focus_change so these turns stay separable in analysis.</summary>
    private void MaybeSendFocusChangeTurn(string objectName, string aoiName)
    {
        if (!FocusChangeGreetingEnabled)
            return;
        if (!enableFocusChangeGreeting || !started || agentMode != AgentMode.RL || rl == null)
            return;
        if (string.IsNullOrEmpty(objectName))
            return;
        // Only once per exhibit per session: re-entering a painting should not
        // re-trigger the opener every time the visitor glances back.
        if (focusChangeGreetedExhibits.Contains(objectName))
            return;
        // Never interrupt: not while the visitor is mid-utterance, and not while a
        // request (or the agent's own speech) is still in flight.
        if (rl.IsRequestInFlight || rl.IsCapturingSpeech)
            return;
        if (Time.realtimeSinceStartup < nextFocusChangeAllowedAt)
            return;
        // The agent's reply is spoken server-side, so Unity cannot observe TTS
        // finishing; keep a quiet period after any turn rather than talking over it.
        if (rl.SecondsSinceLastTurn < focusChangeQuietAfterTurnSeconds)
            return;

        if (rl.SendFocusChangeTurn(objectName, aoiName))
        {
            focusChangeGreetedExhibits.Add(objectName);
            nextFocusChangeAllowedAt = Time.realtimeSinceStartup + focusChangeCooldownSeconds;
            Debug.Log($"[GetEyeData] Focus-change turn sent for '{objectName}'.");
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

    private void BeginNoSupportedFocusWindow()
    {
        if (noSupportedFocusStartedAt < 0f)
            noSupportedFocusStartedAt = Time.realtimeSinceStartup;
    }

    private void ClearNoSupportedFocusWindow()
    {
        noSupportedFocusStartedAt = -1f;
    }

    /// <summary>How long the visitor has been looking at nothing the agent supports.
    /// 0 while focus is on a known exhibit. Sent to the RL runtime as turn metadata:
    /// it is the only visitor-disengagement signal the policy can receive, because the
    /// `disengaged` response-type label was behavioural (a fatigue latch) in training,
    /// never something detectable from the transcript.</summary>
    public float GetOffExhibitSeconds()
    {
        if (noSupportedFocusStartedAt < 0f)
            return 0f;
        return Mathf.Max(0f, Time.realtimeSinceStartup - noSupportedFocusStartedAt);
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
        if (HasConfirmedNoFocus())
            return "NONE";

        if (!string.IsNullOrEmpty(stableCurrentObjectName))
            return stableCurrentObjectName;

        if (HasRecentValidRawFocus())
            return lastValidRawObjectName;

        return "";
    }

    private string GetPreferredCurrentAoiName()
    {
        if (HasConfirmedNoFocus())
            return "";

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

    private bool HasConfirmedNoFocus()
    {
        if (noSupportedFocusStartedAt < 0f)
            return false;

        return (Time.realtimeSinceStartup - noSupportedFocusStartedAt) >= enterNoneThresholdSeconds;
    }

    private void FlushWritersIfDue()
    {
        if (!started) return;

        // Piggy-backs on the existing <=2s cadence; it self-throttles internally.
        MicHealthCheckIfDue();

        if (Time.realtimeSinceStartup < nextFlushAt) return;

        FlushAllWriters();
        nextFlushAt = Time.realtimeSinceStartup + Mathf.Clamp(flushIntervalSeconds, 0.5f, 2f);
    }

    private void FlushAllWriters()
    {
        try { textWriter?.Flush(); } catch { }
        try { eye120Writer?.Flush(); } catch { }
        try { fixationWriter?.Flush(); } catch { }
        try { transcriptionTextWriter?.Flush(); } catch { }
    }

    private void ResetFixationState()
    {
        fixationActive = false;
        fixationIdCounter = 0;
        fixationStartTsMs = 0;
        fixationLastTsMs = 0;
        fixationSampleCount = 0;
        fixationValidFocusCount = 0;
        fixationSumX = 0f;
        fixationSumY = 0f;
        fixationSumZ = 0f;
        fixationMaxObservedGapMs = 0f;
        fixationObjectNameNorm = "";
        fixationAoiNameNorm = "";
        fixationFocusSource = "none";
        fixationSessionId = "";
    }

    private void UpdateFixationEventStream(string[] rowData)
    {
        if (!enableFixationEventStream || fixationWriter == null || rowData == null || rowData.Length < 18)
            return;

        long sampleTsMs;
        if (!long.TryParse(rowData[17], NumberStyles.Integer, CultureInfo.InvariantCulture, out sampleTsMs))
            sampleTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        bool isValidFocus = rowData[15] == "1";
        string objectNameNorm = (rowData[13] == "None") ? "" : rowData[13];
        string aoiNameNorm = (rowData[12] == "None") ? "" : rowData[12];
        string focusSource = string.IsNullOrEmpty(rowData[14]) ? "none" : rowData[14];
        string sessionId = (rowData[16] == "None") ? "" : rowData[16];

        float x = 0f, y = 0f, z = 0f;
        bool hasGazeCoordinate =
            float.TryParse(rowData[6], NumberStyles.Float, CultureInfo.InvariantCulture, out x) &&
            float.TryParse(rowData[7], NumberStyles.Float, CultureInfo.InvariantCulture, out y) &&
            float.TryParse(rowData[8], NumberStyles.Float, CultureInfo.InvariantCulture, out z);

        bool isEligibleSample = isValidFocus && !string.IsNullOrEmpty(objectNameNorm) && hasGazeCoordinate;
        if (!isEligibleSample)
        {
            FinalizeActiveFixationIfNeeded();
            return;
        }

        if (!fixationActive)
        {
            StartNewFixation(sampleTsMs, x, y, z, objectNameNorm, aoiNameNorm, focusSource, sessionId);
            return;
        }

        bool hasLabelChange = !string.Equals(objectNameNorm, fixationObjectNameNorm, StringComparison.OrdinalIgnoreCase) ||
                              !string.Equals(aoiNameNorm, fixationAoiNameNorm, StringComparison.OrdinalIgnoreCase);
        long sampleGapMs = sampleTsMs - fixationLastTsMs;
        bool hasDiscontinuity = sampleGapMs < 0 || sampleGapMs > fixationMaxGapMs;

        if (hasLabelChange || hasDiscontinuity)
        {
            FinalizeActiveFixationIfNeeded();
            StartNewFixation(sampleTsMs, x, y, z, objectNameNorm, aoiNameNorm, focusSource, sessionId);
            return;
        }

        fixationSumX += x;
        fixationSumY += y;
        fixationSumZ += z;
        fixationSampleCount++;
        fixationValidFocusCount++;
        if (sampleGapMs > fixationMaxObservedGapMs)
            fixationMaxObservedGapMs = sampleGapMs;
        fixationLastTsMs = sampleTsMs;
    }

    private void StartNewFixation(long sampleTsMs, float x, float y, float z, string objectNameNorm, string aoiNameNorm, string focusSource, string sessionId)
    {
        fixationActive = true;
        fixationStartTsMs = sampleTsMs;
        fixationLastTsMs = sampleTsMs;
        fixationSampleCount = 1;
        fixationValidFocusCount = 1;
        fixationSumX = x;
        fixationSumY = y;
        fixationSumZ = z;
        fixationMaxObservedGapMs = 0f;
        fixationObjectNameNorm = objectNameNorm;
        fixationAoiNameNorm = aoiNameNorm;
        fixationFocusSource = focusSource;
        fixationSessionId = sessionId;
    }

    private void FinalizeActiveFixationIfNeeded()
    {
        if (!fixationActive || fixationWriter == null)
            return;

        long durationMs = fixationLastTsMs - fixationStartTsMs;
        if (durationMs < 0)
            durationMs = 0;
        if (durationMs >= fixationMinDurationMs && fixationSampleCount > 0)
        {
            fixationIdCounter++;
            float centroidX = fixationSumX / fixationSampleCount;
            float centroidY = fixationSumY / fixationSampleCount;
            float centroidZ = fixationSumZ / fixationSampleCount;

            float focusValidityScore = fixationSampleCount > 0
                ? (float)fixationValidFocusCount / fixationSampleCount
                : 0f;
            float gapPenalty = 1f;
            if (fixationMaxObservedGapMs > fixationMaxGapMs)
            {
                float overflow = fixationMaxObservedGapMs - fixationMaxGapMs;
                gapPenalty = Mathf.Clamp01(1f - (overflow / Mathf.Max(1f, fixationMaxGapMs)));
            }
            float qualityScore = Mathf.Clamp01(focusValidityScore * gapPenalty);

            fixationWriter.WriteLine(string.Join(",", new[]
            {
                string.IsNullOrEmpty(fixationSessionId) ? "None" : fixationSessionId,
                fixationIdCounter.ToString(CultureInfo.InvariantCulture),
                fixationStartTsMs.ToString(CultureInfo.InvariantCulture),
                fixationLastTsMs.ToString(CultureInfo.InvariantCulture),
                durationMs.ToString(CultureInfo.InvariantCulture),
                centroidX.ToString(CultureInfo.InvariantCulture),
                centroidY.ToString(CultureInfo.InvariantCulture),
                centroidZ.ToString(CultureInfo.InvariantCulture),
                string.IsNullOrEmpty(fixationObjectNameNorm) ? "None" : fixationObjectNameNorm,
                string.IsNullOrEmpty(fixationAoiNameNorm) ? "None" : fixationAoiNameNorm,
                fixationSampleCount.ToString(CultureInfo.InvariantCulture),
                qualityScore.ToString("F4", CultureInfo.InvariantCulture),
                string.IsNullOrEmpty(fixationAlgorithmVersion) ? "focus_segment_v1" : fixationAlgorithmVersion,
                string.IsNullOrEmpty(fixationFocusSource) ? "none" : fixationFocusSource,
                "1"
            }));
        }

        fixationActive = false;
        fixationStartTsMs = 0;
        fixationLastTsMs = 0;
        fixationSampleCount = 0;
        fixationValidFocusCount = 0;
        fixationSumX = 0f;
        fixationSumY = 0f;
        fixationSumZ = 0f;
        fixationMaxObservedGapMs = 0f;
        fixationObjectNameNorm = "";
        fixationAoiNameNorm = "";
        fixationFocusSource = "none";
        fixationSessionId = "";
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






