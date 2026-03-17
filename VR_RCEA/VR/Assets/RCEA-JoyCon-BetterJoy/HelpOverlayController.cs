using UnityEngine;
using UnityEngine.UI;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

public class HelpOverlayController : MonoBehaviour
{
    [Header("Target")]
    [Tooltip("Image to show/hide. For full-screen, anchor to stretch (min 0,0 max 1,1) on a Screen Space - Overlay canvas.")]
    public Image overlayImage;
    [Range(0f, 1f)] public float defaultAlpha = 0.5f;
    public bool startHidden = true;
    public bool holdToShow = false;

    [Header("Keyboard")]
    public KeyCode toggleKey = KeyCode.H;

    public enum PadButton { South, East, West, North, Start, Select, LShoulder, RShoulder, LStick, RStick }

    [Header("Gamepad (Joy-Con via BetterJoy/XInput)")]
    [Tooltip("Primary gamepad button to accept (e.g., Start for Joy-Con +).")]
    public PadButton primaryButton = PadButton.Start;
    [Tooltip("Secondary gamepad button to accept (e.g., Select for Joy-Con -).")]
    public PadButton secondaryButton = PadButton.Select;

    [Header("Help art by ColorWheel mode")]
    [Tooltip("Drag your ColorWheelUI (ColorWheelHalo) here so we can match the help art to its Mode.")]
    public ColorWheelUI colorWheel;
    public Sprite helpContinuous;
    public Sprite helpSectors5;   // NEW
    public Sprite helpSectors9;
    public Sprite helpSectors13;

    bool _visible;
    ColorWheelUI.Mode _lastMode;

    void OnValidate()
    {
        if (!overlayImage) overlayImage = GetComponent<Image>();
    }

    void Start()
    {
        if (!overlayImage)
        {
            Debug.LogWarning("[HelpOverlay] No overlayImage assigned.");
            return;
        }

        // lock alpha
        var c = overlayImage.color;
        c.a = Mathf.Clamp01(defaultAlpha);
        overlayImage.color = c;

        _visible = !startHidden;
        ApplyVisible();

        UpdateHelpSprite(force: true);
    }

    void Update()
    {
        UpdateHelpSprite();

        bool kbDown = Input.GetKeyDown(toggleKey);
        bool kbHeld = Input.GetKey(toggleKey);

        bool padDown = false, padHeld = false;
#if ENABLE_INPUT_SYSTEM
        var gp = Gamepad.current;
        if (gp != null)
        {
            padDown = WasPressed(gp, primaryButton) || WasPressed(gp, secondaryButton);
            padHeld =  IsHeld(gp, primaryButton)     || IsHeld(gp, secondaryButton);
        }
#endif

        if (holdToShow)
        {
            bool want = kbHeld || padHeld;
            if (want != _visible) { _visible = want; ApplyVisible(); }
        }
        else if (kbDown || padDown)
        {
            _visible = !_visible;
            ApplyVisible();
        }
    }

    void ApplyVisible()
    {
        if (!overlayImage) return;
        overlayImage.enabled = _visible;
    }

    void UpdateHelpSprite(bool force = false)
    {
        if (!overlayImage || !colorWheel) return;

        var mode = colorWheel.mode;
        if (!force && mode == _lastMode) return;

        // Choose sprite (with simple fallbacks if one isn't assigned)
        Sprite chosen = null;
        switch (mode)
        {
            case ColorWheelUI.Mode.Continuous:
                chosen = helpContinuous;
                break;

            case ColorWheelUI.Mode.Sectors5:
                chosen = helpSectors5 != null ? helpSectors5
                        : (helpSectors9 != null ? helpSectors9 : helpContinuous);
                break;

            case ColorWheelUI.Mode.Sectors9:
                chosen = helpSectors9 != null ? helpSectors9
                        : (helpSectors5 != null ? helpSectors5 : helpContinuous);
                break;

            case ColorWheelUI.Mode.Sectors13:
                chosen = helpSectors13 != null ? helpSectors13
                        : (helpSectors9 != null ? helpSectors9
                        : (helpSectors5 != null ? helpSectors5 : helpContinuous));
                break;
        }

        if (chosen) overlayImage.sprite = chosen;
        _lastMode = mode;

        // If you want the image to size to the sprite’s pixel size, uncomment:
        // overlayImage.SetNativeSize();
    }

#if ENABLE_INPUT_SYSTEM
    static bool WasPressed(Gamepad g, PadButton b)
    {
        switch (b)
        {
            case PadButton.South:      return g.buttonSouth.wasPressedThisFrame;
            case PadButton.East:       return g.buttonEast.wasPressedThisFrame;
            case PadButton.West:       return g.buttonWest.wasPressedThisFrame;
            case PadButton.North:      return g.buttonNorth.wasPressedThisFrame;
            case PadButton.Start:      return g.startButton.wasPressedThisFrame;
            case PadButton.Select:     return g.selectButton.wasPressedThisFrame;
            case PadButton.LShoulder:  return g.leftShoulder.wasPressedThisFrame;
            case PadButton.RShoulder:  return g.rightShoulder.wasPressedThisFrame;
            case PadButton.LStick:     return g.leftStickButton.wasPressedThisFrame;
            case PadButton.RStick:     return g.rightStickButton.wasPressedThisFrame;
        }
        return false;
    }
    static bool IsHeld(Gamepad g, PadButton b)
    {
        switch (b)
        {
            case PadButton.South:      return g.buttonSouth.isPressed;
            case PadButton.East:       return g.buttonEast.isPressed;
            case PadButton.West:       return g.buttonWest.isPressed;
            case PadButton.North:      return g.buttonNorth.isPressed;
            case PadButton.Start:      return g.startButton.isPressed;
            case PadButton.Select:     return g.selectButton.isPressed;
            case PadButton.LShoulder:  return g.leftShoulder.isPressed;
            case PadButton.RShoulder:  return g.rightShoulder.isPressed;
            case PadButton.LStick:     return g.leftStickButton.isPressed;
            case PadButton.RStick:     return g.rightStickButton.isPressed;
        }
        return false;
    }
#endif
}
