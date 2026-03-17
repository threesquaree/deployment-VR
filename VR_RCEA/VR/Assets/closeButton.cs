using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class closeButton : MonoBehaviour
{ 
    public GameObject Panel;
    public GameObject SecondPanel;
    public GameObject infoPanel1;
    public GameObject infoPanel2;
    public void PanelCloser()
    {
        if (Panel != null)
        {
            Panel.SetActive(false);
        }
    }

    public void interestingPainting()
    {
        if (Panel != null)
        {
            Panel.SetActive(false);
            if (SecondPanel != null)
            {
                SecondPanel.SetActive(true);
            }
        }
        
    }

    public void wantToKnowMore()
    {
        if (Panel != null)
        {
            Panel.SetActive(false);
            if (infoPanel1 != null)
            {
                infoPanel1.SetActive(true);
            }
            if (infoPanel2 != null)
            {
                infoPanel2.SetActive(true);
            }
        }
    }
}
