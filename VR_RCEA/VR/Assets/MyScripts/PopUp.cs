using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

public class PopUp : MonoBehaviour
{
    public bool popupactive = false;
    private float starttime_popup;
    [SerializeField] Sprite popupimg;
    [SerializeField] string title;
    [SerializeField] string info;
    [SerializeField] string description;

    void OnMouseOver()
    {
        if (Input.GetMouseButtonDown(0)){
            OpenPopUp();
        }
    }

    private void Update()
    {
        
        if (popupactive && Input.GetKeyDown(KeyCode.Space))
            ClosePopup();
    }

    private void OpenPopUp()
    {
        // Set up and activate canvas
        GameObject canvascontrol = GameObject.Find("CanvasControl");
        GameObject popupcanvas = canvascontrol.transform.Find("PopupCanvas").gameObject;

        // Set variables
        popupcanvas.transform.Find("ImageContainer/Image").gameObject.GetComponent<Image>().sprite = popupimg;
        //popupcanvas.transform.Find("TextContainer/Title").gameObject.GetComponent<Text>().text = title;
        //popupcanvas.transform.Find("TextContainer/Info").gameObject.GetComponent<Text>().text = info;
        //popupcanvas.transform.Find("TextContainer/Description").gameObject.GetComponent<Text>().text = description;

        // Activate and start recording time
        popupcanvas.SetActive(true);
        popupactive = true;
        starttime_popup = Time.time; //start counting time

        // Disable player control
        GameObject player = GameObject.Find("FPSControllerVariant");
        (player.GetComponent("FirstPersonController") as MonoBehaviour).enabled = false;
    }

    public void ClosePopup()
    {
        // Deactivate canvas
        GameObject.Find("PopupCanvas").SetActive(false);
        GameObject.Find("FPSControllerVariant").SetActive(true);
        popupactive = false;

        //Trigger data collector (send info and save event)
        DataCollector dc = GameObject.Find("EventSystem").gameObject.GetComponent<DataCollector>();
        dc.StopTimer(title+" (img)",starttime_popup);

        // Enable player control
        GameObject player = GameObject.Find("FPSControllerVariant");
        (player.GetComponent("FirstPersonController") as MonoBehaviour).enabled = true;
    }

}
