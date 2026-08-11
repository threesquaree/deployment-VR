using UnityEngine;

/// <summary>
/// Participant-facing audio feedback for speech capture, shared by the baseline
/// (RasaCommunication) and RL (RLCommunication) arms.
///
/// Why this exists: when the Windows dictation recognizer returns nothing usable
/// the utterance is discarded and never sent to the agent. Before this cue that
/// failure was completely silent -- the participant heard nothing back and had no
/// way to know they needed to repeat themselves. Pilot session
/// ca_18c13318..._2026-07-20T12-32-32 lost three utterances that way.
///
/// The tone is generated procedurally so this needs no art asset and no Editor
/// wiring -- dropping the script into the project is enough.
///
/// The agent's own voice comes from server-side TTS (Unity never plays agent
/// audio), so a local descending two-tone cue cannot be mistaken for the agent
/// speaking.
/// </summary>
public static class SpeechFeedback
{
    private const int SampleRate = 44100;
    private const float ToneSeconds = 0.18f;
    private const float ToneHighHz = 620f;
    private const float ToneLowHz = 440f;
    private const float ToneVolume = 0.5f;

    private static AudioClip notCapturedClip;

    /// <summary>
    /// Plays a short descending "didn't catch that" cue. Safe to call when the
    /// host is null or already destroyed. Must be called from the main thread.
    /// </summary>
    public static void PlayNotCapturedCue(MonoBehaviour host)
    {
        if (host == null)
            return;

        AudioSource source = ResolveSource(host);
        if (source == null)
            return;

        AudioClip clip = GetNotCapturedClip();
        if (clip == null)
            return;

        source.PlayOneShot(clip, ToneVolume);
    }

    private static AudioSource ResolveSource(MonoBehaviour host)
    {
        // Reuse an existing AudioSource if the host already has one; PlayOneShot
        // does not disturb whatever clip that source is configured with.
        AudioSource source = host.GetComponent<AudioSource>();
        if (source == null)
        {
            source = host.gameObject.AddComponent<AudioSource>();
            source.playOnAwake = false;
            source.loop = false;
            // 2D so the cue is audible regardless of where the visitor is looking
            // or standing when the capture fails.
            source.spatialBlend = 0f;
        }
        return source;
    }

    private static AudioClip GetNotCapturedClip()
    {
        if (notCapturedClip != null)
            return notCapturedClip;

        int sampleCount = Mathf.RoundToInt(SampleRate * ToneSeconds);
        if (sampleCount <= 0)
            return null;

        int halfway = sampleCount / 2;
        // Short linear fades at both ends and across the pitch change, so the cue
        // does not click.
        int fade = Mathf.Max(1, sampleCount / 12);

        var samples = new float[sampleCount];
        float phase = 0f;
        for (int i = 0; i < sampleCount; i++)
        {
            float frequency = i < halfway ? ToneHighHz : ToneLowHz;
            // Accumulate phase rather than computing sin(2*pi*f*t) directly, so the
            // waveform stays continuous across the high->low transition.
            phase += 2f * Mathf.PI * frequency / SampleRate;

            float envelope = 1f;
            if (i < fade)
                envelope = (float)i / fade;
            else if (i >= sampleCount - fade)
                envelope = (float)(sampleCount - 1 - i) / fade;

            samples[i] = Mathf.Sin(phase) * envelope;
        }

        notCapturedClip = AudioClip.Create("SpeechNotCapturedCue", sampleCount, 1, SampleRate, false);
        notCapturedClip.SetData(samples, 0);
        return notCapturedClip;
    }
}
