using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class pointer : MonoBehaviour
{
    public float m_DefaultLenght = 5.0f;
    public GameObject m_Dot;
    public VRInputModule m_InputModule;

    private LineRenderer m_LineRenderer = null;
    private void Awake()
    {
        m_LineRenderer = GetComponent<LineRenderer>();
        
    }

    // Update is called once per frame
    void Update()
    {
        UpdateLine();
        
    }

     private void UpdateLine()
     {
        float targetLenght = m_DefaultLenght;

        RaycastHit hit = CreateRaycast(targetLenght);

        Vector3 endPosition = transform.position + (transform.forward * targetLenght);

        if (hit.collider != null)
            endPosition = hit.point;

        m_Dot.transform.position = endPosition;

        m_LineRenderer.SetPosition(0, transform.position);
        m_LineRenderer.SetPosition(1, endPosition);



     }

    private RaycastHit CreateRaycast(float lenght)
    {
        RaycastHit hit;
        Ray ray = new Ray(transform.position, transform.forward);
        Physics.Raycast(ray, out hit, m_DefaultLenght);


        return hit;
    }
}
