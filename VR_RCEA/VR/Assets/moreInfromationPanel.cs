using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

public class moreInfromationPanel : MonoBehaviour
{
    // Start is called before the first frame update

    public GameObject Panel;
    public Text titleText;
    public Text descriptionText;
    public string title;
    public string description;
    public void PanelOpener()
    {
        if (Panel != null)
        {
            bool isActive = Panel.activeSelf;
            Panel.SetActive(!isActive);
            titleText.text = title;
            descriptionText.text = description;

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
