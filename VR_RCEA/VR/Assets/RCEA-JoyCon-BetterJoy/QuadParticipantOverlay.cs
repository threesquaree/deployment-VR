using UnityEngine;
using TMPro;

public class QuadParticipantOverlay : MonoBehaviour
{
    [Header("Refs")]
    public RCEADataLogger logger;     // assign your logger
    public TMP_Text overlayText;      // the TextMeshPro on/near the Quad

    [Header("UI")]
    [TextArea]
    public string message = "Enter participant number";

    bool _lastVisible;

    void Reset()
    {
        overlayText = GetComponent<TMP_Text>();
    }

    void Start()
    {
        if (!overlayText)
            Debug.LogWarning("QuadParticipantOverlay: overlayText not assigned.");

        // Initialize message
        if (overlayText) overlayText.text = message;

        UpdateVisibility(force: true);
    }

    void Update()
    {
        UpdateVisibility();
    }

    void UpdateVisibility(bool force = false)
    {
        bool shouldShow = (logger == null) || !logger.HasParticipant;

        if (force || shouldShow != _lastVisible)
        {
            if (overlayText) overlayText.gameObject.SetActive(shouldShow);
            _lastVisible = shouldShow;
        }
    }

    // Optional: call this if something external changes the participant and you want an immediate refresh.
    public void Refresh() => UpdateVisibility(force: true);
}
