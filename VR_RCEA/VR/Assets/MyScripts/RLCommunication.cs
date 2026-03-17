using System;
using System.Collections;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;
using Stopwatch = System.Diagnostics.Stopwatch;

public class RLCommunication : MonoBehaviour
{
    private const string DEFAULT_RUNTIME_URL = "http://127.0.0.1:8000";
    private const string DEBUG_LOG_FILE = "C:/Users/Vrmuseum/Desktop/Research/debug_logs/unity_rl_debug.log";

    [SerializeField] private string runtimeBaseUrl = DEFAULT_RUNTIME_URL;
    [SerializeField] private Text outputText;

    private DictationRecognizer dictationRecognizer;
    private string recognizedText = "";
    private string lastHypothesis = "";
    private bool requestInFlight = false;
    private string sessionId = "";
    private string participantId = "";
    private string actorNodeId = "";

    [Serializable]
    private class SessionStartPayload
    {
        public string participant_id;
        public string actor_node_id;
        public string started_at;
    }

    [Serializable]
    private class TurnPayload
    {
        public string session_id;
        public string user_text;
        public string current_object_name;
        public string current_aoi_name;
        public string timestamp;
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

    private void Awake()
    {
        LogDebug("Unity", "RLCommunication.Awake", $"script initialized on {gameObject.name}");
    }

    public bool HasActiveSession()
    {
        return !string.IsNullOrEmpty(sessionId);
    }

    public void StartSession(string newParticipantId, string newActorNodeId)
    {
        if (HasActiveSession())
        {
            LogDebug("Unity", "StartSession", $"skip=already_active session_id={sessionId}");
            return;
        }

        participantId = newParticipantId ?? "participant";
        actorNodeId = newActorNodeId ?? "";
        var payload = new SessionStartPayload
        {
            participant_id = participantId,
            actor_node_id = actorNodeId,
            started_at = DateTime.UtcNow.ToString("o")
        };
        StartCoroutine(PostSessionStartCoroutine(payload));
    }

    public void EndSession(string reason)
    {
        if (!HasActiveSession())
            return;

        var payload = new SessionEndPayload
        {
            session_id = sessionId,
            reason = string.IsNullOrEmpty(reason) ? "manual_end" : reason,
            ended_at = DateTime.UtcNow.ToString("o")
        };
        StartCoroutine(PostSessionEndCoroutine(payload));
    }

    public void SendPromptingUser(string currentObjectName, string currentAoiName)
    {
        if (!HasActiveSession())
        {
            LogDebug("Unity", "SendPromptingUser", "skip=no_active_session");
            return;
        }
        SendTurn("prompting_user", currentObjectName, currentAoiName);
    }

    public void CheckMicrophone()
    {
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
        if (dictationRecognizer != null && dictationRecognizer.Status == SpeechSystemStatus.Running)
        {
            LogDebug("Unity", "StartDictationEngine", "warning=dictation_already_running");
            return;
        }

        recognizedText = "";
        lastHypothesis = "";

        dictationRecognizer = new DictationRecognizer
        {
            InitialSilenceTimeoutSeconds = 10f,
            AutoSilenceTimeoutSeconds = 3.0f
        };

        dictationRecognizer.DictationHypothesis += OnHypothesis;
        dictationRecognizer.DictationResult += OnResult;
        dictationRecognizer.DictationComplete += OnComplete;
        dictationRecognizer.DictationError += OnError;
        dictationRecognizer.Start();
        LogDebug("Unity", "StartDictationEngine", "dictation_started");
    }

    public async void StopDictationEngine(string currentObjectName, string currentAoiName)
    {
        if (dictationRecognizer == null)
        {
            LogDebug("Unity", "StopDictationEngine", "error=recognizer_null");
            return;
        }

        await Task.Delay(1600);

        string toSend = (recognizedText ?? "").Trim();
        if (string.IsNullOrWhiteSpace(toSend))
            toSend = (lastHypothesis ?? "").Trim();

        if (string.IsNullOrWhiteSpace(toSend) || toSend.Length < 3)
        {
            LogDebug("Unity", "StopDictationEngine", "error=invalid_captured_speech");
            CleanupRecognizer();
            return;
        }

        LogDebug("Unity", "StopDictationEngine", $"dispatch user_text={toSend}, current_object={currentObjectName}, current_aoi={currentAoiName}");
        SendTurn(toSend, currentObjectName, currentAoiName);
        CleanupRecognizer();
    }

    private void CleanupRecognizer()
    {
        try
        {
            if (dictationRecognizer != null)
            {
                if (dictationRecognizer.Status == SpeechSystemStatus.Running)
                    dictationRecognizer.Stop();

                dictationRecognizer.DictationHypothesis -= OnHypothesis;
                dictationRecognizer.DictationResult -= OnResult;
                dictationRecognizer.DictationComplete -= OnComplete;
                dictationRecognizer.DictationError -= OnError;
                dictationRecognizer.Dispose();
                dictationRecognizer = null;
            }
        }
        catch (Exception e)
        {
            Debug.LogError("CleanupRecognizer exception: " + e.Message);
        }
        finally
        {
            recognizedText = "";
            lastHypothesis = "";
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
    }

    private void OnResult(string text, ConfidenceLevel confidence)
    {
        var clean = (text ?? "").Trim();
        if (!string.IsNullOrEmpty(clean))
            recognizedText += clean + " ";
    }

    private void OnComplete(DictationCompletionCause cause)
    {
        LogDebug("Unity", "DictationComplete", $"cause={cause}");
    }

    private void OnError(string error, int hresult)
    {
        LogDebug("Unity", "DictationError", $"error={error} hresult={hresult}");
    }

    private void SendTurn(string userText, string currentObjectName, string currentAoiName)
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
            Debug.LogWarning("RL request skipped: one already in flight.");
            LogDebug("Unity", "SendTurn", "skip=request_in_flight");
            return;
        }

        var payload = new TurnPayload
        {
            session_id = sessionId,
            user_text = userText,
            current_object_name = currentObjectName,
            current_aoi_name = currentAoiName,
            timestamp = DateTime.UtcNow.ToString("o")
        };
        LogDebug("Unity", "SendTurn", $"session_id={sessionId}, user_text={userText}, current_object={currentObjectName}, current_aoi={currentAoiName}");
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
                LogDebug("Unity", "SessionStart", $"session_id={sessionId}");
            }
            else
            {
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
            request.timeout = 15;
            yield return request.SendWebRequest();
            stopwatch.Stop();

            if (request.result == UnityWebRequest.Result.Success)
            {
                var response = JsonUtility.FromJson<TurnResponseJson>(request.downloadHandler.text);
                if (outputText) outputText.text = response.reply_text;
                LogDebug(
                    "Unity",
                    "TurnResponse",
                    $"session_id={sessionId}, ms={stopwatch.Elapsed.TotalMilliseconds:F2}, action={response.action}, option={response.option}, subaction={response.subaction}, mapped_exhibit={response.mapped_exhibit}"
                );
            }
            else
            {
                HandleLocalError("RL turn request failed", request);
            }
        }

        requestInFlight = false;
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


