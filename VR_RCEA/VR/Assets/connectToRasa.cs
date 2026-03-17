using System.Collections;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;

public class PostMessageJson
{
    public string message;
    public string sender;
}

public class connectToRasa : MonoBehaviour
{
    private const string rasa_url = "http://localhost:5005/webhooks/rest/webhook";

    public GameObject Panel;
    public GameObject button;
    public Text ResultedText;
    public Text text;

    protected DictationRecognizer dictationRecognizer;

    [System.Serializable]
    public class UnityEventString : UnityEngine.Events.UnityEvent<string> { };
    public UnityEventString OnPhraseRecognized;
    public UnityEngine.Events.UnityEvent OnUserStartedSpeaking;
    
	private bool isUserSpeaking;
	private bool isDictationRunning;

	void Update()
	{
		// Replace "Fire1" with the appropriate input axis/button for the lower button of your controller.
		if (Input.GetButtonDown("TriggerButton"))
		{
			StartDictationEngine();
		}

		if (Input.GetButtonUp("TriggerButton"))
		{
			StopDictationEngineAndSendText();
		}
	}

	private void DictationRecognizer_OnDictationHypothesis(string text)
	{
		Debug.LogFormat("Dictation hypothesis: {0}", text);

		if (!isUserSpeaking)
		{
			isUserSpeaking = true;
			OnUserStartedSpeaking.Invoke();
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
		Debug.LogFormat("Dictation result: {0}", text);
		ResultedText.text = text;
		SendRecordedTextToRasa();
		
		if (isUserSpeaking)
		{
			isUserSpeaking = false;
			OnPhraseRecognized.Invoke(text);
		}
	}

	private void DictationRecognizer_OnDictationError(string error, int hresult)
	{
		Debug.LogErrorFormat("Dictation error: {0}; HResult = {1}.", error, hresult);
		isDictationRunning = false;
	}

	public void CloseDictationEngine()
	{
		if (dictationRecognizer != null)
		{
			dictationRecognizer.DictationHypothesis -= DictationRecognizer_OnDictationHypothesis;
			dictationRecognizer.DictationComplete -= DictationRecognizer_OnDictationComplete;
			dictationRecognizer.DictationResult -= DictationRecognizer_OnDictationResult;
			dictationRecognizer.DictationError -= DictationRecognizer_OnDictationError;

			if (dictationRecognizer.Status == SpeechSystemStatus.Running)
				dictationRecognizer.Stop();

			dictationRecognizer.Dispose();
			dictationRecognizer = null;
			isDictationRunning = false;
		}
	}

	public void StartDictationEngine()
	{
		if (isDictationRunning)
		{
			Debug.LogWarning("Dictation engine is already running.");
			return;
		}

		isUserSpeaking = false;

		dictationRecognizer = new DictationRecognizer();

		dictationRecognizer.DictationHypothesis += DictationRecognizer_OnDictationHypothesis;
		dictationRecognizer.DictationResult += DictationRecognizer_OnDictationResult;
		dictationRecognizer.DictationComplete += DictationRecognizer_OnDictationComplete;
		dictationRecognizer.DictationError += DictationRecognizer_OnDictationError;

		ResultedText.text = "Listening...";  // Indicate that the recognizer has started listening

		dictationRecognizer.Start();
		isDictationRunning = true;
		Debug.Log("Dictation engine started.");
	}

	private void StopDictationEngineAndSendText()
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

	private void SendRecordedTextToRasa()
	{
		if (!string.IsNullOrEmpty(ResultedText.text) && ResultedText.text != "Listening...")
		{
			var paintingName = "user";

			// Check the button name and assign the corresponding painting name
			switch (button.name)
			{
				case "A1-CA": paintingName = "Map of Paranambucae"; break;
				case "A2-CA": paintingName = "Head of a Boy"; break;
				case "A3-CA": paintingName = "The Market in Dam Square"; break;
				case "B1-CA": paintingName = "Diego Bemba, a Servant of Don Miguel de Castro"; break;
				case "B2-CA": paintingName = "Don Miguel de Castro, Emissary of Congo"; break;
				case "B3-CA": paintingName = "Pedro Sunda, a Servant of Don Miguel de Castro"; break;
				case "C1-CA": paintingName = "Man in a Turban"; break;
				case "C2-CA": paintingName = "Portrait of a Black Girl"; break;
				case "C3-CA": paintingName = "Portrait of a Man"; break;
				case "C4-CA": paintingName = "Two moors"; break;
				case "C5-CA": paintingName = "Head of a Boy in a Turban"; break;
				case "C6-CA": paintingName = "King Caspar"; break;
				case "D1-CA": paintingName = "The New Utopia Begins Here: Hermina Huiswoud"; break;
				case "D2-CA": paintingName = "The Unspoken Truth"; break;
				case "D3-CA": paintingName = "Ilona"; break;
			}

			PostMessageJson postMessage = new PostMessageJson
			{
				sender = paintingName,
				message = ResultedText.text
			};

			string jsonBody = JsonUtility.ToJson(postMessage);
			Debug.Log("User json: " + jsonBody);

			// Create a post request with the data to send to Rasa server
			//StartCoroutine(PostRequest(rasa_url, jsonBody));
		}
		else
		{
			Debug.LogWarning("No text to send to Rasa.");
		}
	}

	private IEnumerator PostRequest(string url, string jsonBody)
	{
		UnityWebRequest request = new UnityWebRequest(url, "POST");
		byte[] rawBody = new System.Text.UTF8Encoding().GetBytes(jsonBody);
		request.uploadHandler = (UploadHandler)new UploadHandlerRaw(rawBody);
		request.downloadHandler = (DownloadHandler)new DownloadHandlerBuffer();
		request.SetRequestHeader("Content-Type", "application/json");

		yield return request.SendWebRequest();

		if (request.result != UnityWebRequest.Result.Success)
		{
			Debug.LogError("Error: " + request.error);
		}
		else
		{
			Debug.Log("Response: " + request.downloadHandler.text);
			text.text = request.downloadHandler.text;
		}
	}
}
    