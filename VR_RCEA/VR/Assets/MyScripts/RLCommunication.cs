using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;
using Stopwatch = System.Diagnostics.Stopwatch;

public class RLCommunication : MonoBehaviour, ISpeechCaptureHost
{
    private const string DEFAULT_RUNTIME_URL = "http://127.0.0.1:8000";
    private const string DEBUG_LOG_FILE = "C:/Users/s3533204/Downloads/Research/Research/debug_logs/unity_rl_debug.log";

    [SerializeField] private string runtimeBaseUrl = DEFAULT_RUNTIME_URL;
    [SerializeField] private Text outputText;

    private DictationRecognizer dictationRecognizer;
    private string recognizedText = "";
    private string lastHypothesis = "";
    private bool isListening = false;
    private bool isStopping = false;
    private Coroutine stopWatchdogCoroutine;
    // True while a recognizer is disposing on the background thread. Windows SAPI
    // allows only one DictationRecognizer, so creating a new one before the old
    // finishes disposing either blocks the main thread (31s freeze) or throws and
    // leaves a null recognizer (dead mic). Presses are gated on this.
    private volatile bool teardownInProgress = false;
    private float dictationBusySince = -1f;
    [SerializeField] private float dictationStopWatchdogSeconds = 3.5f;
    [SerializeField] private float dictationStaleResetSeconds = 6f;
    // Visitors often press the trigger, then turn or walk to the next painting
    // before speaking. At the old 10s this timed out and the turn was lost.
    [SerializeField] private float initialSilenceTimeoutSeconds = 20f;
    [SerializeField] private float autoSilenceTimeoutSeconds = 3.0f;
    // Speech capture strategy. DEFAULT OFF (legacy per-turn: fresh recognizer each
    // turn). Reusing ONE recognizer across many Start/Stop cycles (v2) corrupts the
    // Windows SAPI session over ~10 turns -> DictationComplete stops firing and the
    // mic dies. Legacy per-turn never wedged in the field.
    // NOTE: this default only affects fresh component instances; a value already
    // serialized in the scene wins, so untick this in the Inspector to switch.
    [SerializeField] private bool useReusableRecognizer = false;
    private string pendingCurrentObjectName = "";
    private string pendingCurrentAoiName = "";
    private bool requestInFlight = false;
    private float lastTurnResponseAt = -1f;
    private string sessionId = "";
    private string participantId = "";
    private string actorNodeId = "";
    private string sessionStartedAtUtc = "";
    private string sessionStartedAtLocal = "";
    public bool HasReceivedSuccessfulTurn { get; private set; }
    public bool HasReceivedSuccessfulUserTurn { get; private set; }
    public int SuccessfulUserTurnCount { get; private set; }
    private bool pendingTurnIsSilence = false;
    private bool pendingTurnIsRealUser = false;

    // What the visitor said while the in-flight slot was occupied. Proactive turns are
    // still dropped when busy -- a greeting that lost the race is stale by the time the
    // slot frees -- but a real utterance is never discarded: dropping it is invisible to
    // the participant, who asked a question and gets an unrelated monologue instead.
    private readonly Queue<DeferredUserTurn> deferredUserTurns = new Queue<DeferredUserTurn>();

    private class DeferredUserTurn
    {
        public string userText;
        public string objectName;
        public string aoiName;
    }

    [Serializable]
    private class SessionStartPayload
    {
        public string session_id;
        public string participant_id;
        public string actor_node_id;
        public string started_at;
        public string started_at_local;
    }

    [Serializable]
    private class TurnMetadata
    {
        public bool is_silence_event;
        public string trigger_source;
        public string source;
        public float silence_elapsed_sec;
        // Seconds the visitor has spent looking at nothing the agent supports.
        // Feeds the runtime's `disengaged` telemetry gate - that label was a
        // behavioural fatigue latch in training, not a lexical decision, so the
        // transcript alone can never produce it.
        public float off_exhibit_seconds;
    }

    [Serializable]
    private class TurnPayload
    {
        public string session_id;
        public string user_text;
        public string current_object_name;
        public string current_aoi_name;
        public string timestamp;
        public TurnMetadata metadata;
    }

    [Serializable]
    private class SessionEndPayload
    {
        public string session_id;
        public string reason;
        public string ended_at;
    }

    [Serializable]
    private class SessionStartResponseJson
    {
        public string session_id;
        public string model_name;
        public string started_at;
    }

    [Serializable]
    private class TurnResponseJson
    {
        public string session_id;
        public string timestamp;
        public string reply_text;
        public string action;
        public string option;
        public string subaction;
        public string target_exhibit;
        public string mapped_exhibit;
        public string current_exhibit;
        public bool should_end;
        public string error;
    }

    // --- Speech backend (added 2026-07-28) ---------------------------------
    // Mirrors RasaCommunication: Whisper routes press-to-talk through the local
    // offline STT service. Set to WindowsDictation to roll back; the recognizer
    // implementation below is left intact.
    [SerializeField] private SpeechBackend speechBackend = SpeechBackend.Whisper;
    [SerializeField] private GetEyeData getEyeData;
    private WhisperSpeechCapture speechCapture;
    private int consecutiveCaptureFailures = 0;
    private int consecutiveEmptyTranscripts = 0;
    [SerializeField] private int degradedCaptureThreshold = 2;

    private void Awake()
    {
        LogDebug("Unity", "RLCommunication.Awake", $"script initialized on {gameObject.name}");
        EnsureSpeechCapture();
    }

    private void Start()
    {
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

    // ---- ISpeechCaptureHost (Whisper backend) -----------------------------

    public void OnSpeechCaptured(string text, string objectName, string aoiName, string userAsrEndTs)
    {
        consecutiveCaptureFailures = 0;
        consecutiveEmptyTranscripts = 0;
        LogDebug("Unity", "StopDictationEngine", $"sending_message='{text}', user_asr_end_ts={userAsrEndTs}, source=whisper");
        SendTurn(text, objectName, aoiName);
    }

    public void OnSpeechCaptureFailed(WhisperSpeechCapture.Failure failure, string detail)
    {
        bool emptySpeech = failure == WhisperSpeechCapture.Failure.EmptyTranscript
                        || failure == WhisperSpeechCapture.Failure.EmptyWindow;

        SpeechFeedback.PlayNotCapturedCue(this);

        if (emptySpeech)
        {
            consecutiveEmptyTranscripts++;
            LogDebug("Unity", "StopDictationEngine",
                $"error=invalid_captured_speech failure={failure} detail={detail} consecutive_empty={consecutiveEmptyTranscripts}");
            if (consecutiveEmptyTranscripts >= degradedCaptureThreshold && outputText)
                outputText.text = "I didn't catch that — please speak after pressing, and hold the trigger while talking.";
            return;
        }

        // Dead input stream is a hardware fault, not a quiet participant.
        if (failure == WhisperSpeechCapture.Failure.MicSilent)
        {
            consecutiveCaptureFailures++;
            LogDebug("Unity", "StopDictationEngine",
                $"error=mic_silent detail={detail} consecutive={consecutiveCaptureFailures}");
            if (consecutiveCaptureFailures >= degradedCaptureThreshold)
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

        if (consecutiveCaptureFailures >= degradedCaptureThreshold)
        {
            LogDebug("Unity", "StopDictationEngine",
                $"warning=recognizer_degraded cause=stt_service consecutive={consecutiveCaptureFailures} advise=check_stt_window");
            if (outputText)
                outputText.text = "Speech service problem — please tell the researcher (audio is being saved).";
        }
    }

    public void LogSpeechDebug(string @event, string data) => LogDebug("Unity", @event, data);

    public bool HasActiveSession()
    {
        return !string.IsNullOrEmpty(sessionId);
    }

    public void StartSession(string newParticipantId, string newActorNodeId, string externalSessionId, string startedAtUtc, string startedAtLocal)
    {
        if (HasActiveSession())
        {
            LogDebug("Unity", "StartSession", $"skip=already_active session_id={sessionId}");
            return;
        }

        participantId = newParticipantId ?? "participant";
        actorNodeId = newActorNodeId ?? "";
        sessionId = string.IsNullOrEmpty(externalSessionId) ? Guid.NewGuid().ToString("N") : externalSessionId;
        sessionStartedAtUtc = string.IsNullOrEmpty(startedAtUtc) ? DateTime.UtcNow.ToString("o") : startedAtUtc;
        sessionStartedAtLocal = string.IsNullOrEmpty(startedAtLocal) ? DateTime.Now.ToString("o") : startedAtLocal;
        HasReceivedSuccessfulTurn = false;
        HasReceivedSuccessfulUserTurn = false;
        SuccessfulUserTurnCount = 0;
        var payload = new SessionStartPayload
        {
            session_id = sessionId,
            participant_id = participantId,
            actor_node_id = actorNodeId,
            started_at = sessionStartedAtUtc,
            started_at_local = sessionStartedAtLocal
        };
        StartCoroutine(PostSessionStartCoroutine(payload));
    }

    public void EndSession(string reason)
    {
        if (!HasActiveSession())
            return;

        // Tear down the persistent recognizer at the session boundary (v2 keeps one
        // alive across turns; legacy already disposes per turn so this is a no-op).
        if (dictationRecognizer != null)
            CleanupRecognizer();

        speechCapture?.OnSessionEnding(reason);

        // Anything still deferred belongs to the session that is ending; flushing it into
        // the next participant's session would attribute their utterance to the wrong run.
        if (deferredUserTurns.Count > 0)
        {
            LogDebug("Unity", "EndSession",
                     $"warning=deferred_user_turns_dropped depth={deferredUserTurns.Count} reason={reason}");
            deferredUserTurns.Clear();
        }

        var payload = new SessionEndPayload
        {
            session_id = sessionId,
            reason = string.IsNullOrEmpty(reason) ? "manual_end" : reason,
            ended_at = DateTime.UtcNow.ToString("o")
        };
        StartCoroutine(PostSessionEndCoroutine(payload));
    }

    public void SendSilenceTurn(string currentObjectName, string currentAoiName, float silenceElapsedSeconds)
    {
        if (!HasActiveSession())
        {
            LogDebug("Unity", "SendSilenceTurn", "skip=no_active_session");
            return;
        }
        var metadata = new TurnMetadata
        {
            is_silence_event = true,
            trigger_source = "unity_silence_timer",
            source = "unity_silence_timer",
            silence_elapsed_sec = silenceElapsedSeconds
        };
        LogDebug(
            "Unity",
            "SendSilenceTurn",
            $"session_id={sessionId}, current_object={currentObjectName}, current_aoi={currentAoiName}, silence_elapsed_sec={silenceElapsedSeconds:F1}"
        );
        SendTurn("", currentObjectName, currentAoiName, metadata);
    }

    /// <summary>Fire a turn because the visitor moved their attention to a new exhibit
    /// without speaking, so the agent can open on the new painting instead of waiting
    /// out the 40 s silence timer. NOT a silence event: it must not consume the
    /// silence budget, and there is no visitor utterance to interpret.</summary>
    public bool SendFocusChangeTurn(string currentObjectName, string currentAoiName)
    {
        if (!HasActiveSession())
        {
            LogDebug("Unity", "SendFocusChangeTurn", "skip=no_active_session");
            return false;
        }
        if (requestInFlight)
        {
            LogDebug("Unity", "SendFocusChangeTurn", "skip=request_in_flight");
            return false;
        }
        var metadata = new TurnMetadata
        {
            is_silence_event = false,
            trigger_source = "focus_change",
            source = "unity_focus_change"
        };
        LogDebug(
            "Unity",
            "SendFocusChangeTurn",
            $"session_id={sessionId}, current_object={currentObjectName}, current_aoi={currentAoiName}"
        );
        SendTurn("", currentObjectName, currentAoiName, metadata);
        return true;
    }

    public bool IsRequestInFlight => requestInFlight;

    /// <summary>True from the talk button going down until the resulting utterance has
    /// been transcribed, so proactive turns never cut across someone who is mid-sentence
    /// -- or, worse, across the STT round-trip that follows. Releasing the trigger is not
    /// the end of the visitor's turn; the transcript is still ~150-400 ms away, and a
    /// proactive turn sent inside that window takes the in-flight slot and the visitor's
    /// question is dropped by SendTurn.</summary>
    public bool IsCapturingSpeech => speechCapture != null && speechCapture.IsBusy;

    /// <summary>Seconds since the last successful turn response. The agent's reply is
    /// spoken server-side after the response returns, so Unity cannot see TTS finish;
    /// callers use this as a proxy for "the agent may still be talking".</summary>
    public float SecondsSinceLastTurn =>
        lastTurnResponseAt < 0f ? float.MaxValue : Time.realtimeSinceStartup - lastTurnResponseAt;

    public void CheckMicrophone()
    {
        if (speechBackend == SpeechBackend.Whisper)
        {
            EnsureSpeechCapture();
            speechCapture?.BeginCapture(this);
            return;
        }

        string[] devices = Microphone.devices ?? Array.Empty<string>();
        LogDebug("Unity", "CheckMicrophone", $"device_count={devices.Length} devices=[{string.Join(" | ", devices)}]");

        if (Microphone.devices.Length > 0)
        {
            StartDictationEngine();
        }
        else
        {
            Debug.LogError("No microphone found.");
            if (outputText) outputText.text = "No microphone found.";
        }
    }

    private void StartDictationEngine()
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

        if (isListening || isStopping)
        {
            float busyFor = dictationBusySince >= 0f ? (Time.realtimeSinceStartup - dictationBusySince) : 0f;
            if (dictationBusySince >= 0f && busyFor >= dictationStaleResetSeconds)
            {
                // Wedged. Hard reset and BAIL -- do not create in the same frame. The
                // teardown gate lets the next press create a fresh recognizer cleanly.
                LogDebug("Unity", "StartDictationEngine", $"force_reset_stale busy_for={busyFor:F1}s isListening={isListening} isStopping={isStopping}");
                CleanupRecognizer();
                SpeechFeedback.PlayNotCapturedCue(this);
                return;
            }

            LogDebug("Unity", "StartDictationEngine", "warning=dictation_already_running");
            // This press is being ignored, so anything said now is lost too.
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        // Legacy mode: a non-running recognizer can linger. Tear it down and bail so
        // the next press creates cleanly (avoids create-while-disposing).
        if (!useReusableRecognizer && dictationRecognizer != null)
        {
            LogDebug("Unity", "StartDictationEngine", "drop_stale_recognizer");
            CleanupRecognizer();
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        recognizedText = "";
        lastHypothesis = "";
        pendingCurrentObjectName = "";
        pendingCurrentAoiName = "";

        // Both modes create through the exception-safe EnsureRecognizer; they differ
        // only in whether FinalizeCapturedSpeech keeps (reuse) or disposes (legacy).
        EnsureRecognizer();
        if (dictationRecognizer == null)
        {
            LogDebug("Unity", "StartDictationEngine", "error=recognizer_create_failed");
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        try
        {
            if (dictationRecognizer.Status != SpeechSystemStatus.Running)
                dictationRecognizer.Start();
        }
        catch (Exception e)
        {
            Debug.LogError("StartDictationEngine start failed: " + e.Message);
            LogDebug("Unity", "StartDictationEngine", $"error=start_failed message={e.Message}");
            CleanupRecognizer();
            SpeechFeedback.PlayNotCapturedCue(this);
            return;
        }

        LogDebug(
            "Unity",
            "StartDictationEngine",
            $"config reusable={useReusableRecognizer} initial_silence={dictationRecognizer.InitialSilenceTimeoutSeconds:F1} auto_silence={dictationRecognizer.AutoSilenceTimeoutSeconds:F1} devices=[{string.Join(" | ", Microphone.devices ?? Array.Empty<string>())}]"
        );

        isListening = true;
        isStopping = false;
        dictationBusySince = Time.realtimeSinceStartup;
        LogDebug("Unity", "StartDictationEngine", "dictation_started");
    }

    public void StopDictationEngine(string currentObjectName, string currentAoiName)
    {
        if (speechBackend == SpeechBackend.Whisper)
        {
            speechCapture?.EndCapture(currentObjectName, currentAoiName);
            return;
        }

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
                StartStopWatchdog();
                return;
            }
        }
        catch (Exception e)
        {
            Debug.LogError("StopDictationEngine exception: " + e.Message);
            LogDebug("Unity", "StopDictationEngine", $"error=stop_exception message={e.Message}");
        }

        if (useReusableRecognizer)
        {
            // Do NOT finalize inline on a not-yet-Running recognizer: that instant
            // drop-flood is what drove participant 05's freeze. Let the watchdog
            // finalize if DictationComplete never fires.
            StartStopWatchdog();
            return;
        }

        FinalizeCapturedSpeech("recognizer_not_running");
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
        isListening = false;
        isStopping = false;
        recognizedText = "";
        lastHypothesis = "";
        pendingCurrentObjectName = "";
        pendingCurrentAoiName = "";
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

        // If DictationComplete never fired, the Windows recognizer is wedged in the
        // stopping state and every future trigger press is rejected. Force a recovery
        // so the next utterance can be captured.
        if (isStopping || dictationRecognizer != null)
        {
            string status = dictationRecognizer == null ? "null" : dictationRecognizer.Status.ToString();
            LogDebug("Unity", "StopWatchdog", $"force_recovery isStopping={isStopping} recognizer_status={status}");
            FinalizeCapturedSpeech("watchdog_timeout");
        }
    }

    private void OnDestroy()
    {
        if (dictationRecognizer != null)
            CleanupRecognizer();
    }

    private void OnHypothesis(string text)
    {
        lastHypothesis = text ?? "";
        LogDebug("Unity", "DictationHypothesis", $"len={lastHypothesis.Length} text={lastHypothesis}");
    }

    private void OnResult(string text, ConfidenceLevel confidence)
    {
        var clean = (text ?? "").Trim();
        if (!string.IsNullOrEmpty(clean))
        {
            recognizedText += clean + " ";
            LogDebug("Unity", "DictationResult", $"confidence={confidence} len={clean.Length} text={clean}");
        }
    }

    private void OnComplete(DictationCompletionCause cause)
    {
        LogDebug("Unity", "DictationComplete", $"cause={cause}");
        FinalizeCapturedSpeech($"completion={cause}");
    }

    private void OnError(string error, int hresult)
    {
        LogDebug("Unity", "DictationError", $"error={error} hresult={hresult}");
    }

    private void FinalizeCapturedSpeech(string reason)
    {
        // OnComplete and the watchdog can both reach here; whichever runs second
        // finds isStopping already cleared and returns. (Guarding on isStopping
        // rather than a null recognizer is what makes the reusable path idempotent,
        // since ReleaseRecognizer keeps the instance alive.)
        if (!isStopping)
            return;

        // A watchdog finalize means DictationComplete never fired -> the recognizer
        // is wedged and must be torn down, not reused.
        bool wedged = reason == "watchdog_timeout";
        bool keepRecognizer = useReusableRecognizer && !wedged;

        string toSend = (recognizedText ?? "").Trim();
        if (string.IsNullOrWhiteSpace(toSend))
            toSend = (lastHypothesis ?? "").Trim();

        if (string.IsNullOrWhiteSpace(toSend))
        {
            string recognizerStatus = dictationRecognizer == null ? "null" : dictationRecognizer.Status.ToString();
            LogDebug(
                "Unity",
                "StopDictationEngine",
                $"error=invalid_captured_speech reason={reason} recognizer_status={recognizerStatus} recognized_len={recognizedText.Length} hypothesis_len={lastHypothesis.Length}"
            );
            // Tell the visitor the utterance was lost -- otherwise this failure is
            // completely silent and they have no idea they need to repeat themselves.
            SpeechFeedback.PlayNotCapturedCue(this);
            if (keepRecognizer) ReleaseRecognizer(); else CleanupRecognizer();
            return;
        }

        LogDebug(
            "Unity",
            "StopDictationEngine",
            $"dispatch user_text={toSend}, current_object={pendingCurrentObjectName}, current_aoi={pendingCurrentAoiName}, reason={reason}"
        );
        SendTurn(toSend, pendingCurrentObjectName, pendingCurrentAoiName);
        if (keepRecognizer) ReleaseRecognizer(); else CleanupRecognizer();
    }

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

    private void ReleaseRecognizer()
    {
        // Normal turn boundary: KEEP the recognizer instance alive for the next
        // turn. DictationComplete already stopped it, so there is no Stop()/Dispose()
        // here -- that per-turn churn is exactly what caused the 31s freeze.
        CancelStopWatchdog();
        isListening = false;
        isStopping = false;
        dictationBusySince = -1f;
        recognizedText = "";
        lastHypothesis = "";
        pendingCurrentObjectName = "";
        pendingCurrentAoiName = "";
    }

    private void SendTurn(string userText, string currentObjectName, string currentAoiName, TurnMetadata metadata = null)
    {
        if (!HasActiveSession())
        {
            string localError = "RL session has not started. StartDataCollection must run before sending turns.";
            Debug.LogWarning(localError);
            if (outputText) outputText.text = localError;
            LogDebug("Unity", "SendTurn", "skip=no_active_session");
            return;
        }

        if (requestInFlight)
        {
            // metadata==null is the plain-user path (OnSpeechCaptured); the trigger_source
            // test covers any caller that fills the block in itself.
            bool isUserUtterance = (metadata == null || metadata.trigger_source == "user_input")
                                   && !string.IsNullOrWhiteSpace(userText);
            if (isUserUtterance)
            {
                deferredUserTurns.Enqueue(new DeferredUserTurn
                {
                    userText = userText,
                    objectName = currentObjectName,
                    aoiName = currentAoiName
                });
                LogDebug("Unity", "SendTurn",
                         $"defer=request_in_flight depth={deferredUserTurns.Count}, user_text={userText}");
                return;
            }
            Debug.LogWarning("RL request skipped: one already in flight.");
            LogDebug("Unity", "SendTurn", "skip=request_in_flight");
            return;
        }

        // Metadata is always sent, even for plain user turns: the runtime's
        // response-type classifier reads off_exhibit_seconds from it, and a null
        // metadata block would leave that gate permanently dark.
        if (metadata == null)
        {
            metadata = new TurnMetadata
            {
                is_silence_event = false,
                trigger_source = "user_input",
                source = "unity"
            };
        }
        metadata.off_exhibit_seconds = getEyeData != null ? getEyeData.GetOffExhibitSeconds() : 0f;

        var payload = new TurnPayload
        {
            session_id = sessionId,
            user_text = userText,
            current_object_name = currentObjectName,
            current_aoi_name = currentAoiName,
            timestamp = DateTime.UtcNow.ToString("o"),
            metadata = metadata
        };
        pendingTurnIsSilence = metadata != null && metadata.is_silence_event;
        pendingTurnIsRealUser = !pendingTurnIsSilence && !string.IsNullOrWhiteSpace(userText);
        string metadataSummary = metadata == null
            ? "metadata=null"
            : $"metadata.is_silence_event={metadata.is_silence_event}, metadata.trigger_source={metadata.trigger_source}";
        LogDebug("Unity", "SendTurn", $"session_id={sessionId}, user_text={userText}, current_object={currentObjectName}, current_aoi={currentAoiName}, {metadataSummary}");
        StartCoroutine(PostTurnCoroutine(payload));
    }

    private IEnumerator PostSessionStartCoroutine(SessionStartPayload payload)
    {
        string url = runtimeBaseUrl + "/session/start";
        string jsonBody = JsonUtility.ToJson(payload);
        using (var request = BuildJsonRequest(url, jsonBody))
        {
            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                var response = JsonUtility.FromJson<SessionStartResponseJson>(request.downloadHandler.text);
                sessionId = response.session_id;
                LogDebug("Unity", "SessionStart", $"session_id={sessionId}, started_at_utc={sessionStartedAtUtc}, started_at_local={sessionStartedAtLocal}");
            }
            else
            {
                sessionId = "";
                HandleLocalError("Failed to start RL session", request);
            }
        }
    }

    private IEnumerator PostTurnCoroutine(TurnPayload payload)
    {
        string url = runtimeBaseUrl + "/turn";
        string jsonBody = JsonUtility.ToJson(payload);
        var stopwatch = Stopwatch.StartNew();
        requestInFlight = true;

        using (var request = BuildJsonRequest(url, jsonBody))
        {
            // A turn costs 4.6-8.3 s server-side (LLM generation + judge, plus an
            // optional revise/re-judge round), and the response-type classifier adds
            // one more call BEFORE the policy runs. 15 s left too little headroom:
            // on abort Unity drops the reply but server-side TTS still speaks it,
            // so the participant hears an answer this client has discarded.
            request.timeout = 30;
            yield return request.SendWebRequest();
            stopwatch.Stop();

            if (request.result == UnityWebRequest.Result.Success)
            {
                var response = JsonUtility.FromJson<TurnResponseJson>(request.downloadHandler.text);
                HasReceivedSuccessfulTurn = true;
                lastTurnResponseAt = Time.realtimeSinceStartup;
                if (pendingTurnIsRealUser)
                {
                    HasReceivedSuccessfulUserTurn = true;
                    SuccessfulUserTurnCount += 1;
                }
                if (outputText) outputText.text = response.reply_text;
                LogDebug(
                    "Unity",
                    "TurnResponse",
                    $"session_id={sessionId}, ms={stopwatch.Elapsed.TotalMilliseconds:F2}, action={response.action}, option={response.option}, subaction={response.subaction}, mapped_exhibit={response.mapped_exhibit}, pending_silence={pendingTurnIsSilence}, successful_user_turn_count={SuccessfulUserTurnCount}"
                );
            }
            else
            {
                HandleLocalError("RL turn request failed", request);
            }
        }

        pendingTurnIsSilence = false;
        pendingTurnIsRealUser = false;
        requestInFlight = false;

        // Hand the freed slot straight to anything the visitor said while we were busy,
        // oldest first, so their question is answered late rather than not at all.
        if (deferredUserTurns.Count > 0)
        {
            var deferred = deferredUserTurns.Dequeue();
            LogDebug("Unity", "SendTurn",
                     $"flush=deferred_user_turn remaining={deferredUserTurns.Count}, user_text={deferred.userText}");
            SendTurn(deferred.userText, deferred.objectName, deferred.aoiName);
        }
    }

    private IEnumerator PostSessionEndCoroutine(SessionEndPayload payload)
    {
        string url = runtimeBaseUrl + "/session/end";
        string jsonBody = JsonUtility.ToJson(payload);
        using (var request = BuildJsonRequest(url, jsonBody))
        {
            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                LogDebug("Unity", "SessionEnd", $"session_id={sessionId}");
                sessionId = "";
                sessionStartedAtUtc = "";
                sessionStartedAtLocal = "";
                HasReceivedSuccessfulTurn = false;
                HasReceivedSuccessfulUserTurn = false;
                SuccessfulUserTurnCount = 0;
                pendingTurnIsSilence = false;
                pendingTurnIsRealUser = false;
            }
            else
            {
                HandleLocalError("Failed to end RL session", request);
            }
        }
    }

    private UnityWebRequest BuildJsonRequest(string url, string jsonBody)
    {
        var request = new UnityWebRequest(url, "POST");
        request.uploadHandler = new UploadHandlerRaw(new System.Text.UTF8Encoding().GetBytes(jsonBody));
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        return request;
    }

    private void HandleLocalError(string prefix, UnityWebRequest request)
    {
        string body = request.downloadHandler?.text ?? "";
        string message = prefix + ": " + request.error;
        Debug.LogError(message + " body=" + body);
        if (outputText) outputText.text = prefix + ". Check RL runtime.";
        LogDebug("Unity", "LocalError", $"prefix={prefix}, error={request.error}, body={body}");
    }

    private void LogDebug(string component, string eventName, string data = "")
    {
        try
        {
            System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(DEBUG_LOG_FILE));
            string timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            string logEntry = $"[{timestamp}] [{component}] {eventName} | {data}";
            System.IO.File.AppendAllText(DEBUG_LOG_FILE, logEntry + "\n");
        }
        catch (Exception ex)
        {
            Debug.LogError($"LogDebug exception: {ex.Message}");
        }
    }
}


