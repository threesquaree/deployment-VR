using System;
using System.Collections;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;
using Stopwatch = System.Diagnostics.Stopwatch;

public class RasaCommunication : MonoBehaviour
{
    private const string RASA_URL = "http://localhost:5005/webhooks/rest/webhook";
    private const string DEBUG_LOG_FILE = "C:/Users/Vrmuseum/Desktop/Research/debug_logs/unity_debug.log";

    private DictationRecognizer dictationRecognizer;
    private string recognizedText = "";
    private string lastHypothesis = "";
    private bool isRecognizing = false;
    private bool requestInFlight = false;
    private bool hasFinalResult = false;

    public Text outputText;

    private void Awake()
    {
        LogDebug("Unity", "RasaCommunication.Awake", $"script initialized on {gameObject.name}");
    }

    private void OnEnable()
    {
        LogDebug("Unity", "RasaCommunication.OnEnable", $"script enabled on {gameObject.name}");
    }

    public void CheckMicrophone()
    {
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
        LogDebug("Unity", "StartDictationEngine", "start listening");

        if (dictationRecognizer != null && dictationRecognizer.Status == SpeechSystemStatus.Running)
        {
            Debug.LogWarning("Dictation already running.");
            LogDebug("Unity", "StartDictationEngine", "warning=dictation_already_running");
            return;
        }

        recognizedText = "";
        lastHypothesis = "";
        hasFinalResult = false;

        dictationRecognizer = new DictationRecognizer
        {
            InitialSilenceTimeoutSeconds = 10f,
            AutoSilenceTimeoutSeconds = 3.0f
        };

        dictationRecognizer.DictationHypothesis += OnHypothesis;
        dictationRecognizer.DictationResult += OnResult;
        dictationRecognizer.DictationComplete += OnComplete;
        dictationRecognizer.DictationError += OnError;

        Debug.Log("Start Recording");
        dictationRecognizer.Start();
        isRecognizing = true;
        LogDebug("Unity", "StartDictationEngine", "dictation_started");
    }

    public async void StopDictationEngine()
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
            Debug.LogWarning("No usable speech captured; not sending to Rasa.");
            LogDebug("Unity", "StopDictationEngine", "error=invalid_captured_speech");
            CleanupRecognizer();
            return;
        }

        LogDebug("Unity", "StopDictationEngine", $"sending_message='{toSend}'");
        Debug.Log($"Sending to Rasa: '{toSend}' (len={toSend.Length})");
        SendDataToRasa("communicating_with_agent", toSend);
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
            isRecognizing = false;
            recognizedText = "";
            lastHypothesis = "";
            hasFinalResult = false;
            Debug.Log("Stopped Recording");
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
        Debug.Log($"Dictation Complete (cause={cause}) Final='{recognizedText}' Hypo='{lastHypothesis}'");
    }

    private void OnError(string error, int hresult)
    {
        Debug.LogError("Dictation Error: " + error + " (0x" + hresult.ToString("X") + ")");
    }

    public void SendDataToRasa(string sender, string message)
    {
        if (requestInFlight)
        {
            Debug.LogWarning("Rasa request skipped: one already in flight.");
            LogDebug("Unity", "SendDataToRasa", "skip=request_in_flight");
            return;
        }

        var post = new PostMessageJson { sender = sender, message = message };
        string jsonBody = JsonUtility.ToJson(post);

        LogDebug("Unity", "SendDataToRasa", $"sender={sender}, len={(message ?? "").Length}");
        Debug.Log("User json: " + jsonBody);

        requestInFlight = true;
        LogDebug("Unity", "HTTP请求准备启动协程", $"sender={sender}, started_at={DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}");
        StartCoroutine(PostRequestCoroutine(RASA_URL, jsonBody));
    }

    [Serializable]
    public class PostMessageJson
    {
        public string message;
        public string sender;
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
            request.timeout = 10;

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
