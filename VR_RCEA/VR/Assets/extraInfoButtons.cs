using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class extraInfoButtons : MonoBehaviour
{
    public GameObject button;
    public GameObject Panel;

    public void PanelOpener()
    {
        if (Panel != null)
        {
            if (button != null)
            {
                bool isActive = Panel.activeSelf;
                Panel.SetActive(!isActive);
            }
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
