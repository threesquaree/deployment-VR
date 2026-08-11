"""
Validate faster-whisper on REAL study audio before we wire it into Unity.

- loads the model (times cold load)
- transcribes a full session audio.wav (quality + real-time-factor)
- extracts one short mid-session clip and times a WARM transcribe, i.e. the
  latency a live press-to-talk turn would actually see
- prints the Windows-dictation ground truth from turns.jsonl for comparison

Usage:
  stt/.venv/Scripts/python.exe stt/benchmark.py <session_dir>
"""

import io
import json
import sys
import time
import wave

from faster_whisper import WhisperModel

import os
MODEL = os.environ.get("STT_MODEL", "small.en")
DEVICE = os.environ.get("STT_DEVICE", "cuda")
COMPUTE = os.environ.get("STT_COMPUTE", "int8_float16")


def slice_wav(path, start_s, dur_s):
    """Return WAV bytes for [start_s, start_s+dur_s) using stdlib wave (PCM)."""
    with wave.open(path, "rb") as w:
        fr = w.getframerate()
        w.setpos(int(start_s * fr))
        frames = w.readframes(int(dur_s * fr))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as o:
            o.setnchannels(w.getnchannels())
            o.setsampwidth(w.getsampwidth())
            o.setframerate(fr)
            o.writeframes(frames)
        return buf.getvalue(), w.getnframes() / float(fr)


def transcribe(model, audio):
    t0 = time.time()
    segments, info = model.transcribe(
        io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio,
        language="en", beam_size=1, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, (time.time() - t0), float(getattr(info, "duration", 0.0) or 0.0)


def main(session_dir):
    wav = f"{session_dir}/audio.wav"
    turns = f"{session_dir}/turns.jsonl"

    print(f"[load] {MODEL} on {DEVICE}/{COMPUTE} ...")
    t0 = time.time()
    model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    print(f"[load] done in {time.time() - t0:.1f}s\n")

    # --- warm single short clip = the live per-turn latency we care about ---
    clip, total_s = slice_wav(wav, start_s=min(60, 0), dur_s=6.0)
    transcribe(model, clip)                       # warm-up (first call pays init)
    text, secs, _ = transcribe(model, clip)
    print(f"[warm 6s clip] latency={secs*1000:.0f}ms  text={text!r}\n")

    # --- full session: quality + real-time factor ---
    print(f"[full] transcribing {wav} ({total_s:.0f}s of audio) ...")
    full_text, full_secs, dur = transcribe(model, wav)
    rtf = full_secs / dur if dur else 0
    print(f"[full] {dur:.0f}s audio in {full_secs:.1f}s  RTF={rtf:.3f}\n")
    print("=== WHISPER full transcript ===")
    print(full_text, "\n")

    # --- ground truth from Windows dictation for side-by-side ---
    try:
        print("=== Windows dictation (turns.jsonl user_text) ===")
        for line in open(turns, encoding="utf-8"):
            r = json.loads(line)
            if r.get("record_type") == "interaction" and (r.get("user_text") or "").strip():
                print(f"  T{r.get('turn_number')}: {r['user_text']!r}")
    except FileNotFoundError:
        print("(no turns.jsonl)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
