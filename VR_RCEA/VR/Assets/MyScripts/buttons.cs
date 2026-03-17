using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;


public class OpenPanel : MonoBehaviour
{
    public GameObject Panel;
    public void PanelOpener()
    {
        if (Panel != null)
        {
            bool isActive = Panel.activeSelf;
            Panel.SetActive(!isActive);
        }
    }
    public void PanelCloser()
    {
        if (Panel != null)
        {
            Panel.SetActive(false);
        }
    }
}