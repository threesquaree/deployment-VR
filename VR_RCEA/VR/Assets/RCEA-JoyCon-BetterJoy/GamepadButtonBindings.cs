using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;
#endif

public class GamepadButtonBindings : MonoBehaviour
{
    public enum PadButton { South, East, West, North, Start, Select, LShoulder, RShoulder, LStick, RStick }

    [Header("Bindings")]
    public PadButton pressToTalk = PadButton.LShoulder;
    public PadButton help = PadButton.Start;

    [System.Serializable] public class VoidEvent : UnityEngine.Events.UnityEvent { }
    public VoidEvent OnPressToTalkDown;
    public VoidEvent OnPressToTalkUp;
    public VoidEvent OnHelpPressed;

    bool _pttPrev, _helpPrev;

    void Update()
    {
#if ENABLE_INPUT_SYSTEM
        var gp = Gamepad.current;
        if (gp == null) return;

        bool pttNow = IsHeld(gp, pressToTalk);
        bool helpNow = IsHeld(gp, help);
        if (pttNow && !_pttPrev) OnPressToTalkDown?.Invoke();
        if (!pttNow && _pttPrev) OnPressToTalkUp?.Invoke();
        if (WasPressed(gp, help)) OnHelpPressed?.Invoke();

        _pttPrev = pttNow; _helpPrev = helpNow;
#endif
    }

#if ENABLE_INPUT_SYSTEM
    static bool WasPressed(Gamepad g, PadButton b) => GetButton(g, b)?.wasPressedThisFrame ?? false;
    static bool IsHeld(Gamepad g, PadButton b) => GetButton(g, b)?.isPressed ?? false;
    static ButtonControl GetButton(Gamepad g, PadButton b)
    {
        switch (b)
        {
            case PadButton.South: return g.buttonSouth;
            case PadButton.East: return g.buttonEast;
            case PadButton.West: return g.buttonWest;
            case PadButton.North: return g.buttonNorth;
            case PadButton.Start: return g.startButton;
            case PadButton.Select: return g.selectButton;
            case PadButton.LShoulder: return g.leftShoulder;
            case PadButton.RShoulder: return g.rightShoulder;
            case PadButton.LStick: return g.leftStickButton;
            case PadButton.RStick: return g.rightStickButton;
        }
        return null;
    }
#endif
}
