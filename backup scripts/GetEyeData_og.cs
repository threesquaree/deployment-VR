using System.Collections;
using System.Collections.Generic;
using Tobii.XR;
using UnityEngine;
using System.Text;
using System.IO;
using System;
using UnityEngine.UI;
using Tobii.G2OM;
using Valve.VR.InteractionSystem;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.Windows.Speech;
using Newtonsoft.Json;
using System.Net;
using System.Linq;
using Valve.VR;
using System.Diagnostics;
using System.Globalization;


public class GetEyeData : MonoBehaviour
{
    // Public Fields
    public String filename;
    public Text statusText;
    
    public Dictionary<string, int> paintingsDic;
    public GameObject FallBackIndicator;
    public string paintingName;
    
    public string actorNodeID;
	public string measureNodeID;

    // Private Fields
    private bool started;

    private float timestamp;
    private float startTime;

    private AudioClip recording;

    [SerializeField] private Player player;
    [SerializeField] private HeatMap heatMapScript;
    [SerializeField] private String mic;
    [SerializeField] private Button btn = null;

    // Object Initialization
    public Neo4jConnector graph = new Neo4jConnector();

    // Writers
    private TextWriter textWriter;
    private TextWriter transcriptionTextWriter;

    protected DictationRecognizer dictationRecognizer;

    [System.Serializable]
    public class UnityEventString : UnityEngine.Events.UnityEvent<string> { };
    public UnityEventString OnPhraseRecognized;

    public UnityEngine.Events.UnityEvent OnUserStartedSpeaking;

    private bool isUserSpeaking;
    
    private IGazeFocusable lastFocus;
    
    // Action for the trigger press
    public SteamVR_Action_Boolean triggerAction;
    
    // Hand type: Left or Right controller
    public SteamVR_Input_Sources handType;
	
	public float waitTime = 60f;
	
	RasaCommunication rasa = new RasaCommunication();
	
   // Start is called before the first frame update
    async void Start()
    {
        GameObject[] allObjects = FindObjectsOfType<GameObject>(); // Get all objects in scene

        foreach (GameObject obj in allObjects)
        {
            Renderer renderer = obj.GetComponent<Renderer>();

            if (renderer != null) // If it has a renderer, get bounding box
            {
                Bounds bounds = renderer.bounds;

                // Use F6 for six decimal places, you can adjust as needed
                string minValues = $"({bounds.min.x:F6}, {bounds.min.y:F6}, {bounds.min.z:F6})";
                string maxValues = $"({bounds.max.x:F6}, {bounds.max.y:F6}, {bounds.max.z:F6})";

                //UnityEngine.Debug.LogError(obj.name + " Bounding Box: Min " + minValues + " Max " + maxValues);
            }
        }

        paintingsDic = new Dictionary<string, int>();
        
        foreach (var device in Microphone.devices)
        {
            UnityEngine.Debug.Log("Name: " + device);
        }
		
		if (triggerAction == null)
        {
            triggerAction = SteamVR_Actions.default_GrabPinch; // Default trigger action
        }
		StartCoroutine(PerformEvery30Seconds());
		
        
    }
	
	IEnumerator PerformEvery30Seconds()
    {
        while (true) // Infinite loop to keep repeating the function
        {
			
			// Call your function
			MyFunction();

			// Wait for 60 seconds before repeating
			yield return new WaitForSeconds(waitTime);
        }
    }

    void MyFunction()
    {
		if (started && !triggerAction.GetStateDown(handType))
		{
            // Your function logic here
            UnityEngine.Debug.Log("Function performed every 60 seconds");
			rasa.SendDataToRasa("prompting_user", "prompting_user");
		}
    }

    private void SetStatus(string status)
    {
        statusText.text = filename + ": " + status;
    }
	
    private void Update()
    {
        if (started)
        {
			
            if (FallBackIndicator != null && FallBackIndicator.activeInHierarchy)
            {
                AddFallbackPointerData();
                return;
            }
            AddData();
        }
		
		if (triggerAction.GetStateDown(handType)) // Replace with your actual input
        {
            //Debug.LogError("Hi");
            
			rasa.CheckMicrophone();
        }
        
        // Check if the button is released
        if (triggerAction.GetStateUp(handType)) // Replace with your actual input
        {
            //Debug.LogError("Bye");
            rasa.StopDictationEngine();
			waitTime = 60f;
        }
        
    }
    
    private void ParameterOnClick(string test)
    {
        paintingsDic[test] = 0;
    }
	
    public void StartDataCollection(string recordingName)
    {
		actorNodeID = graph.CreateActorNode(recordingName,DateTime.Now.ToString("yyyyMMddHHmmss"));
        measureNodeID = graph.CreateMeasureNode(actorNodeID);
		
		
        rasa.SendDataToRasa("sending_actor_id", actorNodeID);
		
        InitializeRecording(recordingName);
    }
    
    private void InitializeRecording(string recordingName)
    {
        // Record microphone
        filename = recordingName + " (" + DateTime.Now.ToString("yyyy-MM-dd HH-mm-ss") + ")";
        textWriter = new StreamWriter(getPath());
        transcriptionTextWriter = new StreamWriter(getPath(filename + "_transcription.txt"));

        // Creating First row of titles manually..
        string[] rowDataTemp = new string[] {
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
		};
        textWriter.WriteLine(string.Join(",", rowDataTemp));

        started = true;
        recording = Microphone.Start(mic, false, 2000, 44100);
        startTime = Time.time;


        SetStatus("Recording started - " + Microphone.devices[0]);
    }
    
    private void AddFallbackPointerData()
    {
        var ray = Camera.main.ScreenPointToRay(Input.mousePosition);
        GameObject focusedGameObject = null;
        Vector3? hitcoord = null;
        Vector2? textureCoord = null;
    
        var hits = Physics.RaycastAll(ray, 100).OrderBy(h => h.distance);
        if (hits.Any())
        {
            var hit = hits.First();
            hitcoord = hit.point;
            textureCoord = hit.textureCoord;
            var focusable = hit.transform.GetComponent<IGazeFocusable>();
            if (focusable != null)
            {
                focusedGameObject = hit.transform.gameObject;
    
                if (lastFocus != null)
                {
                    lastFocus.GazeFocusChanged(false);
                }
                lastFocus = focusable;
                focusable.GazeFocusChanged(true);
            }
            else
            {
                if (lastFocus != null)
                {
                    lastFocus.GazeFocusChanged(false);
                }
            }
        }
    
        ProccessData(Time.time, focusedGameObject, hitcoord, textureCoord);
    }
    
    private void AddData()
    {
        // Get eye tracking data in world space
        var eyeTrackingData = TobiiXR.GetEyeTrackingData(TobiiXR_TrackingSpace.World);
    
        // For social use cases, data in local space may be easier to work with
        var eyeTrackingDataLocal = TobiiXR.GetEyeTrackingData(TobiiXR_TrackingSpace.Local);
    
        var timestamp = eyeTrackingDataLocal.Timestamp;
    
        GameObject focusedGameObject = null;
        // Get gaze ray and collision point
        var p1 = eyeTrackingData.GazeRay.Origin; //origin
        var dir = eyeTrackingData.GazeRay.Direction;
        var ray = new Ray(p1, dir);
        Vector3? hitcoord = null;
        Vector2? textureCoord = null;
    
        var hits = Physics.RaycastAll(ray, 100).OrderBy(h => h.distance);
        if (hits.Any())
        {
            var hit = hits.First();
            hitcoord = hit.point;
            textureCoord = hit.textureCoord;
            var focusable = hit.transform.GetComponent<IGazeFocusable>();
            if (focusable != null)
            {
                focusedGameObject = hit.transform.gameObject;
    
                if (lastFocus != null)
                {
                    lastFocus.GazeFocusChanged(false);
                }
                lastFocus = focusable;
                focusable.GazeFocusChanged(true);
            }
            else
            {
                if (lastFocus != null)
                {
                    lastFocus.GazeFocusChanged(false);
                }
            }
        }
    
        ProccessData(timestamp, focusedGameObject, hitcoord, textureCoord);
    }

    //public string VectorString(Vector3 vector) => vector.x + "," + vector.y + "," + vector.z;

    //public string VectorString(Vector2 vector) => vector.x + "," + vector.y;
    public string VectorString(Vector3 vector) =>
    string.Format(CultureInfo.InvariantCulture, "{0},{1},{2}", vector.x, vector.y, vector.z);

    public string VectorString(Vector2 vector) =>
        string.Format(CultureInfo.InvariantCulture, "{0},{1}", vector.x, vector.y);


    public void ProccessData(float timestamp, GameObject focusedGameObject, Vector3? coord, Vector2? textureCoord)
    {
        // SAVE VARIABLES IN NEW ROW - initialize row 
        var rowDataTemp = new string[6];
        //rowDataTemp[0] = timestamp.ToString(); // (could also be formatted e.g.: ToString("#.0000"))
        // the timestamp
        rowDataTemp[0] = timestamp.ToString(CultureInfo.InvariantCulture); // (could also be formatted e.g.: ToString("#.0000"))
        // player position x and y and z
        rowDataTemp[1] = VectorString(player.headCollider.transform.position);

        // gaze position coordinates x y and z
        rowDataTemp[4] = coord.HasValue ? VectorString(coord.Value) : "None";

		string objectName = "";
		
        // Check whether TobiiXR has any focused objects (and whether we are focusing on an area of interest)
        if (focusedGameObject != null)
        {
            var focusobj = focusedGameObject.name.Split(new[] { "_AoI_" }, StringSplitOptions.None);
            // check if AoI:
            // object name
            rowDataTemp[2] = focusobj[0]; // object name
            //rowDataTemp[3] = Vector3.Distance(focusedGameObject.transform.position, player.headCollider.transform.position).ToString();
            // distance
            rowDataTemp[3] = Vector3.Distance(focusedGameObject.transform.position, player.headCollider.transform.position).ToString(CultureInfo.InvariantCulture);


            objectName = focusobj[0];
			
			
            if (textureCoord.HasValue)
            {
                heatMapScript.SendData(filename, focusedGameObject, textureCoord.Value);
            }

            // object coordinates x and y
            rowDataTemp[5] = VectorString(textureCoord.Value);
        }
        else
        {
            // Tobii isn't focusing on anything right now
            rowDataTemp[2] = "None"; // no object
            rowDataTemp[3] = "None"; // no object
        }
		
        //paintingName = rowDataTemp[2];
		
	
        
        if (!rowDataTemp[2].Equals("None"))
        {
			ProcessDatabaseQueries(rowDataTemp);
        }
		

        // Add whole new row to list
        //rowData.Add(rowDataTemp);
        textWriter.WriteLine(string.Join(",", rowDataTemp));
        //UnityEngine.Debug.Log(string.Join(";", rowDataTemp));
    }

    async public void SaveData()
    {
        if (!started)
            return;

        textWriter.Close();
        transcriptionTextWriter.Close();

        // Save sound
        Microphone.End(mic);
        var timeSinceRecordStarted = Time.time - startTime;

        float lengthL = recording.length;
        float samplesL = recording.samples;
        float samplesPerSec = (float)samplesL / lengthL;
        float[] samples = new float[(int)(samplesPerSec * timeSinceRecordStarted)];
        recording.GetData(samples, 0);

        AudioClip trimmedRecording = AudioClip.Create("RecordedSound", (int)(timeSinceRecordStarted * samplesPerSec), 1, 44100, false, false);
        trimmedRecording.SetData(samples, 0);

        SavWav.Save(filename + "_Recording", trimmedRecording);

        heatMapScript.SaveData();

        SetStatus("Data saved succesfully!");
        started = false;
    }

    public void OnApplicationQuit()
    {
        SaveData();
    }

    // Following method is used to retrive the relative path as device platform
    private string getPath() => getPath(filename + ".csv");
    public static string getPath(string filename)
    {
#if UNITY_EDITOR
        return Application.dataPath + "/OUTPUT/" + filename;
#else
        return Application.dataPath + "/" + filename;
#endif
    }
    
    private void ProcessDatabaseQueries(string[] rowData)
    {
		string[] names = {
			"A1", "A2", "A3", "B1",
			"B2", "B3", "B4", "B5",
			"C1", "C2", "C3", "C4",
			"C5", "C6", "D1", "D2",
			"D3", "D4", "D5"
		};

		string aoiName = "";
		string objectName = ""; // Initialize objectName for later use.

		// Check if the first two characters of rowData[2] exist in names array.
		if (names.Contains(rowData[2].Substring(0, 2)))
		{
			
			// Query to create the action and related entities in the database
			graph.BuildActionCreationQuery(rowData,actorNodeID);

			// Query to calculate and store the duration of the previous action
			graph.BuildDurationCalculationQuery(actorNodeID);
			
			// If rowData[2] contains "Painting", set aoiName to "Background".
			aoiName = rowData[2].Substring(3); // Extract substring starting from index 2.
			if (rowData[2].Contains("Painting"))
			{
				aoiName = "Background";
			}
			if (rowData[2].Contains("Text"))
			{
				aoiName = rowData[2].Substring(0, 2)+"_Text";
			}
			// Set objectName to the first two characters of rowData[2].
			objectName = rowData[2].Substring(0, 2);
			
			paintingName = objectName;
		
			// Query to update time spent on the object
			graph.BuildTimeSpentOnObjectQuery("objectName",objectName,actorNodeID,measureNodeID);

			// Query to update fixation count on the object
			graph.BuildFixationCountQuery("objectName",objectName,actorNodeID,measureNodeID);

			// Query to update the number of transitions between fixation points
			graph.BuildTransitionCountQuery("objectName",objectName,actorNodeID,measureNodeID);
			
			graph.BuildTransitionCountBetweenAOIsQuery(objectName,actorNodeID,measureNodeID);
			
			
			if (aoiName != ""){
				// Query to update time spent on the object
				graph.BuildTimeSpentOnObjectQuery("name",aoiName,actorNodeID,measureNodeID);
		
				// Query to update fixation count on the object
				graph.BuildFixationCountQuery("name",aoiName,actorNodeID,measureNodeID);
		
				// Query to update the number of transitions between fixation points
				graph.BuildTransitionCountQuery("name",aoiName,actorNodeID,measureNodeID);
			}
		}
		
            

    }
	
	
    
}