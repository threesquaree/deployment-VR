using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Press-to-talk speech capture backed by the local Whisper STT service.
///
/// Replaces Windows DictationRecognizer, which silently dropped 25-55% of
/// participant utterances (empty finals with cause=Complete; participants 15,
/// 19, 20). Replaying the saved session audio through faster-whisper recovered
/// every dropped utterance, so the mic was never the problem -- the recognizer
/// was. Here we slice the utterance out of the mic buffer GetEyeData is already
/// recording, write it to disk, and POST it to a local offline service.
///
/// Policy-light by design: this component never plays cues, never touches UI,
/// and never dispatches a turn itself. It reports through ISpeechCaptureHost so
/// RasaCommunication and RLCommunication each keep their existing cue,
/// telemetry and dispatch code verbatim -- that is what lets both arms share
/// one capture implementation without merging the two forks.
/// </summary>
public class WhisperSpeechCapture : MonoBehaviour
{
    public enum Failure
    {
        PressTooShort,
        NoMicClip,
        MicStopped,
        EmptyWindow,
        EncodeFailed,
        ServiceUnreachable,
        ServiceError,
        EmptyTranscript,
        MicSilent,
    }

    [SerializeField] private string sttBaseUrl = "http://127.0.0.1:5065";
    // P19 produced seven presses of 30-330ms (trigger misfires), and the
    // 2026-07-28 test run showed taps of 0.45-0.98s that contained no speech at
    // all. Measured on that run: silent presses had a median of 0.98s while the
    // shortest press carrying a real question was 1.43s -- so 1.0s discards taps
    // without ever truncating genuine speech.
    [SerializeField] private float minPressSeconds = 1.0f;
    // Visitors routinely start talking on the press edge, and stop just after
    // release; without padding the first/last syllable is clipped.
    [SerializeField] private float preRollSeconds = 0.30f;
    [SerializeField] private float postRollSeconds = 0.40f;
    [SerializeField] private float maxWindowSeconds = 30f;
    [SerializeField] private int sttTimeoutSeconds = 15;
    [SerializeField] private bool persistTurnAudio = true;
    // Below this peak the captured window is digital silence, i.e. the mic input
    // stream is dead -- NOT a quiet participant. Measured on the 2026-07-28 test
    // run: dead windows peak at 0.0004-0.003, room tone ~0.02, speech 0.10-0.54.
    [SerializeField] private float micSilenceThreshold = 0.01f;
    // Only a silent press held at least this long suggests a real mic fault; below
    // it, silence just means the visitor did not speak.
    [SerializeField] private float silentPressAlarmSeconds = 2.5f;

    private GetEyeData eyeData;
    private ISpeechCaptureHost host;

    private bool armed;
    private int pressSample = -1;
    private float pressRealtime = -1f;
    private int turnIndex;

    // One request at a time, but presses are never blocked: a turn that arrives
    // while another is transcribing is queued, so the participant can keep
    // talking and no utterance is lost to a busy flag.
    private readonly Queue<PendingTurn> pending = new Queue<PendingTurn>();
    private bool workerRunning;
    // Turns released by the trigger but not yet enqueued. CaptureTurn yields for the
    // post-roll before it can enqueue, so neither `pending` nor `armed` covers that
    // window; without this counter IsBusy goes briefly false between trigger release
    // and enqueue, which is exactly the gap a proactive turn slips through.
    private int capturesAssembling;

    private class PendingTurn
    {
        public int index;
        public byte[] wav;
        public string wavPath;
        public string objectName;
        public string aoiName;
        public float pressDuration;
        public float audioSeconds;
        public ISpeechCaptureHost host;
    }

    /// <summary>Find-or-create on the GetEyeData GameObject. Idempotent.</summary>
    public static WhisperSpeechCapture Attach(GetEyeData owner)
    {
        if (owner == null)
            return null;
        var c = owner.GetComponent<WhisperSpeechCapture>();
        if (c == null)
            c = owner.gameObject.AddComponent<WhisperSpeechCapture>();
        c.eyeData = owner;
        owner.RegisterSpeechCapture(c);
        return c;
    }

    public bool IsArmed => armed;

    /// <summary>True from the moment the trigger goes down until the last captured
    /// utterance has been transcribed and handed to the host. Wider than <see cref="IsArmed"/>
    /// on purpose: releasing the trigger does not mean the visitor's turn is over, it
    /// means transcription has started. Proactive turns (focus-change greetings, the
    /// silence timer) must stay quiet across that whole span, otherwise they race the
    /// STT round-trip and win, and the visitor's question is answered by a greeting.</summary>
    public bool IsBusy => armed || capturesAssembling > 0 || workerRunning || pending.Count > 0;

    // ---- trigger press -----------------------------------------------------

    public bool BeginCapture(ISpeechCaptureHost captureHost)
    {
        host = captureHost;

        if (eyeData == null)
            eyeData = FindObjectOfType<GetEyeData>();

        if (eyeData == null || !eyeData.IsMicCaptureActive)
        {
            Log("BeginCapture", "error=no_mic_clip");
            Fail(Failure.NoMicClip, "session not started or mic clip missing");
            return false;
        }

        if (!eyeData.IsMicHardwareRecording())
        {
            // Non-looping 2000s buffer: once it fills, Microphone stops and
            // GetPosition returns 0 forever. One 2026-07-22 session already hit
            // this exactly. GetEyeData rotates the segment; surface it here too.
            Log("BeginCapture", "error=mic_stopped");
            Fail(Failure.MicStopped, "microphone is not recording (buffer cap or device loss)");
            return false;
        }

        if (armed)
        {
            // Keep the ORIGINAL press sample: a duplicate down-event mid-utterance
            // must not truncate what the participant has already said.
            Log("BeginCapture", "warning=duplicate_press");
            return true;
        }

        pressSample = eyeData.GetMicSamplePosition();
        pressRealtime = Time.realtimeSinceStartup;
        armed = true;
        Log("BeginCapture", $"armed sample={pressSample}");
        return true;
    }

    // ---- trigger release ---------------------------------------------------

    public void EndCapture(string currentObjectName, string currentAoiName)
    {
        if (!armed)
        {
            Log("EndCapture", "warning=release_without_press");
            return;
        }
        armed = false;

        float pressDuration = Time.realtimeSinceStartup - pressRealtime;
        if (pressDuration < minPressSeconds)
        {
            // Silent drop, deliberately: a 30ms misfire is not a lost utterance,
            // and cueing it would train participants to distrust the cue.
            Log("EndCapture", $"skip=press_too_short press_s={Inv(pressDuration)} min_s={Inv(minPressSeconds)}");
            return;
        }

        // Snapshot the press position into a local: CaptureTurn yields for the
        // post-roll, and a new press during that window would otherwise overwrite
        // pressSample and make this turn slice from the wrong offset.
        capturesAssembling++;
        StartCoroutine(TrackAssembly(
            CaptureTurn(pressSample, currentObjectName, currentAoiName, pressDuration, host)));
    }

    /// <summary>Runs CaptureTurn and clears its assembling slot however it ends. CaptureTurn
    /// has several `yield break` exits; a decrement at each one would eventually be missed by
    /// an edit, and a counter stuck above zero latches IsBusy true and silences every
    /// proactive turn for the rest of the session.</summary>
    private IEnumerator TrackAssembly(IEnumerator capture)
    {
        try
        {
            yield return capture;
        }
        finally
        {
            capturesAssembling--;
        }
    }

    private IEnumerator CaptureTurn(int startedAtSample, string objectName, string aoiName,
                                    float pressDuration, ISpeechCaptureHost turnHost)
    {
        // Let the tail of the utterance land in the buffer before slicing.
        yield return new WaitForSecondsRealtime(postRollSeconds);

        int endSample = eyeData.GetMicSamplePosition();
        int freq = eyeData.MicFrequency;
        if (freq <= 0)
            freq = 44100;

        int start = startedAtSample - Mathf.RoundToInt(preRollSeconds * freq);
        if (start < 0)
            start = 0;

        int end = endSample;
        int clipSamples = eyeData.MicClip != null ? eyeData.MicClip.samples : 0;
        if (end > clipSamples)
            end = clipSamples;

        int frames = end - start;
        if (frames <= Mathf.RoundToInt(0.2f * freq))
        {
            Log("CaptureTurn", $"error=empty_window frames={frames} start={start} end={end}");
            FailFor(turnHost, Failure.EmptyWindow, $"window too small ({frames} frames)");
            yield break;
        }

        int maxFrames = Mathf.RoundToInt(maxWindowSeconds * freq);
        if (frames > maxFrames)
        {
            // Stuck trigger: keep the tail, which is where the speech will be.
            Log("CaptureTurn", $"warning=window_clamped orig_s={Inv(frames / (float)freq)}");
            start = end - maxFrames;
            frames = maxFrames;
        }

        byte[] wav;
        float peak = 0f, rms = 0f;
        try
        {
            wav = eyeData.EncodeMicWindowToWav(start, frames, out peak, out rms);
        }
        catch (Exception e)
        {
            Log("CaptureTurn", $"error=encode_failed msg={e.Message}");
            FailFor(turnHost, Failure.EncodeFailed, e.Message);
            yield break;
        }

        if (wav == null || wav.Length <= 44)
        {
            Log("CaptureTurn", "error=encode_failed msg=empty_payload");
            FailFor(turnHost, Failure.EncodeFailed, "encoder returned no data");
            yield break;
        }

        turnIndex++;
        var turn = new PendingTurn
        {
            index = turnIndex,
            wav = wav,
            objectName = objectName,
            aoiName = aoiName,
            pressDuration = pressDuration,
            audioSeconds = frames / (float)freq,
            host = turnHost,
        };

        // Persist BEFORE transcribing: if the service is down or wrong, the
        // utterance is still on disk and recoverable offline. This is the
        // guarantee the DictationRecognizer path never had.
        if (persistTurnAudio)
            turn.wavPath = PersistTurnAudio(turn);

        Log("CaptureTurn",
            $"captured turn={turn.index} audio_s={Inv(turn.audioSeconds)} bytes={wav.Length} " +
            $"press_s={Inv(pressDuration)} peak={Inv(peak)} rms={Inv(rms)} wav={turn.wavPath ?? "none"}");

        // A silent window means one of two very different things, and the press
        // duration is what separates them. On the 2026-07-28 test run silence
        // tracked press length almost perfectly (silent median 0.98s vs 4.28s for
        // real speech), i.e. the visitor tapped and said nothing -- NOT a fault.
        // A genuinely dead mic would produce silence regardless of how long the
        // trigger was held, so only a long silent press is worth alarming about.
        if (peak < micSilenceThreshold)
        {
            bool longEnoughToBeSpeech = pressDuration >= silentPressAlarmSeconds;
            Log("CaptureTurn",
                $"{(longEnoughToBeSpeech ? "error=mic_silent" : "info=no_speech_in_press")} " +
                $"turn={turn.index} peak={Inv(peak)} rms={Inv(rms)} press_s={Inv(pressDuration)} " +
                $"wav={turn.wavPath ?? "none"}");
            FailFor(turnHost,
                    longEnoughToBeSpeech ? Failure.MicSilent : Failure.EmptyTranscript,
                    longEnoughToBeSpeech
                        ? $"held {pressDuration:F1}s but captured silence (peak {Inv(peak)}) - check the headset mic"
                        : "no speech in press");
            yield break;
        }

        pending.Enqueue(turn);
        if (pending.Count > 3)
            Log("CaptureTurn", $"warning=stt_queue_backlog depth={pending.Count}");
        if (!workerRunning)
            StartCoroutine(Worker());
    }

    private string PersistTurnAudio(PendingTurn turn)
    {
        try
        {
            string dir = eyeData.SessionSpeechFolder();
            if (string.IsNullOrEmpty(dir))
                return null;
            Directory.CreateDirectory(dir);
            string path = Path.Combine(
                dir, $"utt_{turn.index:D4}_{DateTime.UtcNow:yyyyMMdd-HHmmss-fff}.wav");
            File.WriteAllBytes(path, turn.wav);
            return path;
        }
        catch (Exception e)
        {
            // Never abort the turn for a disk problem -- transcription can still
            // succeed and the participant still gets an answer.
            Log("PersistTurnAudio", $"warning=persist_failed msg={e.Message}");
            return null;
        }
    }

    // ---- transcription worker (strict FIFO keeps dialogue order) -----------

    private IEnumerator Worker()
    {
        workerRunning = true;
        // try/finally (legal around yield in an iterator): if a turn ever throws,
        // the flag must still clear or every later utterance would queue behind a
        // worker that is no longer running -- a silent, permanent speech outage.
        try
        {
            while (pending.Count > 0)
            {
                var turn = pending.Dequeue();
                yield return Transcribe(turn);
            }
        }
        finally
        {
            workerRunning = false;
        }
    }

    private IEnumerator Transcribe(PendingTurn turn)
    {
        string url = sttBaseUrl.TrimEnd('/') + "/transcribe";
        var sw = System.Diagnostics.Stopwatch.StartNew();

        using (var req = new UnityWebRequest(url, "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(turn.wav);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "audio/wav");
            req.timeout = sttTimeoutSeconds;

            yield return req.SendWebRequest();
            sw.Stop();

            string body = req.downloadHandler != null ? (req.downloadHandler.text ?? "") : "";

            if (req.result != UnityWebRequest.Result.Success)
            {
                Log("Transcribe",
                    $"error=stt_unreachable turn={turn.index} result={req.result} " +
                    $"code={req.responseCode} err={req.error} wav={turn.wavPath ?? "none"}");
                FailFor(turn.host, Failure.ServiceUnreachable,
                        $"{req.error} (audio kept at {turn.wavPath ?? "n/a"})");
                yield break;
            }

            if (req.responseCode < 200 || req.responseCode >= 300)
            {
                Log("Transcribe",
                    $"error=stt_server_error turn={turn.index} code={req.responseCode} body={Trim(body)}");
                FailFor(turn.host, Failure.ServiceError,
                        $"HTTP {req.responseCode} (audio kept at {turn.wavPath ?? "n/a"})");
                yield break;
            }

            SttResponse parsed = null;
            try
            {
                parsed = JsonUtility.FromJson<SttResponse>(body);
            }
            catch (Exception e)
            {
                Log("Transcribe", $"error=stt_bad_json turn={turn.index} msg={e.Message} body={Trim(body)}");
            }

            string text = parsed != null ? (parsed.text ?? "").Trim() : "";

            if (string.IsNullOrWhiteSpace(text))
            {
                // Participant pressed but said nothing usable. Distinct from a
                // service fault -- the host counts these separately so a quiet
                // visitor is never misreported as broken infrastructure.
                Log("Transcribe",
                    $"info=empty_transcript turn={turn.index} audio_s={Inv(turn.audioSeconds)} " +
                    $"rtt_ms={sw.Elapsed.TotalMilliseconds:F0}");
                FailFor(turn.host, Failure.EmptyTranscript, "no speech detected");
                yield break;
            }

            string userAsrEndTs = DateTime.UtcNow.ToString("o");
            Log("Transcribe",
                $"transcribed turn={turn.index} chars={text.Length} audio_s={Inv(turn.audioSeconds)} " +
                $"stt_latency_ms={(parsed != null ? parsed.latency_ms : 0f):F0} " +
                $"rtt_ms={sw.Elapsed.TotalMilliseconds:F0} text='{Trim(text)}'");

            if (turn.host != null)
                turn.host.OnSpeechCaptured(text, turn.objectName, turn.aoiName, userAsrEndTs);
        }
    }

    // ---- session boundary --------------------------------------------------

    public void OnSessionEnding(string reason)
    {
        armed = false;
        if (pending.Count > 0)
            Log("OnSessionEnding", $"warning=pending_turns_dropped depth={pending.Count} reason={reason}");
    }

    // ---- helpers -----------------------------------------------------------

    private void Fail(Failure f, string detail) => FailFor(host, f, detail);

    private void FailFor(ISpeechCaptureHost h, Failure f, string detail)
    {
        if (h != null)
            h.OnSpeechCaptureFailed(f, detail);
    }

    /// <summary>Format a float with a '.' decimal point regardless of machine
    /// locale. This box runs a comma-decimal locale, which silently emitted
    /// "press_s=3,73" into the debug log and broke every downstream parser.</summary>
    private static string Inv(float v) =>
        v.ToString("F3", System.Globalization.CultureInfo.InvariantCulture);

    private static string Trim(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        s = s.Replace("\n", " ").Replace("\r", " ");
        return s.Length > 160 ? s.Substring(0, 160) + "..." : s;
    }

    private void Log(string ev, string data)
    {
        if (host != null)
            host.LogSpeechDebug("WhisperSpeechCapture." + ev, data);
        else
            Debug.Log($"[WhisperSpeechCapture] {ev} | {data}");
    }

    [Serializable]
    private class SttResponse
    {
        public string text;
        public float latency_ms;
        public float audio_s;
        public float rtf;
        public string error;
    }
}

/// <summary>
/// Implemented by each agent arm. Keeps dispatch, cues and telemetry in the arm
/// so the capture component stays backend-only.
/// </summary>
public interface ISpeechCaptureHost
{
    void OnSpeechCaptured(string text, string objectName, string aoiName, string userAsrEndTs);
    void OnSpeechCaptureFailed(WhisperSpeechCapture.Failure failure, string detail);
    void LogSpeechDebug(string @event, string data);
}
