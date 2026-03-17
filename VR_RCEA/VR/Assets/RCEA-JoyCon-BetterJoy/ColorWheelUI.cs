using UnityEngine;
using UnityEngine.UI;

public class ColorWheelUI : MonoBehaviour
{
    public enum Mode { Continuous, Sectors13, Sectors9, Sectors5 }

    [Header("Wiring")]
    public Image wheelImage;
    public Image indicatorImage;

    [Header("Mode")]
    public Mode mode = Mode.Continuous;

    [Header("Anchor colors (axes before rotation)")]
    // These four axis anchors are blended around the ring.
    // Primaries sit on the diagonals (45/135/225/315) as midpoints between anchors.
    public Color col0 = new Color(0.46f, 0.80f, 0.47f); // 0°   (between Green & Yellow)
    public Color col90 = new Color(0.93f, 0.80f, 0.66f); // 90°  (between Yellow & Red)
    public Color col180 = new Color(0.87f, 0.28f, 0.28f); // 180° (between Red & Blue)
    public Color col270 = new Color(0.53f, 0.60f, 0.94f); // 270° (between Blue & Green)

    [Header("Anchor rotation")]
    [Tooltip("Rotate the color ring without changing sector geometry.")]
    public float anchorOffsetDeg = 45f;  // 45 makes primaries land on diagonals with the defaults

    [Header("Alpha / center fade")]
    [Range(0, 1)] public float minAlpha = 0f;
    [Range(0, 1)] public float maxAlpha = 0.9f;
    public Color centerGrey = new Color(0.8f, 0.8f, 0.8f, 0f);
    public bool fadeTowardWhite = true;

    [Header("Center radius (for modes with a center sector)")]
    [Range(0f, 1f)] public float centerRadius = 0.15f;

    // Live values (used by logger/other code)
    public Vector2 CurrentVA { get; private set; }
    public float CurrentAngleDeg { get; private set; } // 0..360, 0° = +X (valence+)
    public float CurrentIntensity { get; private set; } // |VA|
    public int CurrentSector { get; private set; } // Sectors9: 0..7, center=8
                                                   // Sectors13: 0..11, center=12
                                                   // Sectors5: 0..3, center=4

    public void OnVA(Vector2 va)
    {
        if (!wheelImage) return;

        // clamp/smooth inputs
        var v = Vector2.ClampMagnitude(va, 1f);
        float r = v.magnitude;
        float ang = Mathf.Atan2(v.y, v.x); if (ang < 0) ang += Mathf.PI * 2f;       // 0..2π
        float angDeg = ang * Mathf.Rad2Deg;                                         // 0..360
        float t = ang / (Mathf.PI * 2f);                                            // 0..1

        // cache for others
        CurrentVA = v;
        CurrentIntensity = r;
        CurrentAngleDeg = angDeg;
        CurrentSector = -1;

        // rotate color ring independently from sector math
        float tHue = Mathf.Repeat(t + anchorOffsetDeg / 360f, 1f);

        Color hue;

        switch (mode)
        {
            case Mode.Continuous:
                hue = SampleContinuous(tHue);
                break;

            case Mode.Sectors13:
                {
                    if (r <= centerRadius) { hue = centerGrey; CurrentSector = 12; }
                    else
                    {
                        int s = Mathf.FloorToInt(((angDeg + 15f) % 360f) / 30f); // 0..11 (30°)
                        float centerT = ((s * 30f) + 15f) / 360f;
                        hue = SampleContinuous(Mathf.Repeat(centerT + anchorOffsetDeg / 360f, 1f));
                        CurrentSector = s;
                    }
                    break;
                }

            case Mode.Sectors9:
                {
                    if (r <= centerRadius) { hue = centerGrey; CurrentSector = 8; }
                    else
                    {
                        int s8 = Mathf.FloorToInt(((angDeg + 22.5f) % 360f) / 45f); // 0..7 (45°)
                        float centerT = (s8 * 45f) / 360f;
                        hue = SampleContinuous(Mathf.Repeat(centerT + anchorOffsetDeg / 360f, 1f));
                        CurrentSector = s8;
                    }
                    break;
                }

            case Mode.Sectors5:   // NEW: 4 outer 90° wedges centered on 45/135/225/315 + center
                {
                    if (r <= centerRadius) { hue = centerGrey; CurrentSector = 4; }
                    else
                    {
                        // Shift boundaries by -22.5° so quadrants are centered on the diagonals.
                        int s4 = Mathf.FloorToInt(((angDeg - 22.5f + 360f) % 360f) / 90f); // 0..3
                        float centerDeg = s4 * 90f + 45f;                                   // 45/135/225/315
                        float centerT = centerDeg / 360f;
                        hue = SampleContinuous(Mathf.Repeat(centerT + anchorOffsetDeg / 360f, 1f));
                        CurrentSector = s4;
                    }
                    break;
                }

            default:
                hue = SampleContinuous(tHue);
                break;
        }

        if (fadeTowardWhite && CurrentSector != 4 && CurrentSector != 8 && CurrentSector != 12)
            hue = Color.Lerp(Color.white, hue, r);

        Color final = Color.Lerp(centerGrey, hue, r);
        final.a = Mathf.Lerp(minAlpha, maxAlpha, r);

        wheelImage.color = final;

        if (indicatorImage)
        {
            var knob = Color.Lerp(centerGrey, hue, r);
            knob.a = final.a;
            indicatorImage.color = knob;
        }
    }

    // 0..1 ring interpolation across the four axis anchors
    Color SampleContinuous(float t)
    {
        if (t < 0.25f) return Color.Lerp(col0, col90, (t - 0.00f) / 0.25f);
        if (t < 0.50f) return Color.Lerp(col90, col180, (t - 0.25f) / 0.25f);
        if (t < 0.75f) return Color.Lerp(col180, col270, (t - 0.50f) / 0.25f);
        return Color.Lerp(col270, col0, (t - 0.75f) / 0.25f);
    }
}
