using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Valve.VR;
using Valve.VR.InteractionSystem;
using UnityEngine.UI;

public class ViveControllerButton : MonoBehaviour
{
    public Button button;

    public SteamVR_Action_Boolean m_InteractUI = SteamVR_Input.GetBooleanAction("InteractUI");

    private void Update()
    {
        if (m_InteractUI.GetStateDown(SteamVR_Input_Sources.Any))
        {
            button.onClick.Invoke();
            print("hihi");
            
        }
    }
}
