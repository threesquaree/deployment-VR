using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ToggleScreens : MonoBehaviour
{
    public GameObject onObject;
    public GameObject offObject;


    public void ToggleButton(bool value)
    {
        onObject.SetActive(value);
        offObject.SetActive(!value);

    }
}
