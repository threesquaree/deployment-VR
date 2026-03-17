using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using static System.Net.Mime.MediaTypeNames;

public class PopupMessage : MonoBehaviour
{

    public GameObject ui;

    // Use t$$anonymous$$s for initialization
    void Start()
    {

    }

    // Update is called once per frame
    void Update()
    {
    }

    public void Open(string inventoryStuffName, string message)
    {
        ui.SetActive(!ui.activeSelf);

        if (ui.activeSelf)
        {
            
        }
    }
    public void Close()
    {
        ui.SetActive(!ui.activeSelf);
        if (!ui.activeSelf)
        {
            Time.timeScale = 1f;
        }
    }
    //You need to have Folder Resources/InvenotryItems
    public Texture TakeInvenotryCollecition(string LoadCollectionsToInventory)
    {
        Texture loadedGO = Resources.Load("InvenotryItems/" + LoadCollectionsToInventory, typeof(Texture)) as Texture;
        return loadedGO;
    }
}