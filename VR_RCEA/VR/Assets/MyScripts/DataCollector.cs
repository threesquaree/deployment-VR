using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using System.IO;
using System;
using System.Text;


public class DataCollector : MonoBehaviour
{
    // link inputfield for filename
    public Text inputfield;
    public string filename; //get this from start participant nr input


    // initialize counters
    public float starttime_experiment;
    private List<string[]> popup_events = new List<string[]>(); // initialize list for data to export

    void Start()
    {
        // Creating First row of titles manually..
        string[] rowDataTemp = new string[3];
        rowDataTemp[0] = "Timestamp";
        rowDataTemp[1] = "PictureName";
        rowDataTemp[2] = "ViewDuration";
        popup_events.Add(rowDataTemp);
    }

    public void AssignFilename()
    {
        filename = inputfield.text;
        Debug.Log("Filename changed to:" + filename);
    }

    public void StartExperimentTimer()
    {
        // start visit (start timer)
        starttime_experiment = Time.time;
        Debug.Log("Started Experiment Timer");
    }

    public void StopTimer(string picturename, float starttime_popup) //call this from PopUp when closing
    {
        // create new entry (row) in popup_events
        string[] rowDataTemp = new string[3];
        rowDataTemp[0] = starttime_popup.ToString("f2"); //timestamp (start)
        rowDataTemp[1] = picturename; //picturename passed from popup script
        rowDataTemp[2] = (Time.time - starttime_popup).ToString("f2"); //view duration
        popup_events.Add(rowDataTemp);
        Debug.LogFormat("Timestamp : {0}, Picturename: {1}, ViewDuration: {2}", rowDataTemp[0], rowDataTemp[1], rowDataTemp[2]);
    }

    public void OnApplicationQuit()
    {

        // Add total visit duration as event
        string[] rowDataTemp = new string[3];
        rowDataTemp[0] = "n/a"; //timestamp (start)
        rowDataTemp[1] = "complete museum visit (finished)"; //picturename passed from popup script
        rowDataTemp[2] = (Time.time - starttime_experiment).ToString("f2"); //view duration
        popup_events.Add(rowDataTemp);

        //save all data to file
        string[][] output = new string[popup_events.Count][];

        for (int i = 0; i < output.Length; i++)
        {
            output[i] = popup_events[i];
        }

        int length = output.GetLength(0);
        string delimiter = ";";

        StringBuilder sb = new StringBuilder();

        for (int index = 0; index < length; index++)
            sb.AppendLine(string.Join(delimiter, output[index]));


        string filePath = GetPath();
        Debug.Log("Saving to path: " + filePath);
        StreamWriter outStream = System.IO.File.CreateText(filePath);
        outStream.WriteLine(sb);
        outStream.Close();
    }

    // Following method is used to retrive the relative path as device platform
    private string GetPath()
    {
#if UNITY_EDITOR
        return Application.dataPath + "/CSV/" + filename + ".csv";
#else
        return Application.dataPath + "/" + filename +".csv";
#endif
    }

}


