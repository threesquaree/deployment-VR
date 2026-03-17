using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

public class ImageResizer : MonoBehaviour
{
    public RawImage rawImage;
    // Start is called before the first frame update
    void Start()
    {
        CanvasExtensions.SizeToParent(rawImage);
    }

    // Update is called once per frame
    void Update()
    {
        
    }
}
