using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;
using Stopwatch = System.Diagnostics.Stopwatch;

public enum SpeechBackend
{
    WindowsDictation = 0,
    Whisper = 1,
}

public class RasaCommunication : MonoBehaviour, ISpeechCaptureHost
{
    private const string RASA_URL = "http://localhost:5005/webhooks/rest/webhook";
    private const string DEBUG_LOG_FILE = "C:/Users/s3533204/Downloads/Research/Research/debug_logs/unity_debug.log";

    private DictationRecognizer dictationRecognizer;
    private string recognizedText = "";
    private string lastHypothesis = "";
    private bool isRecognizing = false;
    private bool requestInFlight = false;
    private bool hasFinalResult = false;

    // Sender tag the Whisper capture path uses for a real visitor utterance; the silence
    // timer sends "prompting_user" instead. Only the former is worth deferring.
    private const string USER_SENDER = "communicating_with_agent";

    // See RLCommunication: a visitor utterance that collides with an in-flight request
    // waits for the slot rather than being discarded, which is invisible to the participant.
    private readonly Queue<DeferredUserTurn> deferredUserTurns = new Queue<DeferredUserTurn>();

    private class DeferredUserTurn
    {
        public string message;
        public string objectName;
        public string aoiName;
        public string userAsrEndTs;
    }
    private float dictationBusySince = -1f;
    [SerializeField] private float dictationStaleResetSeconds = 6f;
    // Visitors often press the trigger, then turn or walk to the next painting
    // before speaking. At the old 10s this timed out and the turn was lost.
    [SerializeField] private float initialSilenceTimeoutSeconds = 20f;
    [SerializeField] private float autoSilenceTimeoutSeconds = 3.0f;

    // --- Recognizer degradation tracking (added 2026-07-27, participant 15) ---
    // Windows online dictation degrades over a session: after a run of turns it
    // starts returning empty finals / DictationComplete(cause=UnknownError), and
    // every capture is dropped as invalid_captured_speech. Previously that failure
    // was silent -- the participant kept talking and the agent never answered
    // ("voice kept dropping towards the end"). Count consecutive dropped captures
    // so we can (a) surface it loudly for the operator and (b) tell the participant
    // to repeat instead of failing silently.
    [SerializeField] private int degradedRecognizerThreshold = 2;
    private int consecutiveCaptureFailures = 0;
    private DictationCompletionCause lastCompletionCause = DictationCompletionCause.Complete;

    // --- Speech backend (added 2026-07-28) ---------------------------------
    // Whisper routes press-to-talk through the local offline STT service instead
    // of Windows dictation. Set to WindowsDictation in the Inspector to roll back
    // instantly -- the entire DictationRecognizer implementation below is left
    // intact and simply stops being called.
    [SerializeField] private SpeechBackend speechBackend = SpeechBackend.Whisper;
    private WhisperSpeechCapture speechCapture;
    // Counted separately from service faults: a participant who says nothing is
    // not a broken pipeline, and conflating the two is how a real outage gets
    // dismissed as "they just didn't speak".
    private int consecutiveEmptyTranscripts = 0;

    // Speech capture strategy. DEFAULT OFF (legacy per-turn: fresh recognizer each
    // turn). Reusing ONE recognizer across many Start/Stop cycles (v2) corrupts the
    // Windows SAPI session over ~10 turns -> DictationComplete stops firing and the
    // mic dies (participants 05 and 07). Legacy per-turn never wedged in the field.
    // NOTE: this default only affects fresh component instances; a value already
    // serialized in the scene wins, so untick this in the Inspector to switch.
    [SerializeField] private bool useReusableRecognizer = false;
    [SerializeField] private float dictationStopWatchdogSeconds = 3.5f;
    private bool isListening = false;
    private bool isStopping = false;
    private string pendingCurrentObjectName = "";
    private string pendingCurrentAoiName = "";
    private Coroutine stopWatchdogCoroutine;
    // True while a recognizer is being disposed on the background thread. Windows
    // SAPI allows only one DictationRecognizer, so creating a new one before the
    // old one finishes disposing either blocks the main thread (31s freeze,
    // participant 05) or throws and leaves us with a null recognizer (dead mic,
    // participant 07). Presses are gated on this to serialize teardown vs create.
    private volatile bool teardownInProgress = false;

    [SerializeField] private GetEyeData getEyeData;

    public Text outputText;

    private void Awake()
    {
        if (getEyeData == null)
            getEyeData = FindObjectOfType<GetEyeData>();
        LogDebug("Unity", "RasaCommunication.Awake", $"script initialized on {gameObject.name}");
        EnsureSpeechCapture();
    }

    private void Start()
    {
        // Retry: if GetEyeData had not been created yet during Awake, this is the
        // second (and reliable) chance to bind rather than silently staying null.
        EnsureSpeechCapture();
    }

    private void EnsureSpeechCapture()
    {
        if (speechBackend != SpeechBackend.Whisper || speechCapture != null)
            return;
        if (getEyeData == null)
            getEyeData = FindObjectOfType<GetEyeData>();
        if (getEyeData == null)
            return;
        speechCapture = WhisperSpeechCapture.Attach(getEyeData);
        LogDebug("Unity", "SpeechBackend", $"backend=whisper attached={(speechCapture != null)}");
    }

    private void OnEnable()
    {
        LogDebug("Unity", "RasaCommunication.OnEnable", $"script enabled on {gameObject.name}");
    }

    public void CheckMicrophone()
    {
        if (speechBackend == SpeechBackend.Whisper)
        {
            EnsureSpeechCapture();
            speechCapture?.BeginCapture(this);
            return;
        }

        if (Microphone.devices.Length > 0)
        {
            Debug.LogWarning("Microphone found: " + Microphone.devices[0]);
            StartDictationEngine();
        }
        else
        {
            Debug.LogError("No microphone found.");
            if (outputText) outputText.text = "No microphone found.";
        }
    }

    public void StartDictationEngine()
    {
        // Refuse to start while a previous recognizer is still tearing down -- creating
        // one now is the SAPI collision that froze/killed the mic. The visitor gets a
        // cue and can press again once teardown finishes (usually well under a second).
        if (teardownInProgress)
        {
            LogDebug("Unity", "StartDictationEngine", "warning=teardown_in_progress");
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        if (useReusableRecognizer)
        {
            StartDictationEngineReusable();
            return;
        }
        StartDictationEngineLegacy();
    }

    // ---- v2: persistent recognizer ----------------------------------------

    private void EnsureRecognizer()
    {
        if (dictationRecognizer != null)
            return;

        try
        {
            var recognizer = new DictationRecognizer
            {
                InitialSilenceTimeoutSeconds = initialSilenceTimeoutSeconds,
                AutoSilenceTimeoutSeconds = autoSilenceTimeoutSeconds
            };
            recognizer.DictationHypothesis += OnHypothesis;
            recognizer.DictationResult += OnResult;
            recognizer.DictationComplete += OnComplete;
            recognizer.DictationError += OnError;
            // Assign only after full construction so a throw never leaves a
            // half-initialized instance in the field.
            dictationRecognizer = recognizer;
        }
        catch (Exception e)
        {
            Debug.LogError("EnsureRecognizer create failed: " + e.Message);
            LogDebug("Unity", "EnsureRecognizer", $"error=create_failed message={e.Message}");
            dictationRecognizer = null;
        }
    }

    private void StartDictationEngineReusable()
    {
        LogDebug("Unity", "StartDictationEngine", "start listening (reusable)");

        if (isStopping)
        {
            // A finalize from the previous release is still pending (~100-200ms).
            // Ignoring this press avoids racing the recognizer; the buffer for this
            // press would be lost, so tell the visitor.
            LogDebug("Unity", "StartDictationEngine", "warning=stop_in_progress");
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        if (isListening)
        {
            float busyFor = dictationBusySince >= 0f ? (Time.realtimeSinceStartup - dictationBusySince) : 0f;
            if (dictationBusySince >= 0f && busyFor >= dictationStaleResetSeconds)
            {
                // Recognizer wedged. Hard reset and BAIL -- do not create a new one
                // in the same frame (that create-while-disposing collision is the bug).
                // The teardown gate lets the NEXT press create a fresh recognizer once
                // disposal completes.
                LogDebug("Unity", "StartDictationEngine", $"force_reset_stale busy_for={busyFor:F1}s");
                HardResetRecognizer();
                SpeechFeedback.PlayNotCapturedCue(this);
                return;
            }

            Debug.LogWarning("Dictation already running.");
            LogDebug("Unity", "StartDictationEngine", "warning=dictation_already_running");
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        EnsureRecognizer();
        if (dictationRecognizer == null)
        {
            LogDebug("Unity", "StartDictationEngine", "error=recognizer_create_failed");
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        recognizedText = "";
        lastHypothesis = "";
        hasFinalResult = false;
        pendingCurrentObjectName = "";
        pendingCurrentAoiName = "";

        try
        {
            if (dictationRecognizer.Status != SpeechSystemStatus.Running)
                dictationRecognizer.Start();
        }
        catch (Exception e)
        {
            Debug.LogError("StartDictationEngine start failed: " + e.Message);
            LogDebug("Unity", "StartDictationEngine", $"error=start_failed message={e.Message}");
            HardResetRecognizer();
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        isRecognizing = true;
        isListening = true;
        isStopping = false;
        dictationBusySince = Time.realtimeSinceStartup;
        LogDebug("Unity", "StartDictationEngine", "dictation_started (reusable)");
    }

    public void StopDictationEngineReusable(string currentObjectName, string currentAoiName)
    {
        LogDebug("Unity", "StopDictationEngine", "stop listening and prepare send (reusable)");

        if (dictationRecognizer == null || !isListening)
        {
            LogDebug("Unity", "StopDictationEngine", "error=recognizer_null");
            return;
        }

        if (isStopping)
        {
            LogDebug("Unity", "StopDictationEngine", "warning=stop_already_in_progress");
            return;
        }

        pendingCurrentObjectName = currentObjectName ?? "";
        pendingCurrentAoiName = currentAoiName ?? "";
        isStopping = true;

        try
        {
            if (dictationRecognizer.Status == SpeechSystemStatus.Running)
            {
                LogDebug(
                    "Unity",
                    "StopDictationEngine",
                    $"stop_requested recognized_len={recognizedText.Length} hypothesis_len={lastHypothesis.Length}"
                );
                dictationRecognizer.Stop();
            }
        }
        catch (Exception e)
        {
            Debug.LogError("StopDictationEngine exception: " + e.Message);
            LogDebug("Unity", "StopDictationEngine", $"error=stop_exception message={e.Message}");
        }

        // Always wait for DictationComplete (or the watchdog); never finalize inline.
        // Finalizing inline when the recognizer was not-yet-Running was the instant
        // drop-flood that drove participant 05's freeze.
        StartStopWatchdog();
    }

    private void FinalizeCapturedSpeech(string reason)
    {
        // OnComplete and the watchdog can both reach here; whichever runs second
        // finds isStopping already cleared and returns.
        if (!isStopping)
            return;

        CancelStopWatchdog();

        string toSend = (recognizedText ?? "").Trim();
        if (string.IsNullOrWhiteSpace(toSend))
        {
            toSend = (lastHypothesis ?? "").Trim();
            if (!string.IsNullOrEmpty(toSend))
                Debug.Log($"Using hypothesis fallback: '{toSend}'");
        }

        // A watchdog finalize means DictationComplete never fired -> the recognizer
        // is wedged and must be torn down, not reused.
        bool wedged = reason == "watchdog_timeout";

        if (string.IsNullOrWhiteSpace(toSend) || toSend.Length < 3)
        {
            consecutiveCaptureFailures++;
            Debug.LogWarning("No usable speech captured; not sending to Rasa.");
            LogDebug(
                "Unity",
                "StopDictationEngine",
                $"error=invalid_captured_speech reason={reason} cause={lastCompletionCause} consecutive={consecutiveCaptureFailures} recognized_len={recognizedText.Length} hypothesis_len={lastHypothesis.Length}"
            );
            // Tell the visitor the utterance was lost -- otherwise this failure is
            // completely silent and they have no idea they need to repeat themselves.
            SpeechFeedback.PlayNotCapturedCue(this);
            if (consecutiveCaptureFailures >= degradedRecognizerThreshold)
            {
                LogDebug(
                    "Unity",
                    "StopDictationEngine",
                    $"warning=recognizer_degraded consecutive={consecutiveCaptureFailures} advise=restart_play_mode"
                );
                if (outputText)
                    outputText.text = "Speech recognition is dropping — please repeat, and let the researcher know.";
            }
            if (wedged) HardResetRecognizer(); else ReleaseRecognizer();
            return;
        }

        consecutiveCaptureFailures = 0;
        string userAsrEndTs = DateTime.UtcNow.ToString("o");
        LogDebug("Unity", "StopDictationEngine", $"sending_message='{toSend}', user_asr_end_ts={userAsrEndTs}, reason={reason}");
        Debug.Log($"Sending to Rasa: '{toSend}' (len={toSend.Length})");
        SendDataToRasa(USER_SENDER, toSend, pendingCurrentObjectName, pendingCurrentAoiName, userAsrEndTs);
        if (wedged) HardResetRecognizer(); else ReleaseRecognizer();
    }

    private void ReleaseRecognizer()
    {
        // Normal turn boundary: KEEP the recognizer instance alive for the next
        // turn. DictationComplete already stopped it, so there is no Stop()/Dispose()
        // here -- that per-turn churn is exactly what caused the 31s freeze.
        CancelStopWatchdog();
        isRecognizing = false;
        isListening = false;
        isStopping = false;
        dictationBusySince = -1f;
        recognizedText = "";
        lastHypothesis = "";
        hasFinalResult = false;
    }

    // Full off-thread teardown (dispose + recreate on next press). Rare path only:
    // wedge-recovery, stale-running, session end, OnDestroy.
    private void HardResetRecognizer()
    {
        CleanupRecognizer();
    }

    private void StartStopWatchdog()
    {
        CancelStopWatchdog();
        stopWatchdogCoroutine = StartCoroutine(StopWatchdogCoroutine());
    }

    private void CancelStopWatchdog()
    {
        if (stopWatchdogCoroutine != null)
        {
            StopCoroutine(stopWatchdogCoroutine);
            stopWatchdogCoroutine = null;
        }
    }

    private IEnumerator StopWatchdogCoroutine()
    {
        yield return new WaitForSeconds(Mathf.Max(0.5f, dictationStopWatchdogSeconds));
        stopWatchdogCoroutine = null;

        // DictationComplete never fired -> recognizer wedged. Force the turn through
        // so it is not lost outright.
        if (isStopping)
        {
            string status = dictationRecognizer == null ? "null" : dictationRecognizer.Status.ToString();
            LogDebug("Unity", "StopWatchdog", $"force_recovery recognizer_status={status}");
            FinalizeCapturedSpeech("watchdog_timeout");
        }
    }

    // ---- legacy: per-turn create/dispose (toggle off) ---------------------

    private void StartDictationEngineLegacy()
    {
        LogDebug("Unity", "StartDictationEngine", "start listening");

        // If a previous recognizer is still around, tear it down and BAIL rather than
        // creating a new one in the same frame -- creating while the old instance is
        // disposing off-thread is the SAPI collision that froze/killed the mic. The
        // teardown gate lets the next press create a fresh recognizer cleanly.
        if (dictationRecognizer != null)
        {
            float busyFor = dictationBusySince >= 0f ? (Time.realtimeSinceStartup - dictationBusySince) : 0f;
            bool running = dictationRecognizer.Status == SpeechSystemStatus.Running;
            if (running && !(dictationBusySince >= 0f && busyFor >= dictationStaleResetSeconds))
            {
                Debug.LogWarning("Dictation already running.");
                LogDebug("Unity", "StartDictationEngine", "warning=dictation_already_running");
                SpeechFeedback.PlayNotCapturedCue(this);
                return;
            }

            LogDebug("Unity", "StartDictationEngine", running ? $"force_reset_stale busy_for={busyFor:F1}s" : "drop_stale_recognizer");
            CleanupRecognizer();
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        recognizedText = "";
        lastHypothesis = "";
        hasFinalResult = false;
        lastCompletionCause = DictationCompletionCause.Complete;

        dictationRecognizer = new DictationRecognizer
        {
            InitialSilenceTimeoutSeconds = initialSilenceTimeoutSeconds,
            AutoSilenceTimeoutSeconds = autoSilenceTimeoutSeconds
        };

        dictationRecognizer.DictationHypothesis += OnHypothesis;
        dictationRecognizer.DictationResult += OnResult;
        dictationRecognizer.DictationComplete += OnComplete;
        dictationRecognizer.DictationError += OnError;

        Debug.Log("Start Recording");
        dictationRecognizer.Start();
        isRecognizing = true;
        dictationBusySince = Time.realtimeSinceStartup;
        LogDebug("Unity", "StartDictationEngine", "dictation_started");
    }

    public void StopDictationEngine(string currentObjectName = null, string currentAoiName = null)
    {
        if (speechBackend == SpeechBackend.Whisper)
        {
            speechCapture?.EndCapture(currentObjectName, currentAoiName);
            return;
        }

        if (useReusableRecognizer)
        {
            StopDictationEngineReusable(currentObjectName, currentAoiName);
            return;
        }
        StopDictationEngineLegacy(currentObjectName, currentAoiName);
    }

    private async void StopDictationEngineLegacy(string currentObjectName = null, string currentAoiName = null)
    {
        LogDebug("Unity", "StopDictationEngine", "stop listening and prepare send");

        if (dictationRecognizer == null)
        {
            Debug.LogWarning("StopDictationEngine called, but recognizer is null.");
            LogDebug("Unity", "StopDictationEngine", "error=recognizer_null");
            return;
        }

        await Task.Delay(1600);

        string toSend = (recognizedText ?? "").Trim();
        if (string.IsNullOrWhiteSpace(toSend))
        {
            toSend = (lastHypothesis ?? "").Trim();
            if (!string.IsNullOrEmpty(toSend))
                Debug.Log($"Using hypothesis fallback: '{toSend}'");
        }

        if (string.IsNullOrWhiteSpace(toSend) || toSend.Length < 3)
        {
            consecutiveCaptureFailures++;
            Debug.LogWarning("No usable speech captured; not sending to Rasa.");
            LogDebug(
                "Unity",
                "StopDictationEngine",
                $"error=invalid_captured_speech cause={lastCompletionCause} consecutive={consecutiveCaptureFailures}"
            );
            // Tell the visitor the utterance was lost -- otherwise this failure is
            // completely silent and they have no idea they need to repeat themselves.
            SpeechFeedback.PlayNotCapturedCue(this);
            // Auto-recovery: a RUN of empty captures means the Windows online-speech
            // session has degraded (UnknownError / empty finals), not a one-off miss.
            // A fresh per-turn recognizer (CleanupRecognizer below) alone does not
            // clear that, so escalate: flag the participant to repeat and leave a loud
            // marker in the operator log advising a Play-mode restart before it eats
            // the rest of the session (participant 15).
            if (consecutiveCaptureFailures >= degradedRecognizerThreshold)
            {
                LogDebug(
                    "Unity",
                    "StopDictationEngine",
                    $"warning=recognizer_degraded consecutive={consecutiveCaptureFailures} advise=restart_play_mode"
                );
                if (outputText)
                    outputText.text = "Speech recognition is dropping — please repeat, and let the researcher know.";
            }
            CleanupRecognizer();
            return;
        }

        consecutiveCaptureFailures = 0;
        string userAsrEndTs = DateTime.UtcNow.ToString("o");
        LogDebug("Unity", "StopDictationEngine", $"sending_message='{toSend}', user_asr_end_ts={userAsrEndTs}");
        Debug.Log($"Sending to Rasa: '{toSend}' (len={toSend.Length})");
        SendDataToRasa(USER_SENDER, toSend, currentObjectName, currentAoiName, userAsrEndTs);
        CleanupRecognizer();
    }

    private void CleanupRecognizer()
    {
        // Detach the instance and reset our state IMMEDIATELY on the main
        // thread, then tear the recognizer down on a background thread.
        // Stop()/Dispose() go through the Windows speech API which was
        // observed to block the main thread for 67-200 seconds (full app
        // freeze, SteamVR "waiting" overlay) on 2026-07-16.
        var recognizer = dictationRecognizer;
        dictationRecognizer = null;

        if (recognizer != null)
        {
            try
            {
                // Cheap delegate ops — safe on the main thread. Detaching
                // first guarantees no callback mutates our state mid-teardown.
                recognizer.DictationHypothesis -= OnHypothesis;
                recognizer.DictationResult -= OnResult;
                recognizer.DictationComplete -= OnComplete;
                recognizer.DictationError -= OnError;
            }
            catch (Exception e)
            {
                Debug.LogError("CleanupRecognizer unsubscribe exception: " + e.Message);
            }

            teardownInProgress = true;
            var teardown = new Thread(() =>
            {
                var sw = Stopwatch.StartNew();
                try
                {
                    try
                    {
                        if (recognizer.Status == SpeechSystemStatus.Running)
                            recognizer.Stop();
                    }
                    catch (Exception) { }
                    try { recognizer.Dispose(); } catch (Exception) { }
                    sw.Stop();
                    if (sw.Elapsed.TotalSeconds > 2)
                        LogDebug("Unity", "RecognizerTeardown", $"slow_teardown_offthread ms={sw.Elapsed.TotalMilliseconds:F0}");
                }
                finally
                {
                    // Always clear the gate so the next press can create a fresh
                    // recognizer, even if Stop()/Dispose() threw.
                    teardownInProgress = false;
                }
            })
            {
                IsBackground = true,
                Name = "DictationTeardown"
            };
            teardown.Start();
        }

        CancelStopWatchdog();
        dictationBusySince = -1f;
        isRecognizing = false;
        isListening = false;
        isStopping = false;
        recognizedText = "";
        lastHypothesis = "";
        hasFinalResult = false;
        Debug.Log("Stopped Recording");
    }

    private void OnDestroy()
    {
        if (dictationRecognizer != null)
            CleanupRecognizer();
    }

    private void OnHypothesis(string text)
    {
        lastHypothesis = text ?? "";
        Debug.Log("Hypothesis: " + lastHypothesis);
    }

    private void OnResult(string text, ConfidenceLevel confidence)
    {
        hasFinalResult = true;
        var clean = (text ?? "").Trim();
        if (!string.IsNullOrEmpty(clean))
        {
            recognizedText += clean + " ";
            Debug.Log("Result: " + clean);
        }
        else
        {
            Debug.Log("Result was empty.");
        }
    }

    private void OnComplete(DictationCompletionCause cause)
    {
        lastCompletionCause = cause;
        Debug.Log($"Dictation Complete (cause={cause}) Final='{recognizedText}' Hypo='{lastHypothesis}'");
        LogDebug("Unity", "DictationComplete", $"cause={cause}");
        if (useReusableRecognizer)
            FinalizeCapturedSpeech($"completion={cause}");
    }

    private void OnError(string error, int hresult)
    {
        Debug.LogError("Dictation Error: " + error + " (0x" + hresult.ToString("X") + ")");
        // Previously console-only, so recognizer errors never reached the operator
        // debug log alongside the invalid_captured_speech markers. Log them too.
        LogDebug("Unity", "DictationError", $"error={error} hresult=0x{hresult:X}");
    }

    // ---- ISpeechCaptureHost (Whisper backend) -----------------------------

    public void OnSpeechCaptured(string text, string objectName, string aoiName, string userAsrEndTs)
    {
        consecutiveCaptureFailures = 0;
        consecutiveEmptyTranscripts = 0;
        LogDebug("Unity", "StopDictationEngine", $"sending_message='{text}', user_asr_end_ts={userAsrEndTs}, source=whisper");
        Debug.Log($"Sending to Rasa: '{text}' (len={text.Length})");
        SendDataToRasa(USER_SENDER, text, objectName, aoiName, userAsrEndTs);
    }

    public void OnSpeechCaptureFailed(WhisperSpeechCapture.Failure failure, string detail)
    {
        // press_too_short never reaches here -- it is dropped upstream so a
        // trigger misfire does not spend a cue the participant would learn to
        // ignore.
        // MicSilent is deliberately NOT counted as "empty speech": the input stream
        // was dead, which is a hardware fault the operator must act on, not a quiet
        // participant. Conflating the two is what let the 2026-07-28 mic dropout
        // masquerade as people not talking.
        bool emptySpeech = failure == WhisperSpeechCapture.Failure.EmptyTranscript
                        || failure == WhisperSpeechCapture.Failure.EmptyWindow;

        SpeechFeedback.PlayNotCapturedCue(this);

        if (emptySpeech)
        {
            consecutiveEmptyTranscripts++;
            LogDebug("Unity", "StopDictationEngine",
                $"error=invalid_captured_speech failure={failure} detail={detail} consecutive_empty={consecutiveEmptyTranscripts}");
            if (consecutiveEmptyTranscripts >= degradedRecognizerThreshold && outputText)
                outputText.text = "I didn't catch that — please speak after pressing, and hold the trigger while talking.";
            return;
        }

        if (failure == WhisperSpeechCapture.Failure.MicSilent)
        {
            consecutiveCaptureFailures++;
            LogDebug("Unity", "StopDictationEngine",
                $"error=mic_silent detail={detail} consecutive={consecutiveCaptureFailures}");
            if (consecutiveCaptureFailures >= degradedRecognizerThreshold)
            {
                LogDebug("Unity", "StopDictationEngine",
                    $"warning=recognizer_degraded cause=mic_hardware consecutive={consecutiveCaptureFailures} advise=check_headset_mic");
                if (outputText)
                    outputText.text = "Microphone not picking up — please tell the researcher (check the headset mic).";
            }
            return;
        }

        consecutiveCaptureFailures++;
        Debug.LogWarning($"Speech capture failed: {failure} ({detail})");
        LogDebug("Unity", "StopDictationEngine",
            $"error=invalid_captured_speech failure={failure} detail={detail} consecutive={consecutiveCaptureFailures}");

        if (consecutiveCaptureFailures >= degradedRecognizerThreshold)
        {
            // Reuses the existing recognizer_degraded key so any log greps/tooling
            // built for the dictation failures keep firing for the STT backend.
            LogDebug("Unity", "StopDictationEngine",
                $"warning=recognizer_degraded cause=stt_service consecutive={consecutiveCaptureFailures} advise=check_stt_window");
            if (outputText)
                outputText.text = "Speech service problem — please tell the researcher (audio is being saved).";
        }
    }

    public void LogSpeechDebug(string @event, string data) => LogDebug("Unity", @event, data);

    public void SendDataToRasa(string sender, string message, string currentObjectName = null, string currentAoiName = null, string userAsrEndTs = null)
    {
        if (requestInFlight)
        {
            // Mirrors RLCommunication.SendTurn: a real utterance waits for the slot, a
            // proactive prompt is dropped (it is stale by the time the slot frees). The
            // two arms must handle this collision identically or it becomes a confound.
            if (sender == USER_SENDER && !string.IsNullOrWhiteSpace(message))
            {
                deferredUserTurns.Enqueue(new DeferredUserTurn
                {
                    message = message,
                    objectName = currentObjectName,
                    aoiName = currentAoiName,
                    userAsrEndTs = userAsrEndTs
                });
                LogDebug("Unity", "SendDataToRasa",
                         $"defer=request_in_flight depth={deferredUserTurns.Count}, message={message}");
                return;
            }
            Debug.LogWarning("Rasa request skipped: one already in flight.");
            LogDebug("Unity", "SendDataToRasa", "skip=request_in_flight");
            return;
        }

        var post = new PostMessageJson
        {
            sender = sender,
            message = message,
            metadata = new MessageMetadata
            {
                currentObjectName = currentObjectName ?? "",
                currentAoiName = currentAoiName ?? "",
                sessionId = ResolveSessionId(),
                participantId = ResolveParticipantId(),
                sessionFolderName = ResolveSessionFolderName(),
                userAsrEndTs = userAsrEndTs ?? "",
            }
        };
        string jsonBody = JsonUtility.ToJson(post);

        LogDebug(
            "Unity",
            "SendDataToRasa",
            $"sender={sender}, len={(message ?? "").Length}, session={ResolveSessionId()}, participant={ResolveParticipantId()}, folder={ResolveSessionFolderName()}, user_asr_end_ts={userAsrEndTs ?? ""}, object={currentObjectName ?? "None"}, aoi={currentAoiName ?? "None"}"
        );
        Debug.Log("User json: " + jsonBody);

        requestInFlight = true;
        LogDebug("Unity", "HTTP请求准备启动协程", $"sender={sender}, started_at={DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}");
        StartCoroutine(PostRequestCoroutine(RASA_URL, jsonBody));
    }

    [Serializable]
    public class MessageMetadata
    {
        public string currentObjectName;
        public string currentAoiName;
        public string sessionId;
        public string participantId;
        public string sessionFolderName;
        public string userAsrEndTs;
    }

    [Serializable]
    public class PostMessageJson
    {
        public string message;
        public string sender;
        public MessageMetadata metadata;
    }

    private string ResolveSessionId()
    {
        return getEyeData != null ? (getEyeData.CurrentSessionId ?? "") : "";
    }

    private string ResolveParticipantId()
    {
        return getEyeData != null ? (getEyeData.CurrentParticipantId ?? "") : "";
    }

    private string ResolveSessionFolderName()
    {
        return getEyeData != null ? (getEyeData.CurrentSessionFolderName ?? "") : "";
    }

    private IEnumerator PostRequestCoroutine(string url, string jsonBody)
    {
        var stopwatch = Stopwatch.StartNew();
        string startedAt = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");

        Debug.Log($"Rasa POST -> {url} body={jsonBody}");
        LogDebug("Unity", "HTTP协程开始", $"started_at={startedAt}, url={url}");

        using (var request = new UnityWebRequest(url, "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(new System.Text.UTF8Encoding().GetBytes(jsonBody));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = 45;

            LogDebug("Unity", "HTTP请求已发送", $"started_at={startedAt}, timeout_s={request.timeout}, body_len={jsonBody.Length}");

            var op = request.SendWebRequest();
            op.completed += _ =>
            {
                string callbackAt = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
                LogDebug(
                    "Unity",
                    "HTTP底层完成事件",
                    $"callback_at={callbackAt}, elapsed_ms={stopwatch.Elapsed.TotalMilliseconds:F2}, result={request.result}, code={request.responseCode}, error={request.error}"
                );
            };

            yield return op;

            string endedAt = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            string body = request.downloadHandler?.text ?? "";
            string bodyPreview = body.Length > 300 ? body.Substring(0, 300) + "..." : body;
            string errorText = string.IsNullOrEmpty(request.error) ? "None" : request.error;

            LogDebug("Unity", "HTTP协程yield返回", $"ended_at={endedAt}, elapsed_ms={stopwatch.Elapsed.TotalMilliseconds:F2}, isDone={op.isDone}");

            if (request.result == UnityWebRequest.Result.Success && request.responseCode >= 200 && request.responseCode < 300)
            {
                Debug.Log($"Rasa HTTP result={request.result} code={request.responseCode} body={body}");
                LogDebug("Unity", "HTTP响应体", $"started_at={startedAt}, ended_at={endedAt}, code={request.responseCode}, body_len={body.Length}, body={bodyPreview}");
            }
            else
            {
                Debug.LogError($"Rasa HTTP failed result={request.result} code={request.responseCode} error={errorText} body={body}");
                LogDebug("Unity", "HTTP错误响应", $"started_at={startedAt}, ended_at={endedAt}, result={request.result}, code={request.responseCode}, error={errorText}, body_len={body.Length}, body={bodyPreview}");
            }

            stopwatch.Stop();
            PerformanceProfiler.LogExecutionTime("RasaCommunication", "PostRequestCoroutine", (float)stopwatch.Elapsed.TotalMilliseconds);
            LogDebug("Unity", "HTTP请求完成", $"状态={request.result}, 代码={request.responseCode}, error={errorText}, ms={stopwatch.Elapsed.TotalMilliseconds:F2}");
            LogDebug("Unity", "HTTP协程结束", $"ended_at={endedAt}, elapsed_ms={stopwatch.Elapsed.TotalMilliseconds:F2}");
            requestInFlight = false;
        }

        // Hand the freed slot to whatever the visitor said while we were busy, oldest first.
        if (deferredUserTurns.Count > 0)
        {
            var deferred = deferredUserTurns.Dequeue();
            LogDebug("Unity", "SendDataToRasa",
                     $"flush=deferred_user_turn remaining={deferredUserTurns.Count}, message={deferred.message}");
            SendDataToRasa(USER_SENDER, deferred.message, deferred.objectName, deferred.aoiName,
                           deferred.userAsrEndTs);
        }
    }

    private void LogDebug(string component, string @event, string data = "")
    {
        try
        {
            System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(DEBUG_LOG_FILE));
            string timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            string logEntry = $"[{timestamp}] [{component}] {@event} | {data}";
            System.IO.File.AppendAllText(DEBUG_LOG_FILE, logEntry + "\n");
            Debug.Log($"[DEBUG_LOG] {logEntry}");
        }
        catch (Exception ex)
        {
            Debug.LogError($"LogDebug exception: {ex.Message}");
        }
    }
}
