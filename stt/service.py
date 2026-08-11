"""
Local offline speech-to-text service (faster-whisper) for the museum study.

Replacement for the Windows online DictationRecognizer, which silently drops
25-55% of participant utterances (empty finals with cause=Complete, sometimes
DictationComplete cause=UnknownError). Proven by replaying saved session audio:
the mic audio is fine, the recognizer is the weak link. This service runs fully
offline so there is no online-speech backend to rate-limit, wedge, or fail.

Endpoints
---------
GET  /health      -> {"status":"ok","model":..,"device":..,"compute":..,"ready":true}
POST /transcribe  -> body = raw WAV bytes (Content-Type: audio/wav)
                     or multipart form field "file"
                  -> {"text": "...", "latency_ms": .., "audio_s": .., "rtf": ..,
                      "error": ""}

Every response carries the full key set (empty "error" on success) so a Unity
JsonUtility DTO can deserialize both success and failure without branching.

Config via environment variables
--------------------------------
STT_MODEL     model name or path       (default: small.en)
STT_DEVICE    cuda | cpu | auto        (default: auto, falls back to cpu)
STT_COMPUTE   ct2 compute type         (default: int8_float16 on cuda, int8 on cpu)
STT_LANG      language code            (default: en; empty to auto-detect)
STT_PORT      HTTP port                (default: 5065)
STT_BEAM      beam size                (default: 1 -> greedy, lowest latency)
STT_LOG       request audit log path   (default: stt/logs/stt_requests.jsonl)

Run:  stt/.venv/Scripts/python.exe stt/service.py
"""

import io
import json
import os
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

# --- CUDA DLL discovery (must run BEFORE ctranslate2 is imported) -----------
# Python 3.8+ ignores PATH when resolving dependencies of extension modules, so
# the pip-installed NVIDIA DLLs (cublas64_12.dll etc.) are invisible to
# CTranslate2 unless their directories are registered explicitly. Harmless when
# the packages are absent -- we simply fall back to CPU below.
def _register_nvidia_dll_dirs():
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not base.is_dir():
        return
    dirs = [str(d) for d in base.glob("*/bin")]
    if not dirs:
        return
    # PATH is the load-bearing part: CTranslate2 resolves cuBLAS with a plain
    # LoadLibrary, which consults PATH but ignores add_dll_directory. Registering
    # both covers either loading style across CT2 versions.
    os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        for d in dirs:
            try:
                os.add_dll_directory(d)
            except OSError:
                pass


_register_nvidia_dll_dirs()

from flask import Flask, request, jsonify  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402


def _env_int(name, default):
    """Never let a typo'd env var kill the service at startup."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        print(f"[stt] WARNING: bad {name}, using {default}", flush=True)
        return int(default)


MODEL_NAME = os.environ.get("STT_MODEL", "small.en")
DEVICE_PREF = os.environ.get("STT_DEVICE", "auto").lower()
COMPUTE_PREF = os.environ.get("STT_COMPUTE", "")
LANG = os.environ.get("STT_LANG", "en") or None
BEAM = _env_int("STT_BEAM", 1)
PORT = _env_int("STT_PORT", 5065)
LOG_PATH = Path(os.environ.get("STT_LOG", Path(__file__).parent / "logs" / "stt_requests.jsonl"))


def _cuda_plausible():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _load_model():
    """Load on the preferred device, degrading to CPU rather than dying.

    get_cuda_device_count() only needs the NVIDIA *driver*, so it reports a GPU
    even when cuBLAS is missing -- the failure then surfaces from WhisperModel()
    itself. Constructing inside try/except is what keeps a missing DLL from
    taking the service down mid-study.
    """
    attempts = []
    if DEVICE_PREF == "cuda" or (DEVICE_PREF == "auto" and _cuda_plausible()):
        attempts.append(("cuda", COMPUTE_PREF or "int8_float16"))
    attempts.append(("cpu", COMPUTE_PREF if DEVICE_PREF == "cpu" and COMPUTE_PREF else "int8"))

    last_err = None
    for device, compute in attempts:
        try:
            print(f"[stt] loading model={MODEL_NAME} device={device} compute={compute} ...", flush=True)
            t0 = time.time()
            m = WhisperModel(MODEL_NAME, device=device, compute_type=compute)
            # Construction alone proves nothing: on a GPU box missing cuBLAS the
            # model loads happily and only fails at the first encode. Exercise the
            # encoder HERE so a broken device is rejected at startup, not mid-study.
            _exercise_encoder(m)
            print(f"[stt] model loaded + verified in {time.time() - t0:.1f}s on {device}", flush=True)
            return m, device, compute
        except Exception as e:  # noqa: BLE001 - any load failure should degrade, not kill
            last_err = e
            print(f"[stt] {device} FAILED: {e}", flush=True)
            if device == "cuda":
                print("[stt] falling back to CPU (pip install nvidia-cublas-cu12 to enable GPU)", flush=True)
    raise RuntimeError(f"could not load model on any device: {last_err}")


def _tone_wav(seconds=1.2, rate=16000, freq=300):
    """Non-silent warm-up audio.

    A silent clip is useless here: VAD strips it before any encoder pass runs, so
    the warm-up completes without ever touching cuBLAS -- which is exactly how a
    GPU build that loads fine but cannot infer slipped through as 'ready'.
    """
    import math
    import struct

    frames = bytearray()
    for i in range(int(rate * seconds)):
        v = int(12000 * math.sin(2 * math.pi * freq * (i / rate)))
        frames += struct.pack("<h", v)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _exercise_encoder(m):
    """Force a real encoder+decoder pass. vad_filter=False is essential -- with VAD
    on, a clip can be trimmed to nothing and the model is never actually invoked."""
    segments, _ = m.transcribe(
        io.BytesIO(_tone_wav()), language=LANG, beam_size=1, vad_filter=False
    )
    list(segments)  # generator is lazy; consume it or nothing executes


# Load AFTER the warm-up helpers exist -- _load_model() verifies the device by
# running a real encode, so it depends on them.
model, DEVICE, COMPUTE = _load_model()


def transcribe_bytes(wav_bytes):
    """Return (text, audio_seconds). VAD trims press-to-talk silence.

    condition_on_previous_text=False and the no-speech thresholds suppress
    Whisper's habit of emitting "Thank you."/"Bye." on near-silent clips, which
    would otherwise be dispatched to the agent as a real participant turn.
    """
    segments, info = model.transcribe(
        io.BytesIO(wav_bytes),
        language=LANG,
        beam_size=BEAM,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    # duration_after_vad is the honest denominator for RTF (duration is pre-trim).
    # Compare against None explicitly: a fully-VAD-trimmed clip reports 0.0, and
    # `or` would silently swap that for the untrimmed length.
    audio_s = getattr(info, "duration_after_vad", None)
    if audio_s is None:
        audio_s = getattr(info, "duration", 0.0) or 0.0
    return text, float(audio_s)


app = Flask(__name__)


def _audit(**fields):
    """Append-only request log. Without it a silent quality regression would be
    as invisible as the DictationRecognizer failure this service replaces."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fields["ts"] = datetime.now(timezone.utc).isoformat()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(fields, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_wav_bytes():
    """Accept either a multipart 'file' field or a raw body of WAV bytes."""
    if "file" in request.files:
        return request.files["file"].read()
    return request.get_data(cache=False)


def _reply(text="", latency_ms=0.0, audio_s=0.0, rtf=0.0, error="", code=200):
    return jsonify(
        text=text,
        latency_ms=round(latency_ms, 1),
        audio_s=round(audio_s, 2),
        rtf=round(rtf, 3),
        error=error,
    ), code


@app.get("/health")
def health():
    return jsonify(
        status="ok", ready=True, model=MODEL_NAME, device=DEVICE, compute=COMPUTE
    )


@app.post("/transcribe")
def transcribe():
    wav = _read_wav_bytes()
    if not wav:
        _audit(event="empty_body", bytes=0)
        return _reply(error="empty_body", code=400)

    t0 = time.time()
    try:
        text, audio_s = transcribe_bytes(wav)
    except Exception as e:  # noqa: BLE001 - report decode/infer failure to caller
        _audit(event="error", bytes=len(wav), error=str(e))
        return _reply(error=str(e), code=500)

    latency_ms = (time.time() - t0) * 1000.0
    rtf = (latency_ms / 1000.0) / audio_s if audio_s > 0 else 0.0
    _audit(
        event="transcribe",
        bytes=len(wav),
        audio_s=round(audio_s, 2),
        latency_ms=round(latency_ms, 1),
        rtf=round(rtf, 3),
        text=text,
    )
    return _reply(text=text, latency_ms=latency_ms, audio_s=audio_s, rtf=rtf)


if __name__ == "__main__":
    # threaded=False: one Whisper inference at a time (single VR client, and the
    # model is not safe for concurrent transcribe calls).
    print(f"[stt] serving on http://127.0.0.1:{PORT}  (audit -> {LOG_PATH})", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=False)
