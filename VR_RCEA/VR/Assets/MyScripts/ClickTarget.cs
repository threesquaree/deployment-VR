using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ClickTarget : MonoBehaviour
{
    public bool clicked = false;

    void OnMouseOver()
    {
        if (Input.GetMouseButtonDown(0))
        {
            clicked = true;
            Debug.Log("Player clicked object!");
        }
    }

    public bool HasBeenClicked()
    {
        if (clicked)
            return true;
        else
            return false;
    }
}