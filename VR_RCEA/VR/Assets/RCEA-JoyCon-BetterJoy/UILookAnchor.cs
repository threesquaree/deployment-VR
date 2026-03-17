using UnityEngine;

[ExecuteAlways]
public class UILookAnchor : MonoBehaviour
{
    public Transform targetCamera;
    [Tooltip("Meters from camera (right, down, forward).")]
    public Vector3 localPos = new Vector3(0.35f, -0.25f, 0.7f);
    [Tooltip("Size of the canvas in meters (width, height).")]
    public Vector2 sizeMeters = new Vector2(0.25f, 0.25f);
    [Tooltip("Canvas Scaler → Reference Pixels Per Unit.")]
    public float pixelsPerUnit = 1000f;

    RectTransform rt;

    void OnEnable() { rt = GetComponent<RectTransform>(); Apply(); }
    void Update() { Apply(); }

    void Apply()
    {
        if (!rt) return;

        // Size canvas in pixels based on meters + PPU
        rt.sizeDelta = sizeMeters * pixelsPerUnit;

        // Make the first child match the canvas size (optional but handy)
        if (rt.childCount > 0)
        {
            var child = rt.GetChild(0) as RectTransform;
            if (child) child.sizeDelta = rt.sizeDelta;
        }

        // Bind to camera
        if (!targetCamera)
        {
            var cam = Camera.main;
            if (cam) targetCamera = cam.transform;
        }
        if (!targetCamera) return;

        // Place & face the camera
        transform.position = targetCamera.TransformPoint(localPos);
        transform.rotation = Quaternion.LookRotation(
            transform.position - targetCamera.position, targetCamera.up);
    }
}
