using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;

public class RecordingReplay : MonoBehaviour
{
    public bool playing;
    private float minTime;
    private float maxTime;
    public float time;
    public string currentFile;
    private SortedDictionary<float, Record> map;
    public List<float> keys;
    public GameObject faceIndictator;
    public GameObject eyeIndicator;
    public FileInfo[] files;
    public AudioSource audioSource;

    // UI
    [SerializeField] Dropdown dropdown;
    [SerializeField] Slider slider;


    public class Record
    {
        public float timecode;
        public Vector3 headPosition;
        public Vector3 eyePosition;
    }

    // Start is called before the first frame update
    void Start()
    {
        dropdown.ClearOptions();
        var info = new DirectoryInfo(GetEyeData.getPath(""));
        files = info.GetFiles().Where(x => x.Extension == ".csv" && !x.Name.Contains("_Recording") && !x.Name.Contains("_Heatmaps")).ToArray();

        dropdown.AddOptions(files.Select(x => x.Name).ToList());
    }

    private void OnDrag(PointerEventData obj)
    {
        throw new System.NotImplementedException();
    }

    public void SetTime(float time)
    {
        this.time = time;
        UpdateState(time);
    }

    public void SelectFile(int index) => SelectFile(files[index].FullName);

    public void TogglePlay() => playing = !playing;
    public void Pauze() => playing = false;
    public void Play() => playing = true;

    void SelectFile(string file)
    {
        print(file);
        using StreamReader reader = new StreamReader(file);
        StartCoroutine(LoadAudioFile(file.Replace(".csv", "_Recording.wav")));
        string line;
        //Define pattern
        map = new SortedDictionary<float, Record>();
        var i = 0;
        while ((line = reader.ReadLine()) != null)
        {
            i++;
            if (i == 1)
                continue;
            //Separating columns to array
            string[] data = line.Split(',');
            var record = new Record()
            {
                timecode = float.Parse(data[0]),
                headPosition = new Vector3(float.Parse(data[1]), float.Parse(data[2]), float.Parse(data[3])),
                eyePosition = float.TryParse(data[6], out var _) ? new Vector3(float.Parse(data[6]), float.Parse(data[7]), float.Parse(data[8])) : Vector3.zero,
            };

            /* Do something with X */
            if(!map.ContainsKey(record.timecode))
            map.Add(record.timecode, record);
        }
        reader.Close();
        keys = new List<float>(map.Keys);
        minTime = keys.Min();
        maxTime = keys.Max();
        time = minTime;
        slider.minValue = minTime;
        slider.maxValue = maxTime;
    }

    // Update is called once per frame
    void Update()
    {
        if (playing)
        {
            if (!audioSource.isPlaying)
            {
                audioSource.Play();
                audioSource.time = slider.normalizedValue * audioSource.clip.length;
            }

            time += Time.deltaTime;
            slider.value = time;
        }
        else
        {
            if (audioSource.isPlaying)
            {
                audioSource.Stop();
            }
        }
    }

    void UpdateState(float time)
    {
        var index = keys.Aggregate((x, y) => Mathf.Abs(x - time) < Mathf.Abs(y - time) ? x : y); ;
        var record = map[index];
        faceIndictator.transform.position = record.headPosition;
        eyeIndicator.transform.position = record.eyePosition;

    }

    IEnumerator LoadAudioFile(string path)
    {
        using var www = UnityWebRequestMultimedia.GetAudioClip(new Uri(path), AudioType.WAV);
            yield return www.SendWebRequest();
        if (www.result == UnityWebRequest.Result.ConnectionError)
        {
            Debug.Log(www.error);
        }
        else
        {
            AudioClip myClip = DownloadHandlerAudioClip.GetContent(www);
            audioSource.clip = myClip;
        }
    }


    private void OnGUI()
    {

    }
}
