using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif
using UnityEngine.Events;

public class GamepadVAReader : MonoBehaviour
{
    [Header("Processing")]
    [Range(0f, 0.6f)] public float deadZone = 0.18f;
    [Range(0f, 0.95f)] public float smoothing = 0.25f;   // 0=no smoothing, 1=very slow
    public bool invertY = false;                          // set to taste
    public bool useRightStick = false;

    [Header("Idle reset")]
    [Tooltip("If true, when the stick is inside the dead-zone we zero the smoothed value immediately.")]
    public bool snapToZeroOnIdle = true;
    [Tooltip("If true, when entering idle we send a single (0,0) sample to reset the UI/log.")]
    public bool publishZeroWhenIdle = true;

    [Header("Publishing")]
    [Range(1f, 60f)] public float publishHz = 10f;
    public bool publishOnlyOnChange = true;
    [Range(0f, 0.5f)] public float minChangeToEmit = 0.02f;

    [System.Serializable] public class VAEvent : UnityEvent<Vector2> { }
    public VAEvent OnVAChanged = new VAEvent();

    Vector2 _smoothed, _last;
    bool _sent, _wasIdle;
    float _t;

    Vector2 _lastVA = Vector2.zero;
    public Vector2 GetLastVA() => _lastVA;

    float MinChangeSqr => minChangeToEmit * minChangeToEmit;

    void OnEnable()
    {
        _smoothed = _last = _lastVA = Vector2.zero;
        _sent = false; _wasIdle = true; _t = 0f;
    }

    void Update()
    {
        Vector2 raw = ReadStick();

        bool idleNow = raw.magnitude < deadZone;
        Vector2 v = idleNow ? Vector2.zero : raw;
        if (invertY) v.y = -v.y;
        v = Vector2.ClampMagnitude(v, 1f);

        // kill smoothing memory while idle (fresh vector each time)
        if (snapToZeroOnIdle && idleNow) _smoothed = Vector2.zero;
        else _smoothed = Vector2.Lerp(_smoothed, v, 1f - Mathf.Clamp01(smoothing));

        // publish at fixed rate
        _t += Time.unscaledDeltaTime;
        if (_t < 1f / Mathf.Max(1f, publishHz)) return;
        _t = 0f;

        Vector2 toEmit = _smoothed;
        bool changed = !_sent || (toEmit - _last).sqrMagnitude >= MinChangeSqr;

        // when entering idle, optionally force a single (0,0)
        if (idleNow && publishZeroWhenIdle && !_wasIdle)
        {
            toEmit = Vector2.zero;
            changed = true;
        }

        if (!publishOnlyOnChange || changed)
        {
            _lastVA = toEmit;
            OnVAChanged?.Invoke(toEmit);
            _last = toEmit; _sent = true;
        }

        _wasIdle = idleNow;
    }

    Vector2 ReadStick()
    {
#if ENABLE_INPUT_SYSTEM
        var gp = Gamepad.current;
        if (gp != null)
            return useRightStick ? gp.rightStick.ReadValue() : gp.leftStick.ReadValue();
        return Vector2.zero;
#else
        float x = Input.GetAxis(useRightStick ? "RightStickX" : "Horizontal");
        float y = Input.GetAxis(useRightStick ? "RightStickY" : "Vertical");
        return new Vector2(x, y);
#endif
    }
}
