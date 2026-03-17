using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Video;

public class TrainingSequencePlayer : MonoBehaviour
{
    [Header("Setup")]
    public RCEADataLogger logger;
    public VideoPlayer videoPlayer;
    public List<VideoClip> clips = new List<VideoClip>();
    public float pauseBetweenClips = 1.0f;   // seconds

    [Header("Keys")]
    public KeyCode startKey = KeyCode.T;
    public KeyCode pauseKey = KeyCode.Space;
    public KeyCode nextKey = KeyCode.RightArrow;
    public KeyCode prevKey = KeyCode.LeftArrow;
    public KeyCode stopKey = KeyCode.S;

    int _index = -1;
    bool _sequenceActive;
    bool _waitingBetween;

  

    void Awake()
    {
        if (!videoPlayer) videoPlayer = GetComponent<VideoPlayer>();
        videoPlayer.playOnAwake = false;
        videoPlayer.isLooping = false;
        videoPlayer.loopPointReached += OnClipEnded;

        // keep playback tied to realtime (don’t run faster than the clip)
        videoPlayer.waitForFirstFrame = true;
        videoPlayer.skipOnDrop = true;           // drop frames if needed instead of speeding up
        videoPlayer.playbackSpeed = 1f;

        
    }





    void Update()
    {
        if (Input.GetKeyDown(startKey))
        {
            if (!_sequenceActive) StartSequence();
            logger?.LogKey(startKey, "DOWN");
        }

        if (!_sequenceActive) return;

        if (Input.GetKeyDown(pauseKey))
        {
            TogglePause();
            logger?.LogKey(pauseKey, videoPlayer.isPaused ? "PAUSE" : "RESUME");
        }

        if (Input.GetKeyDown(nextKey))
        {
            Next();
            logger?.LogKey(nextKey, "NEXT");
        }

        if (Input.GetKeyDown(prevKey))
        {
            Previous();
            logger?.LogKey(prevKey, "PREV");
        }

        if (Input.GetKeyDown(stopKey))
        {
            FinishSequence();
            logger?.LogKey(stopKey, "STOP");
        }
    }

    public void StartSequence()
    {
        if (clips == null || clips.Count == 0)
        {
            Debug.LogWarning("[TrainingSequencePlayer] No clips assigned.");
            return;
        }

        // Make sure logging is running & participant set
        if (logger)
        {
            if (!logger.HasParticipant)
            {
                Debug.LogWarning("[TrainingSequencePlayer] Participant empty; not starting.");
                return;
            }
            if (!logger.IsRunning) logger.StartLoggingIfReady();
            logger.LogSequenceStart();
        }

        _sequenceActive = true;
        _index = -1;
        Next(); // loads first
    }

    public void TogglePause()
    {
        if (!videoPlayer.clip) return;

        if (videoPlayer.isPaused) videoPlayer.Play();
        else videoPlayer.Pause();
    }

    public void Next()
    {
        if (!_sequenceActive) return;

        // if a clip is running, mark end before switching
        if (videoPlayer.clip)
        {
            logger?.LogVideoEnd(videoPlayer.clip.name);
        }

        _index++;
        if (_index >= clips.Count)
        {
            FinishSequence();
            return;
        }

        StartCoroutine(PlayWithPause(clips[_index]));
    }

    public void Previous()
    {
        if (!_sequenceActive) return;

        if (videoPlayer.clip)
        {
            logger?.LogVideoEnd(videoPlayer.clip.name);
        }

        _index = Mathf.Max(0, _index - 1);
        StartCoroutine(PlayWithPause(clips[_index]));
    }

    System.Collections.IEnumerator PlayWithPause(VideoClip clip)
    {
        if (_waitingBetween) yield break;
        _waitingBetween = true;

        videoPlayer.Stop();
        yield return new WaitForSecondsRealtime(pauseBetweenClips);

        videoPlayer.clip = clip;
        logger?.LogVideoStart(clip.name);
        videoPlayer.Play();

        _waitingBetween = false;
    }

    void OnClipEnded(VideoPlayer vp)
    {
        // natural end of a clip -> step to next
        logger?.LogVideoEnd(vp.clip ? vp.clip.name : "");
        Next();
    }

    public void FinishSequence()
    {
        if (!_sequenceActive) return;

        videoPlayer.Stop();
        _sequenceActive = false;
        logger?.LogSequenceEnd();
        // (do not StopLogging here; you might want to keep sampling after)
    }
}
