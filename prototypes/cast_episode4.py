"""PROTOTYPE: one short clip in the "cast" look (vector characters in vector places, dialogue, voices), built from the
real events of Experiment A, episode 4. Not part of the pipeline: it shows what the presentation layer could be.

    python prototypes/cast_episode4.py

Needs out/expA (Experiment A's output) and GEMINI_API_KEY (free tier: Gemini TTS answers, image, music and video
generation do not, their free quota is 0). The lines are written by hand here; the real pipeline would have a model
write them from the beat's facts. Voices are cached under out/prototype/tts.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from agent.llm import load_api_key  # noqa: E402
from audio.synth import SR, synthesize  # noqa: E402
from contracts.packet import AudioCue, AudioPlan  # noqa: E402
from render.cast.cast_html import build_project  # noqa: E402
from render.hyperframes_backend import CLI, GSAP, HyperFramesBackend, _env, _run  # noqa: E402

OUT = ROOT / "out" / "prototype"
TTS_MODEL = "gemini-3.8-flash-tts"


# -- voices: Gemini TTS, one line per request, cached by (voice, style, text) ------------------------------------------
def speak(text: str, voice: str, style: str, tag: str) -> tuple[np.ndarray, int]:
    key = hashlib.sha256(f"{TTS_MODEL}|{voice}|{style}|{text}".encode()).hexdigest()[:16]
    cache = OUT / "tts" / f"{tag}_{key}.npy"
    if cache.exists():
        return np.load(cache), 24000
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=load_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    part = types.Part(text=text, speech_metadata=types.SpeechMetadata(style=style))  # the style is not read aloud
    resp = client.models.generate_content(
        model=TTS_MODEL, contents=[types.Content(role="user", parts=[part])],
        config=types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
    data = resp.candidates[0].content.parts[0].inline_data.data
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as w:
            raw, sr = w.readframes(w.getnframes()), w.getframerate()
    else:
        raw, sr = data, 24000
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    loud = np.where(np.abs(x) > 0.012)[0]  # trim the silence around the line
    if len(loud):
        x = x[max(0, loud[0] - int(0.05 * sr)):min(len(x), loud[-1] + int(0.05 * sr))]
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, x)
    return x, sr


def main() -> None:
    pk = json.loads((ROOT / "out/expA/episodes/day_04/packet.json").read_text(encoding="utf-8"))

    def hue_of(pid: str) -> float:
        lock = pk["continuity_locks"]["characters"][pid]["identity_lock"]
        return float(re.search(r"hsl\((\d+(?:\.\d+)?)", next(v for v in lock if v.startswith("avatar_color="))).group(1))

    name_of = {c["id"]: c["name"] for s in pk["shots"] for c in s["characters"]}
    cast = {p: {"name": name_of[p], "hue": hue_of(p)} for p in ("lan", "ning")}
    nodes = [{"id": l["id"], "name": l["name"], "x": l["x"], "y": l["y"]} for l in pk["map"]["locations"]]
    edges = pk["map"]["edges"]

    voices_of = {"lan": "Leda", "ning": "Kore"}
    A_TH, A_SP = "我心裡還受著傷，給不了她好臉色。", "……妳也在啊。"
    B_SP, C_SP = "妳剛剛那是什麼態度？", "妳之前那樣質問我，現在換我了。"
    a_th = speak(A_TH, voices_of["lan"], "soft, low and breathy, introspective and a little sad, slower than normal, like an inner monologue", "A_th")
    a_sp = speak(A_SP, voices_of["lan"], "cold and flat, quiet, avoiding eye contact, natural conversational pace", "A_sp")
    b_sp = speak(B_SP, voices_of["ning"], "angry and confrontational, sharp and clipped, tense but controlled, natural conversational pace", "B_sp")
    c_sp = speak(C_SP, voices_of["lan"], "angry and bitter, low and tight, deliberate but natural conversational pace", "C_sp")
    dur = lambda v: len(v[0]) / v[1]  # noqa: E731

    # -- the timeline, from the real durations ---------------------------------------------------------------------------
    TITLE, MAP = 2.6, 2.2
    stamp = lambda day, clock, weather: {"day": day, "clock": clock, "placeName": "咖啡店", "weather": weather}  # noqa: E731
    WIDE = {"focus": [540, 1000], "zoom": 1.12, "push": 0.05}
    close = lambda x: {"focus": [x, 1080], "zoom": 2.0, "push": 0.06}  # noqa: E731
    LX, RX = 320, 770
    A0 = TITLE + MAP
    t_th = 1.3
    t_sp = t_th + dur(a_th) + 0.55
    t_re = t_sp + dur(a_sp) + 0.45
    A_DUR = t_re + 1.7
    B0 = A0 + A_DUR
    u_sp = 1.15
    u_re = u_sp + dur(b_sp) + 0.3
    B_DUR = u_re + 1.7
    C0 = B0 + B_DUR
    v_sp = 1.15
    v_re = v_sp + dur(c_sp) + 0.3
    C_DUR = v_re + 1.9
    TOTAL = round(C0 + C_DUR + 0.6, 2)
    r2 = lambda v: round(v + 0.1, 2)  # noqa: E731
    script = {"title": "阿蘭與阿寧", "tagline": "第 3 天起", "recap": "", "title_seconds": TITLE, "total": TOTAL,
              "leads": ["lan", "ning"], "cast": cast, "shots": [
        {"kind": "map", "start": TITLE, "dur": MAP, "place": "cafe", "map": {"nodes": nodes, "edges": edges}, "stamp": stamp(3, "18:17", "霧")},
        {"kind": "scene", "start": A0, "dur": A_DUR, "place": "cafe", "time": "dusk", "weather": "fog", "stamp": stamp(3, "18:17", "霧"),
         "stage": [{"who": "lan", "x": LX, "look": 1, "feel": "distant", "pose": "crossed"}, {"who": "ning", "x": RX, "look": -1, "feel": "hurt", "pose": "down"}],
         "cuts": [{"t": 0, **WIDE}, {"t": 1.1, **close(LX)}, {"t": t_re - 0.05, **close(RX)}],
         "beats": [{"t": t_th, "who": "lan", "feel": "distant", "line": {"text": A_TH, "dur": r2(dur(a_th)), "thought": True}},
                   {"t": t_sp, "who": "lan", "feel": "cold", "line": {"text": A_SP, "dur": r2(dur(a_sp))}},
                   {"t": t_re, "who": "ning", "feel": "hurt"}]},
        {"kind": "scene", "start": B0, "dur": B_DUR, "place": "cafe", "time": "dusk", "weather": "fog", "stamp": stamp(3, "18:27", "霧"),
         "stage": [{"who": "ning", "x": LX, "look": 1, "feel": "angry", "pose": "hips"}, {"who": "lan", "x": RX, "look": -1, "feel": "shocked", "pose": "down"}],
         "cuts": [{"t": 0, **WIDE}, {"t": 1.0, **close(LX)}, {"t": u_re - 0.05, **close(RX)}],
         "beats": [{"t": u_sp, "who": "ning", "feel": "angry", "pose": "point", "shake": 10, "line": {"text": B_SP, "dur": r2(dur(b_sp))}},
                   {"t": u_re, "who": "lan", "feel": "angry"}]},
        {"kind": "scene", "start": C0, "dur": C_DUR, "place": "cafe", "time": "day", "weather": "rain", "stamp": stamp(4, "12:13", "雨"),
         "stage": [{"who": "lan", "x": LX, "look": 1, "feel": "angry", "pose": "hips"}, {"who": "ning", "x": RX, "look": -1, "feel": "hurt", "pose": "crossed"}],
         "cuts": [{"t": 0, **WIDE}, {"t": 1.0, **close(LX)}, {"t": v_re - 0.05, **close(RX)}],
         "beats": [{"t": v_sp, "who": "lan", "feel": "angry", "shake": 8, "line": {"text": C_SP, "dur": r2(dur(c_sp))}},
                   {"t": v_re, "who": "ning", "feel": "hurt"}]},
    ]}

    # -- the sound: score and effects from the synth, voices on top, the music ducked under them ---------------------------
    cues = [AudioCue(0.0, "music", "mood:title", TITLE, 0.35), AudioCue(0.3, "sfx", "title_hit", 0.0, 0.7),
            AudioCue(TITLE, "music", "mood:calm", MAP, 0.3), AudioCue(TITLE + 0.5, "sfx", "tick", 0.0, 0.3), AudioCue(TITLE, "sfx", "whoosh", 0.7, 0.4)]
    for t0, d, mood, inten, amb in ((A0, A_DUR, "cold", 0.4, "fog"), (B0, B_DUR, "tense", 0.7, "fog"), (C0, C_DUR, "clash", 0.6, "rain")):
        cues += [AudioCue(t0, "music", f"mood:{mood}", d, inten), AudioCue(t0, "sfx", "whoosh", 0.7, 0.5), AudioCue(t0, "ambience", amb, d, 0.4)]
    cues += [AudioCue(A0 + 1.1, "sfx", "whoosh", 0.4, 0.3), AudioCue(A0 + t_re - 0.05, "sfx", "whoosh", 0.4, 0.3),
             AudioCue(B0 + u_sp, "sfx", "hit_mid", 0.0, 0.7), AudioCue(B0 + 1.0, "sfx", "whoosh", 0.4, 0.3), AudioCue(B0 + u_re - 0.05, "sfx", "whoosh", 0.4, 0.3),
             AudioCue(C0 + v_sp, "sfx", "hit_low", 0.0, 0.6), AudioCue(C0 + 1.0, "sfx", "whoosh", 0.4, 0.3), AudioCue(C0 + v_re - 0.05, "sfx", "whoosh", 0.4, 0.3)]
    score = synthesize(AudioPlan(sorted(cues, key=lambda c: (c.t, c.kind, c.name))), TOTAL, "cast-proto-1")

    def to48(v):
        x, sr = v
        return np.interp(np.linspace(0, len(x) - 1, int(len(x) * SR / sr)), np.arange(len(x)), x).astype(np.float64)

    n = score.shape[0]
    duck, bus = np.ones(n), np.zeros((n, 2))
    for t, v, pan, gain in ((A0 + t_th, a_th, -0.15, 0.75), (A0 + t_sp, a_sp, -0.15, 1.0), (B0 + u_sp, b_sp, 0.15, 1.0), (C0 + v_sp, c_sp, -0.15, 1.0)):
        x = to48(v) * gain
        a = int(t * SR)
        b = min(n, a + len(x))
        bus[a:b, 0] += x[: b - a] * ((1 - max(0, pan)) * 0.5 + 0.5)
        bus[a:b, 1] += x[: b - a] * ((1 + min(0, pan)) * 0.5 + 0.5)
        ramp, rel = int(0.15 * SR), int(0.45 * SR)
        lo, hi = max(0, a - ramp), min(n, b + rel)
        env = np.full(hi - lo, 0.42)
        env[: min(ramp, len(env))] = np.linspace(1, 0.42, min(ramp, len(env)))
        env[max(0, len(env) - rel):] = np.linspace(0.42, 1, len(env) - max(0, len(env) - rel))
        duck[lo:hi] = np.minimum(duck[lo:hi], env)
    mix = score * duck[:, None] + bus * 1.6

    def wav_bytes(m):
        pcm = np.clip(np.round(m * 32767.0), -32768, 32767).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()

    def lufs(m):
        tmp = OUT / "mix_tmp.wav"
        tmp.write_bytes(wav_bytes(m))
        r = subprocess.run([str(ROOT / "tools/ffmpeg/bin/ffmpeg"), "-nostats", "-i", str(tmp), "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True)
        return float(re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", r.stderr)[-1])

    mix = mix * 10 ** ((-16.0 - lufs(mix)) / 20)  # short-form target loudness
    mix = np.tanh(mix / 0.95) * 0.95

    project = OUT / "project"
    build_project(script, project, GSAP, wav_bytes(mix))
    (OUT / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    mp4 = OUT / "cast_prototype_ep4.mp4"
    _run([str(CLI), "render", str(project), "-o", str(mp4), "-q", "looks", "-f", "30", "--quiet"], _env(HyperFramesBackend(lambda h: None).chrome_path()))
    print("rendered", mp4, TOTAL, "s")


if __name__ == "__main__":
    main()
