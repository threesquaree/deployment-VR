using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

public class urlClicked : MonoBehaviour
{
    // Start is called before the first frame update

    public string url;
    public Text text;
    public void open()
    {
        text.text = "Open";
        Application.OpenURL(url);
    }
}
