using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Tobii.XR;

/// <summary>
/// Spawns a debug ball at the eye-tracking target, so you can see if the eye-tracking is working.
/// Made by Rens van der Werff
/// </summary>

public class BallAtGaze : MonoBehaviour
{
    private Vector3 newPoint;
    public bool enableSmoothing;
    public float smoothFactor;

    void Update()
    {
        // Get eye-tracking data 
        var eyeTrackingData = TobiiXR.GetEyeTrackingData(TobiiXR_TrackingSpace.World);
        Vector3 p1 = eyeTrackingData.GazeRay.Origin; 
        Vector3 dir = eyeTrackingData.GazeRay.Direction;
        
        // Shoot ray in direction of gaze
        Ray ray = new Ray(p1, dir);
        
        if (Physics.Raycast(ray, out RaycastHit hit))
        {
            newPoint = hit.point;
        }
        
        // Set ball location to ray hit and smooth movement if enabled
        transform.position = enableSmoothing ? Vector3.Lerp(transform.position, newPoint, smoothFactor) : newPoint;
    }
}