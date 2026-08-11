"""
Shared Piper TTS helper for the VR museum study.

Used by BOTH study conditions so the voice is guaranteed identical:
  - RL agent:  RL_new\\runtime_service\\service.py (LocalTTS)
  - Baseline:  CA\\improved\\actions.py (speak)

Design constraints honored here:
  - Python 3.8 compatible, standard library only (no pip installs in either venv).
  - Engine is the standalone piper.exe (MIT) in tts\\piper\\ — no Python deps.
  - Voice + speed come from tts\\tts_config.json: ONE source of truth for both agents.
  - synthesize() keeps a persistent piper.exe process (model loaded once,
    ~0.2-0.5 s per utterance) and falls back to a one-shot invocation if the
    persistent process dies.
  - play() is blocking (winsound), so callers can take accurate
    agent_tts_start_ts / agent_tts_end_ts around it.

IMPORTANT (study validity): once participants start, do not change the voice
or length_scale in tts_config.json — both conditions must speak identically
for the whole study.
"""

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

_TTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPER_EXE = os.path.join(_TTS_DIR, "piper", "piper.exe")
_VOICES_DIR = os.path.join(_TTS_DIR, "voices")
_CONFIG_PATH = os.path.join(_TTS_DIR, "tts_config.json")
_TMP_DIR = os.path.join(_TTS_DIR, "tmp")

_SYNTH_TIMEOUT_SEC = 20.0

_lock = threading.Lock()
_proc = None            # persistent piper process
_stdout_queue = None    # lines from the persistent process's stdout


def _iso_now_ms():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_config():
    """Read tts_config.json. Raises if missing/invalid — callers treat any
    exception from this module as 'fall back to pyttsx3'."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    voice = cfg["voice"]
    model_path = os.path.join(_VOICES_DIR, voice + ".onnx")
    if not os.path.exists(model_path):
        raise FileNotFoundError("Piper voice model not found: %s" % model_path)
    return {
        "voice": voice,
        "model_path": model_path,
        "length_scale": float(cfg.get("length_scale", 1.0)),
        "enabled": bool(cfg.get("enabled", True)),
    }


def _reader_thread(proc, out_queue):
    try:
        for line in iter(proc.stdout.readline, b""):
            out_queue.put(line.decode("utf-8", errors="replace").strip())
    except Exception:
        pass
    finally:
        out_queue.put(None)  # EOF sentinel


def _start_persistent(cfg):
    global _proc, _stdout_queue
    _stop_persistent()
    if not os.path.isdir(_TMP_DIR):
        os.makedirs(_TMP_DIR)
    cmd = [
        _PIPER_EXE,
        "--model", cfg["model_path"],
        "--length_scale", str(cfg["length_scale"]),
        "--json-input",
        "--output_dir", _TMP_DIR,
    ]
    _proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(_PIPER_EXE),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _stdout_queue = queue.Queue()
    t = threading.Thread(target=_reader_thread, args=(_proc, _stdout_queue),
                         name="PiperStdoutReader", daemon=True)
    t.start()


def _stop_persistent():
    global _proc, _stdout_queue
    if _proc is not None:
        try:
            _proc.kill()
        except Exception:
            pass
    _proc = None
    _stdout_queue = None


def prewarm():
    """Start the persistent piper process so the first utterance is fast.
    Safe to call at module import of the integrating runtime."""
    with _lock:
        cfg = load_config()
        if _proc is None or _proc.poll() is not None:
            _start_persistent(cfg)


def _synthesize_persistent(text, cfg):
    global _proc, _stdout_queue
    if _proc is None or _proc.poll() is not None:
        _start_persistent(cfg)
    out_path = os.path.join(_TMP_DIR, "utt_%s.wav" % uuid.uuid4().hex)
    request = json.dumps({"text": text, "output_file": out_path})
    _proc.stdin.write((request + "\n").encode("utf-8"))
    _proc.stdin.flush()
    deadline = time.time() + _SYNTH_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            line = _stdout_queue.get(timeout=max(0.1, deadline - time.time()))
        except queue.Empty:
            break
        if line is None:  # process died
            break
        # piper prints the output wav path when synthesis completes
        if out_path in line or line.endswith(".wav"):
            if os.path.exists(out_path) and os.path.getsize(out_path) > 44:
                return out_path
    raise RuntimeError("Persistent piper synthesis failed or timed out")


def _synthesize_oneshot(text, cfg):
    if not os.path.isdir(_TMP_DIR):
        os.makedirs(_TMP_DIR)
    out_path = os.path.join(_TMP_DIR, "utt_%s.wav" % uuid.uuid4().hex)
    cmd = [
        _PIPER_EXE,
        "--model", cfg["model_path"],
        "--length_scale", str(cfg["length_scale"]),
        "--output_file", out_path,
    ]
    completed = subprocess.run(
        cmd,
        input=text.encode("utf-8"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(_PIPER_EXE),
        timeout=_SYNTH_TIMEOUT_SEC,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) <= 44:
        raise RuntimeError("One-shot piper synthesis failed (rc=%s)" % completed.returncode)
    return out_path


def synthesize(text):
    """Text -> wav path. Persistent process first, one-shot fallback.
    Raises on total failure (caller falls back to pyttsx3)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")
    with _lock:
        cfg = load_config()
        try:
            return _synthesize_persistent(text, cfg)
        except Exception:
            _stop_persistent()
            return _synthesize_oneshot(text, cfg)


def play(wav_path):
    """Blocking playback on the Windows default output device."""
    import winsound
    winsound.PlaySound(wav_path, winsound.SND_FILENAME)


def speak(text):
    """Synthesize then play. Returns (started_at_iso, ended_at_iso), where
    started_at is stamped at PLAYBACK start (not synthesis start) so
    agent_tts_start_ts keeps meaning 'audio began'."""
    wav_path = synthesize(text)
    try:
        started_at = _iso_now_ms()
        play(wav_path)
        ended_at = _iso_now_ms()
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass
    return started_at, ended_at


if __name__ == "__main__":
    # Self-test: synthesize + play one sentence, report timing.
    import sys
    sample = "Welcome to the museum. This portrait was painted in sixteen fifty four."
    if len(sys.argv) > 1:
        sample = " ".join(sys.argv[1:])
    print("config:", load_config())
    t0 = time.time()
    prewarm()
    print("prewarm: %.2fs" % (time.time() - t0))
    t1 = time.time()
    wav = synthesize(sample)
    print("synthesize: %.2fs -> %s (%d bytes)" % (time.time() - t1, wav, os.path.getsize(wav)))
    start, end = None, None
    t2 = time.time()
    start = _iso_now_ms()
    play(wav)
    end = _iso_now_ms()
    print("playback: %.2fs  started_at=%s ended_at=%s" % (time.time() - t2, start, end))
    os.remove(wav)
    print("SELF-TEST OK")
