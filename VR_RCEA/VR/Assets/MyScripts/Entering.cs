using System.Collections;
using System.Collections.Generic;
using UnityEngine;

//This script allows the player to enter the museum after clicking the test painting and test text. 
//It makes the entrance wall disappear, as soon as both of these actions have been fulfilled. 
//It also signals to the data collector that the player has started their visit, so the timer for the museum visit starts.

public class Entering : MonoBehaviour
{
    public ClickTarget testpaint;
    public ClickTarget testtxt;
    public GameObject warningtext;

    // Update is called once per frame

    private void Start()
    {
        Debug.Log("Painting has been clicked: " + testpaint.clicked);
        Debug.Log("Text has been clicked: " + testtxt.clicked);
    }

    void Update()
    {
        if (testpaint.clicked && testtxt.clicked)
        {
            // change material of entrancewall, remove text, remove collider
            this.GetComponent<MeshRenderer>().enabled = false;
            this.GetComponent<BoxCollider>().enabled = false;
            //this.transform.Find("canvas/warning").gameObject.SetActive(false);
            warningtext.SetActive(false);
        }
    }
}