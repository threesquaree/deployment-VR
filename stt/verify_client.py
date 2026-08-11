"""
Bench verification for the STT service -- mimics exactly what Unity will do.

Unity posts RAW WAV BYTES with Content-Type: audio/wav (UploadHandlerRaw), so
this client does the same via stdlib urllib. No headset, no VR, no risk: it
replays real recorded study audio and short utterance-length slices through the
live HTTP endpoint and checks latency + the failure matrix.

Usage:
  stt/.venv/Scripts/python.exe stt/verify_client.py <session_dir> [--port 5065]
"""

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path


def post_wav(url, wav_bytes, timeout=60):
    req = urllib.request.Request(
        url, data=wav_bytes, headers={"Content-Type": "audio/wav"}, method="POST"
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8")), (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8")), (time.time() - t0) * 1000


def slice_wav(path, start_s, dur_s):
    with wave.open(str(path), "rb") as w:
        fr = w.getframerate()
        start = min(int(start_s * fr), w.getnframes())
        w.setpos(start)
        frames = w.readframes(int(dur_s * fr))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as o:
            o.setnchannels(w.getnchannels())
            o.setsampwidth(w.getsampwidth())
            o.setframerate(fr)
            o.writeframes(frames)
        return buf.getvalue(), w.getnframes() / float(fr)


def loudest_windows(path, win_s=5.0, n=3):
    """Return start offsets (s) of the n loudest non-overlapping windows."""
    import array

    with wave.open(str(path), "rb") as w:
        fr, nfr = w.getframerate(), w.getnframes()
        step = int(fr * win_s)
        scores = []
        for i in range(0, max(0, nfr - step), step):
            w.setpos(i)
            a = array.array("h")
            a.frombytes(w.readframes(step))
            if not a:
                continue
            # mean |amplitude| is enough to separate speech from room tone
            scores.append((sum(abs(x) for x in a) / len(a), i / float(fr)))
    scores.sort(reverse=True)
    return [round(s, 1) for _, s in scores[:n]]


def silent_wav(seconds=2.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    ap.add_argument("--port", type=int, default=5065)
    args = ap.parse_args()

    base = f"http://127.0.0.1:{args.port}"
    url = base + "/transcribe"
    wav_path = Path(args.session_dir) / "audio.wav"
    failures = []

    print("=" * 70)
    print("1. HEALTH")
    try:
        with urllib.request.urlopen(base + "/health", timeout=10) as r:
            print("   ", r.read().decode())
    except Exception as e:
        print(f"    FAIL: {e}")
        sys.exit(1)

    print("=" * 70)
    print("2. FULL SESSION over HTTP")
    if not wav_path.exists():
        print(f"    SKIP: no {wav_path}")
    else:
        data = wav_path.read_bytes()
        status, body, ms = post_wav(url, data)
        print(f"    status={status} wall={ms:.0f}ms audio_s={body.get('audio_s')} "
              f"server_latency_ms={body.get('latency_ms')} rtf={body.get('rtf')}")
        text = body.get("text", "")
        print(f"    chars={len(text)}")
        print(f"    head: {text[:220]}")
        if status != 200 or not text:
            failures.append("full-session transcription returned no text")

    print("=" * 70)
    print("3. UTTERANCE-LENGTH LATENCY (what a live turn pays)")
    if wav_path.exists():
        # Pick the loudest 5s windows: arbitrary offsets usually land in the long
        # silences between turns and would measure nothing.
        for start_s in loudest_windows(wav_path, win_s=5.0, n=3):
            clip, _ = slice_wav(wav_path, start_s, 5.0)
            status, body, ms = post_wav(url, clip)
            flag = "" if ms < 1500 else "   <-- SLOW"
            print(f"    @{start_s:6.0f}s  wall={ms:7.0f}ms  text={body.get('text','')[:60]!r}{flag}")
            if ms > 3000:
                failures.append(f"utterance latency {ms:.0f}ms exceeds 3s")
            if not body.get("text"):
                failures.append(f"loud window @{start_s:.0f}s produced no text")

    print("=" * 70)
    print("4. FAILURE MATRIX")
    status, body, _ = post_wav(url, b"")
    ok = status == 400 and body.get("error") == "empty_body"
    print(f"    empty body      -> {status} {body.get('error')!r}  {'OK' if ok else 'UNEXPECTED'}")
    if not ok:
        failures.append("empty body did not return 400/empty_body")

    status, body, _ = post_wav(url, b"this is not a wav file at all")
    ok = status == 500 and body.get("error")
    print(f"    garbage bytes   -> {status} error={str(body.get('error'))[:50]!r}  {'OK' if ok else 'UNEXPECTED'}")
    if not ok:
        failures.append("garbage bytes did not return a 500 error")

    status, body, ms = post_wav(url, silent_wav())
    ok = status == 200 and body.get("text", "") == ""
    print(f"    silence (2s)    -> {status} text={body.get('text','')!r} ({ms:.0f}ms)  "
          f"{'OK - no hallucination' if ok else 'UNEXPECTED'}")
    if not ok:
        failures.append(f"silence produced text: {body.get('text')!r}")

    # every response must carry the full key set for Unity's JsonUtility DTO
    missing = {"text", "latency_ms", "audio_s", "rtf", "error"} - set(body)
    print(f"    schema keys     -> {'OK - uniform' if not missing else f'MISSING {missing}'}")
    if missing:
        failures.append(f"response missing keys {missing}")

    print("=" * 70)
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
