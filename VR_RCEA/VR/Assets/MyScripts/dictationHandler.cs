using UnityEngine;
using UnityEngine.Windows.Speech;

public class DictationHandler
{
    private DictationRecognizer dictationRecognizer;
    private bool isUserSpeaking = false;
    private bool isDictationRunning = false;
    private string recognizedText = "";  // Field to store recognized text
    
    // UnityEvent or custom events for handling user speaking and recognized phrases
    public UnityEngine.Events.UnityEvent OnUserStartedSpeaking;
    public UnityEngine.Events.UnityEvent<string> OnPhraseRecognized;

    public void StartDictationEngine()
    {
        InitializeDictationRecognizer();
        SubscribeToDictationEvents();
        StartDictation();
    }

    public void StopDictationEngineAndSendText()
    {
        if (isDictationRunning)
        {
            CloseDictationEngine();
        }
        else
        {
            Debug.LogWarning("Dictation engine is not running.");
        }
    }

    public void CloseDictationEngine()
    {
        if (dictationRecognizer == null) return;

        UnsubscribeFromDictationEvents();

        if (dictationRecognizer.Status == SpeechSystemStatus.Running)
        {
            dictationRecognizer.Stop();
        }

        dictationRecognizer.Dispose();
        dictationRecognizer = null;
        isDictationRunning = false;
    }

    private void DictationRecognizer_OnDictationHypothesis(string text)
    {
        Debug.LogFormat("Dictation hypothesis: {0}", text);
        HandleUserSpeaking();
    }

    private void HandleUserSpeaking()
    {
        if (!isUserSpeaking)
        {
            isUserSpeaking = true;
            OnUserStartedSpeaking?.Invoke();
        }
    }

    private void DictationRecognizer_OnDictationComplete(DictationCompletionCause completionCause)
    {
        Debug.LogFormat("Dictation complete: {0}", completionCause);
        isDictationRunning = false;

        if (completionCause != DictationCompletionCause.Complete)
        {
            Debug.LogWarningFormat("Dictation completed unsuccessfully: {0}.", completionCause);
        }
    }

    private void DictationRecognizer_OnDictationResult(string text, ConfidenceLevel confidence)
    {
        //Debug.LogFormat("Dictation result: {0}", text);
		Debug.LogError(text);
        recognizedText = text;  // Store the recognized text
        HandlePhraseRecognition(text);
    }

    private void HandlePhraseRecognition(string text)
    {
        if (isUserSpeaking)
        {
            isUserSpeaking = false;
            OnPhraseRecognized?.Invoke(text);
        }
    }

    private void DictationRecognizer_OnDictationError(string error, int hresult)
    {
        Debug.LogErrorFormat("Dictation error: {0}; HResult = {1}.", error, hresult);
        isDictationRunning = false;
    }

    private void InitializeDictationRecognizer()
    {
        isUserSpeaking = false;
        recognizedText = "";  // Reset the recognized text before starting a new dictation
        dictationRecognizer = new DictationRecognizer();
    }

    private void SubscribeToDictationEvents()
    {
        dictationRecognizer.DictationHypothesis += DictationRecognizer_OnDictationHypothesis;
        dictationRecognizer.DictationResult += DictationRecognizer_OnDictationResult;
        dictationRecognizer.DictationComplete += DictationRecognizer_OnDictationComplete;
        dictationRecognizer.DictationError += DictationRecognizer_OnDictationError;
    }

    private void UnsubscribeFromDictationEvents()
    {
        dictationRecognizer.DictationHypothesis -= DictationRecognizer_OnDictationHypothesis;
        dictationRecognizer.DictationComplete -= DictationRecognizer_OnDictationComplete;
        dictationRecognizer.DictationResult -= DictationRecognizer_OnDictationResult;
        dictationRecognizer.DictationError -= DictationRecognizer_OnDictationError;
    }

    private void StartDictation()
    {
        Debug.Log("Listening...");
        dictationRecognizer.Start();
        isDictationRunning = true;
        Debug.Log("Dictation engine started.");
    }

    // Method to retrieve the recognized text after dictation completes
    public string GetRecognizedText()
    {
        return recognizedText;
    }
}
