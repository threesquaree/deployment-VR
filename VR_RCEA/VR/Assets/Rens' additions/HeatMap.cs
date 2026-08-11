using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

/// <summary>
/// Script that generates .csv file heat maps of each gaze object that the user looks at.
/// Made by Rens van der Werff
/// </summary>

public class HeatMap : MonoBehaviour
{
    public struct heatMapElement
    {
        public GameObject obj;
        public float[][] floatHeatMap;
    }

    private List<heatMapElement> heatMaps = new List<heatMapElement>();

    public int heatMapSize = 100;
    private String filename = "No_paintings";
    private GameObject focusObject;
    private Vector2 coordinates;

    // Get data from GetEyeData script
    public void SendData(String newName, GameObject obj, Vector2 coords)
    {
        filename = newName + "_Heatmaps";
        focusObject = obj;
        coordinates = coords;

        BuildHeatMap();
    }

    private void BuildHeatMap()
    {
        bool hasHeatmap = false;
        float[][] currentHeatMap = new float[0][];
        int map;

        // Checks if the gameObject already has a heat map
        for (map = 0; map < heatMaps.Count; map++)
        {
            if (heatMaps[map].obj == focusObject)
            {
                currentHeatMap = heatMaps[map].floatHeatMap;
                hasHeatmap = true;
                break;
            }
        }

        // Creates heat map if it doesn't already have one
        if (!hasHeatmap)
        {
            currentHeatMap = new float[heatMapSize][];
            for (int i = 0; i < currentHeatMap.Length; i++)
            {
                currentHeatMap[i] = new float[heatMapSize];
            }
            map = heatMaps.Count;

            heatMaps.Add(new heatMapElement());
        }

        // Add values to the heat map
        if (coordinates != Vector2.zero)
        {
            float elementSize = 1 / (float)heatMapSize;
            int x = (int)(coordinates.x / elementSize);
            int y = (int)(coordinates.y / elementSize);

            currentHeatMap[y][x] += Time.deltaTime;
        }

        heatMapElement newHeatMap = new heatMapElement();
        newHeatMap.obj = focusObject;
        newHeatMap.floatHeatMap = currentHeatMap;

        heatMaps[map] = newHeatMap;
    }

    // Save the heat maps
    public void SaveData() {
        string filePath = getPath();
        string directory = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(directory))
            Directory.CreateDirectory(directory);
        StreamWriter writer = new StreamWriter(filePath);

        string delimiter = ",";

        foreach (var hmap in heatMaps)
        {
            writer.WriteLine(hmap.obj.ToString());

            for (int i = hmap.floatHeatMap.Length - 1; i >= 0; i--)
            {
                writer.WriteLine(String.Join(delimiter, hmap.floatHeatMap[i]));
            }
        }
        writer.Close();
    }
    
    private string getPath()
    {
        return GetEyeData.getPath((filename ?? "") + ".csv");
    }
}
