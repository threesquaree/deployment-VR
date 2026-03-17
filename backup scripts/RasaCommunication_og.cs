using System;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;

public class RasaCommunication : MonoBehaviour
{
    private const string RASA_URL = "http://localhost:5005/webhooks/rest/webhook";

    private DictationRecognizer dictationRecognizer;
    private string recognizedText = "";
    private bool isRecognizing = false;
    private bool requestInFlight = false;
    private bool hasFinalResult = false;

    public Text outputText; // optional UI

    // ---- Public entry points ----
    public void CheckMicrophone()
    {
        if (Microphone.devices.Length > 0)
        {
            Debug.Log("Microphone found: " + Microphone.devices[0]);
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
        if (dictationRecognizer != null && dictationRecognizer.Status == SpeechSystemStatus.Running)
        {
            Debug.LogWarning("Dictation already running.");
            return;
        }

        recognizedText = "";
        hasFinalResult = false;

        dictationRecognizer = new DictationRecognizer();
        dictationRecognizer.DictationHypothesis += OnHypothesis;
        dictationRecognizer.DictationResult += OnResult;
        dictationRecognizer.DictationComplete += OnComplete;
        dictationRecognizer.DictationError += OnError;

        Debug.Log("Start Recording");
        dictationRecognizer.Start();
        isRecognizing = true;
    }

    public async void StopDictationEngine()
    {
        if (dictationRecognizer == null)
        {
            Debug.LogWarning("StopDictationEngine called, but recognizer is null.");
            return;
        }

        // Short grace period to allow final result to arrive
        await Task.Delay(1000);

        string toSend = (recognizedText ?? "").Trim();
        if (string.IsNullOrWhiteSpace(toSend) || toSend.Length < 3)
        {
            Debug.LogWarning("No usable speech captured; not sending to Rasa.");
            CleanupRecognizer();
            return;
        }

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
            hasFinalResult = false;
            Debug.Log("Stopped Recording");
        }
    }

    private void OnDestroy()
    {
        if (dictationRecognizer != null) CleanupRecognizer();
    }

    // ---- Dictation callbacks ----
    private void OnHypothesis(string text)
    {
        Debug.Log("Hypothesis: " + text);
    }

    private void OnResult(string text, ConfidenceLevel confidence)
    {
        Debug.Log("Result: " + text);
        hasFinalResult = true;
        recognizedText += (text?.Trim() + " ");
    }

    private void OnComplete(DictationCompletionCause cause)
    {
        Debug.Log("Dictation Complete: " + recognizedText);
    }

    private void OnError(string error, int hresult)
    {
        Debug.LogError("Dictation Error: " + error);
    }

    // ---- Rasa REST ----
    public async void SendDataToRasa(string sender, string message)
    {
        var post = new PostMessageJson { sender = sender, message = message };
        string jsonBody = JsonUtility.ToJson(post);
        Debug.Log("User json: " + jsonBody);
        await PostRequestAsync(RASA_URL, jsonBody);
    }

    [Serializable]
    public class PostMessageJson
    {
        public string message;
        public string sender;
    }

    private async Task PostRequestAsync(string url, string jsonBody)
    {
        if (requestInFlight)
        {
            Debug.LogWarning("Rasa request skipped: one already in flight.");
            return;
        }

        requestInFlight = true;
        Debug.Log($"Rasa POST -> {url} body={jsonBody}");

        using (var request = new UnityWebRequest(url, "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(new System.Text.UTF8Encoding().GetBytes(jsonBody));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = 10;

            try
            {
                var op = request.SendWebRequest();
                while (!op.isDone) await Task.Yield();

                var body = request.downloadHandler?.text ?? "";
                Debug.Log($"Rasa HTTP result={request.result} code={request.responseCode} body={body}");
            }
            catch (Exception ex)
            {
                Debug.LogError("Rasa POST exception: " + ex.Message);
            }
            finally
            {
                requestInFlight = false;
            }
        }
    }
}
