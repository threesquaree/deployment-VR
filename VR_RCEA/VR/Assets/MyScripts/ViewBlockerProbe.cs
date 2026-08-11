using System.Collections.Generic;
using System.Text;
using UnityEngine;

/// <summary>
/// Temporary diagnostic helper for tracking down an object that blocks part of
/// the HMD view. Static inspection of the scene file cannot find it when the
/// object is parented to the camera at runtime, so this reports what is actually
/// in front of the camera while the scene is playing.
///
/// Usage: drop this on any GameObject in the scene, press Play, then press F9
/// while the blocking shape is visible. The Console gets one report listing every
/// enabled Renderer inside the camera frustum within MaxDistance, sorted nearest
/// first, with the full hierarchy path and the viewport rectangle it covers.
/// Viewport coords are (0,0) bottom-left to (1,1) top-right, so a shape in the
/// bottom-right of the view has xMax near 1 and yMin near 0.
///
/// F10 disables the nearest reported Renderer, so the culprit can be confirmed by
/// watching it vanish. That only turns off the Renderer component, so nothing
/// that reads the object's active state is disturbed.
///
/// Delete this script once the object is identified.
/// </summary>
public class ViewBlockerProbe : MonoBehaviour
{
    public KeyCode reportKey = KeyCode.F9;
    public KeyCode hideNearestKey = KeyCode.F10;

    // Generous enough to catch anything head-locked, tight enough to exclude the
    // walls and paintings that make up the room itself.
    public float maxDistance = 3.0f;

    private readonly List<Renderer> lastReport = new List<Renderer>();

    private void Update()
    {
        if (Input.GetKeyDown(reportKey))
            Report();

        if (Input.GetKeyDown(hideNearestKey))
            HideNearest();
    }

    private Camera ResolveCamera()
    {
        // Camera.main only finds a camera tagged MainCamera and enabled; when the
        // SteamVR rig has swapped rigs the tagged one may be off, so fall back to
        // whichever camera is actually rendering.
        Camera cam = Camera.main;
        if (cam != null && cam.isActiveAndEnabled)
            return cam;

        Camera[] all = Camera.allCameras;
        return all.Length > 0 ? all[0] : null;
    }

    private void Report()
    {
        Camera cam = ResolveCamera();
        if (cam == null)
        {
            Debug.LogWarning("[ViewBlockerProbe] No active camera found.");
            return;
        }

        Plane[] frustum = GeometryUtility.CalculateFrustumPlanes(cam);
        var hits = new List<Renderer>();

        foreach (Renderer r in FindObjectsOfType<Renderer>())
        {
            if (!r.enabled || !r.gameObject.activeInHierarchy)
                continue;

            float distance = Vector3.Distance(cam.transform.position, r.bounds.center);
            if (distance > maxDistance)
                continue;

            if (!GeometryUtility.TestPlanesAABB(frustum, r.bounds))
                continue;

            hits.Add(r);
        }

        hits.Sort((a, b) =>
            Vector3.Distance(cam.transform.position, a.bounds.center)
                .CompareTo(Vector3.Distance(cam.transform.position, b.bounds.center)));

        lastReport.Clear();
        lastReport.AddRange(hits);

        var sb = new StringBuilder();
        sb.AppendFormat("[ViewBlockerProbe] camera '{0}' at {1}; {2} renderer(s) within {3} m and in frustum\n",
            cam.name, cam.transform.position, hits.Count, maxDistance);

        foreach (Renderer r in hits)
        {
            float distance = Vector3.Distance(cam.transform.position, r.bounds.center);
            Vector4 vp = ViewportRect(cam, r.bounds);

            sb.AppendFormat("  {0:F2} m  {1}\n", distance, Path(r.transform));
            sb.AppendFormat("        viewport x[{0:F2}..{1:F2}] y[{2:F2}..{3:F2}]  layer={4}  type={5}  childOfCamera={6}\n",
                vp.x, vp.y, vp.z, vp.w,
                LayerMask.LayerToName(r.gameObject.layer),
                r.GetType().Name,
                r.transform.IsChildOf(cam.transform));

            Material[] mats = r.sharedMaterials;
            for (int i = 0; i < mats.Length; i++)
            {
                Material m = mats[i];
                sb.AppendFormat("        material[{0}]={1} shader={2}\n",
                    i,
                    m == null ? "<none>" : m.name,
                    m == null || m.shader == null ? "<none>" : m.shader.name);
            }
        }

        // A world-space canvas parented to the head shows up as a Renderer above,
        // but listing canvases separately makes the render mode explicit, which is
        // what decides whether something reaches the HMD at all.
        sb.Append("  --- canvases ---\n");
        foreach (Canvas c in FindObjectsOfType<Canvas>())
        {
            if (!c.isRootCanvas)
                continue;

            sb.AppendFormat("        {0}  mode={1}  camera={2}  childOfCamera={3}\n",
                Path(c.transform),
                c.renderMode,
                c.worldCamera == null ? "<none>" : c.worldCamera.name,
                c.transform.IsChildOf(cam.transform));
        }

        Debug.Log(sb.ToString());
    }

    private void HideNearest()
    {
        if (lastReport.Count == 0)
        {
            Debug.LogWarning("[ViewBlockerProbe] Nothing to hide; press the report key first.");
            return;
        }

        // Entries can be destroyed between the report and this call, so walk until
        // a live one turns up rather than assuming index 0 survived.
        for (int i = 0; i < lastReport.Count; i++)
        {
            Renderer r = lastReport[i];
            if (r == null || !r.enabled)
                continue;

            r.enabled = false;
            Debug.LogFormat("[ViewBlockerProbe] Disabled Renderer on {0}", Path(r.transform));
            return;
        }

        Debug.LogWarning("[ViewBlockerProbe] All reported renderers are already hidden or destroyed.");
    }

    private static Vector4 ViewportRect(Camera cam, Bounds b)
    {
        // Project all eight corners: a single centre point says nothing about how
        // much of the view the object actually covers.
        Vector3 min = b.min;
        Vector3 max = b.max;
        float xMin = float.MaxValue, xMax = float.MinValue;
        float yMin = float.MaxValue, yMax = float.MinValue;

        for (int i = 0; i < 8; i++)
        {
            var corner = new Vector3(
                (i & 1) == 0 ? min.x : max.x,
                (i & 2) == 0 ? min.y : max.y,
                (i & 4) == 0 ? min.z : max.z);

            Vector3 v = cam.WorldToViewportPoint(corner);
            xMin = Mathf.Min(xMin, v.x);
            xMax = Mathf.Max(xMax, v.x);
            yMin = Mathf.Min(yMin, v.y);
            yMax = Mathf.Max(yMax, v.y);
        }

        return new Vector4(xMin, xMax, yMin, yMax);
    }

    private static string Path(Transform t)
    {
        var sb = new StringBuilder(t.name);
        for (Transform p = t.parent; p != null; p = p.parent)
            sb.Insert(0, p.name + "/");
        return sb.ToString();
    }
}
