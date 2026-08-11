using System;
using System.Collections;
using System.IO;
using UnityEngine;

/// <summary>
/// High-resolution still capture for figures in papers and posters.
///
/// Why not just screenshot the Game view: while SteamVR is driving the scene the
/// Game view is a mirror of one eye, so it is locked to the HMD's aspect ratio and
/// its resolution, and it carries the screen-space overlay UI. This renders a
/// chosen camera into an offscreen RenderTexture at whatever resolution is asked
/// for, which decouples the figure from the headset entirely and, as a side
/// effect, leaves Screen Space Overlay canvases (the 'User canvas' recording
/// controls) out of the image. World-space canvases -- the wall texts, exhibit
/// labels -- still render, which is what a museum figure needs.
///
/// The project renders in Linear color space, so the RenderTexture is sRGB and the
/// PNG comes out matching the headset rather than washed out.
///
/// Usage: drop on any GameObject, press Play, frame the shot, press F11.
/// Files land in <project>/Screenshots.
/// </summary>
public class PublicationCapture : MonoBehaviour
{
    [Header("Input")]
    public KeyCode captureKey = KeyCode.F11;

    [Header("Camera")]
    [Tooltip("Leave empty to use whichever camera is currently rendering.")]
    public Camera captureCamera;

    [Tooltip("Vertical FOV to render with. 0 keeps the camera's own value. " +
             "65-75 widens the view for a room shot; past ~90 the perspective " +
             "distortion starts to look wrong in print.")]
    [Range(0f, 120f)]
    public float fieldOfViewOverride = 0f;

    [Header("Output")]
    public int width = 3840;
    public int height = 2160;

    [Tooltip("MSAA samples on the offscreen target: 1, 2, 4 or 8. 8 is worth it " +
             "for stills -- the picture frames and wall edges are where aliasing shows.")]
    public int antiAliasing = 8;

    [Tooltip("Relative to the project folder (the parent of Assets).")]
    public string outputFolder = "Screenshots";

    [Header("Hidden during capture")]
    [Tooltip("Objects switched off for the frame and restored right after -- HUDs, " +
             "debug helpers, anything that should not appear in a figure.")]
    public GameObject[] hideDuringCapture;

    private bool capturing;

    private void Update()
    {
        if (Input.GetKeyDown(captureKey) && !capturing)
            StartCoroutine(CaptureRoutine());
    }

    private Camera ResolveCamera()
    {
        if (captureCamera != null)
            return captureCamera;

        // Camera.main only matches an enabled camera tagged MainCamera; after a
        // SteamVR rig swap the tagged one may be inactive, so fall back to
        // whichever camera is actually live.
        if (Camera.main != null && Camera.main.isActiveAndEnabled)
            return Camera.main;

        Camera[] all = Camera.allCameras;
        return all.Length > 0 ? all[0] : null;
    }

    private IEnumerator CaptureRoutine()
    {
        capturing = true;

        // Wait for end of frame so anything that animates or updates UI this frame
        // has settled before the shot is taken.
        yield return new WaitForEndOfFrame();

        try
        {
            Capture();
        }
        finally
        {
            capturing = false;
        }
    }

    private void Capture()
    {
        Camera cam = ResolveCamera();
        if (cam == null)
        {
            Debug.LogWarning("[PublicationCapture] No camera to capture from.");
            return;
        }

        if (width < 1 || height < 1)
        {
            Debug.LogWarning("[PublicationCapture] Width and height must both be positive.");
            return;
        }

        var wasActive = new bool[hideDuringCapture == null ? 0 : hideDuringCapture.Length];
        for (int i = 0; i < wasActive.Length; i++)
        {
            GameObject go = hideDuringCapture[i];
            if (go == null)
                continue;
            wasActive[i] = go.activeSelf;
            go.SetActive(false);
        }

        RenderTexture rt = null;
        Texture2D shot = null;

        // Everything the camera owns has to go back exactly as it was; this runs
        // mid-session while the study scene is live.
        RenderTexture previousTarget = cam.targetTexture;
        RenderTexture previousActive = RenderTexture.active;
        float previousFov = cam.fieldOfView;
        float previousAspect = cam.aspect;
        StereoTargetEyeMask previousEye = cam.stereoTargetEye;

        try
        {
            int samples = (antiAliasing == 1 || antiAliasing == 2 || antiAliasing == 4 || antiAliasing == 8)
                ? antiAliasing
                : 8;

            rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            rt.antiAliasing = samples;
            rt.Create();

            if (fieldOfViewOverride > 0f)
                cam.fieldOfView = fieldOfViewOverride;

            // Without this the camera keeps the screen's aspect and the image comes
            // out stretched at any resolution that is not the Game view's shape.
            cam.aspect = (float)width / height;

            // A camera still bound to an eye renders through the stereo path and
            // ignores the target texture.
            cam.stereoTargetEye = StereoTargetEyeMask.None;
            cam.targetTexture = rt;
            cam.Render();

            RenderTexture.active = rt;
            shot = new Texture2D(width, height, TextureFormat.RGB24, false);
            shot.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            shot.Apply();

            string folder = Path.Combine(Directory.GetParent(Application.dataPath).FullName, outputFolder);
            Directory.CreateDirectory(folder);

            string file = string.Format("museum_{0:yyyy-MM-dd_HH-mm-ss}_{1}x{2}.png",
                DateTime.Now, width, height);
            string path = Path.Combine(folder, file);

            File.WriteAllBytes(path, shot.EncodeToPNG());
            Debug.LogFormat("[PublicationCapture] Wrote {0}  (fov {1:F1}, {2}x MSAA)",
                path, cam.fieldOfView, samples);
        }
        catch (Exception e)
        {
            Debug.LogErrorFormat("[PublicationCapture] Capture failed: {0}", e);
        }
        finally
        {
            cam.targetTexture = previousTarget;
            cam.fieldOfView = previousFov;
            cam.stereoTargetEye = previousEye;
            // Restoring aspect explicitly is not enough; ResetAspect re-links the
            // camera to the screen so later resizes keep working.
            cam.aspect = previousAspect;
            cam.ResetAspect();
            RenderTexture.active = previousActive;

            if (rt != null)
            {
                rt.Release();
                Destroy(rt);
            }
            if (shot != null)
                Destroy(shot);

            for (int i = 0; i < wasActive.Length; i++)
            {
                GameObject go = hideDuringCapture[i];
                if (go != null)
                    go.SetActive(wasActive[i]);
            }
        }
    }
}
