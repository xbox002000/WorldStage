"""Deterministic synthesised score and effects: the same plan and seed give the same WAV, byte for byte.

No samples, no downloads, no network. Only sine partials, filtered noise and envelopes. All noise comes from
the raw output of the PCG64 bit generator, whose stream numpy keeps frozen; the numpy version is still recorded
in the audio toolchain fingerprint.
"""
from __future__ import annotations

import io
import wave

import numpy as np

from contracts.packet import AudioCue, AudioPlan
from world.rng import derive_seed

SR = 48000  # the renderer's own rate, so nothing is resampled
SYNTH_VERSION = "1"
TARGET_RMS_DB = -19.0  # overall loudness target
CEILING = 0.95  # soft limiter ceiling
ROOTS_HZ = (98.0, 110.0, 130.81, 146.83, 164.81)  # G2 A2 C3 D3 E3: the channel's key, chosen per episode

MOODS = ("calm", "warm", "cold", "uneasy", "tense", "clash", "title")
# mood -> (semitone above root, amplitude) partials of the pad
CHORDS: dict[str, tuple[tuple[int, float], ...]] = {
    "title": ((0, 0.50), (7, 0.40), (12, 0.30)),
    "calm": ((0, 0.45), (7, 0.35), (12, 0.25)),
    "warm": ((0, 0.40), (4, 0.30), (7, 0.30), (14, 0.15)),
    "cold": ((0, 0.30), (5, 0.25), (10, 0.20), (19, 0.10)),
    "uneasy": ((0, 0.40), (3, 0.30), (6, 0.30)),
    "tense": ((0, 0.40), (1, 0.20), (6, 0.30), (10, 0.20)),
    "clash": ((0, 0.40), (1, 0.30), (6, 0.30), (11, 0.20)),
}
TREMOLO = {"calm": (0.15, 0.25), "warm": (0.2, 0.2), "cold": (0.1, 0.3), "uneasy": (0.35, 0.45),
           "tense": (0.5, 0.35), "clash": (0.7, 0.4), "title": (0.12, 0.2)}
PULSE_BPM = {"tense": 60, "clash": 92}
BASS_MOODS = {"calm", "warm", "uneasy", "tense", "clash", "title"}
MUSIC_GAIN = (0.16, 0.24)  # (floor, span): gain = floor + span * intensity
SFX_GAIN = 0.55


def audio_toolchain() -> str:
    return f"synth-{SYNTH_VERSION};numpy-{np.__version__}"


def _noise(n: int, seed: int) -> np.ndarray:
    """Uniform white noise in [-1, 1) from PCG64's raw stream (stable across numpy versions)."""
    raw = np.random.PCG64(seed).random_raw(n)
    return (raw >> np.uint64(11)).astype(np.float64) * (2.0 / 9007199254740992.0) - 1.0


def _lowpass(x: np.ndarray, width: int) -> np.ndarray:
    """Moving average: a cheap, deterministic low-pass."""
    if width <= 1:
        return x
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.empty_like(x)
    out[width - 1:] = (c[width:] - c[:-width]) / width
    out[: width - 1] = c[1:width] / np.arange(1, width)
    return out


def _sin_env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = min(n, int(attack * SR)), min(n, int(release * SR))
    env = np.ones(n)
    if a:
        env[:a] = np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if r:
        env[n - r:] *= np.cos(np.linspace(0, np.pi / 2, r)) ** 2
    return env


def _pan(mono: np.ndarray, pan: float) -> np.ndarray:
    theta = (pan + 1.0) * np.pi / 4  # -1 hard left .. +1 hard right, constant power
    return np.stack([mono * np.cos(theta), mono * np.sin(theta)], axis=1)


def _place(bus: np.ndarray, block: np.ndarray, start: int) -> None:
    start = max(0, start)
    if start >= len(bus):
        return
    end = min(len(bus), start + len(block))
    bus[start:end] += block[: end - start]


# -- music ---------------------------------------------------------------------------------------------------------
def _music(mood: str, duration: float, root: float, seed: int, intensity: float) -> np.ndarray:
    n = max(1, int(duration * SR))
    t = np.arange(n) / SR
    rate, depth = TREMOLO[mood]
    out = np.zeros((n, 2))
    for k, (semi, amp) in enumerate(CHORDS[mood]):
        f = 2 * root * 2 ** (semi / 12)  # the pad sits an octave above the bass so small speakers carry it
        phase = (derive_seed(seed, k, "phase", mood) % 6283) / 1000.0
        lfo = 1.0 - depth * (0.5 + 0.5 * np.sin(2 * np.pi * rate * t + phase))
        voice = np.sin(2 * np.pi * f * t + phase) + 0.3 * np.sin(2 * np.pi * 2 * f * t + 1.3 * phase)
        if mood == "warm":
            voice += 0.15 * np.sin(2 * np.pi * 3 * f * t)
        if mood == "uneasy" and k == 0:  # a slightly detuned twin makes the root beat against itself
            voice += np.sin(2 * np.pi * (f + 2.5) * t)
        out += _pan(amp * lfo * voice, ((k % 3) - 1) * 0.45)
    if mood in BASS_MOODS:
        out += _pan(0.35 * np.sin(2 * np.pi * (root / 2) * t), 0.0)
    if mood in PULSE_BPM:  # a heartbeat: thump, then a softer second thump
        beat = 60.0 / PULSE_BPM[mood]
        for i in range(int(duration / beat) + 1):
            for offset, gain in ((0.0, 0.9), (0.22, 0.5)):
                start = int((i * beat + offset) * SR)
                m = int(0.28 * SR)
                if start < n:
                    tt = np.arange(min(m, n - start)) / SR
                    base = np.sin(2 * np.pi * (78 - 26 * tt) * tt)
                    thump = (base + 0.6 * np.sin(2 * np.pi * 2 * (78 - 26 * tt) * tt)) * np.exp(-tt * 16)
                    out[start:start + len(tt)] += _pan(gain * (0.4 + 0.6 * intensity) * thump, 0.0)
    if mood == "clash":  # a slow riser over the whole segment
        f = 220 + 700 * (t / max(duration, 1e-6)) ** 2
        out += _pan(0.18 * intensity * np.sin(2 * np.pi * np.cumsum(f) / SR), 0.0)
    return out * _sin_env(n, 0.5, 0.5)[:, None]


# -- effects -------------------------------------------------------------------------------------------------------
def _sfx_whoosh(seed: int, duration: float) -> np.ndarray:
    n = int(duration * SR)
    noise = _noise(n, seed)
    x = np.linspace(0, 1, n)
    bright = _lowpass(noise, 3)
    mid = _lowpass(noise, 14)
    dark = _lowpass(noise, 60)
    w_mid = np.sin(np.pi * x)  # brightness rises then falls
    body = bright * (0.6 * w_mid) + mid * (0.7 * (1 - abs(2 * x - 1))) + dark * 0.6 * (1 - w_mid)
    return body * np.sin(np.pi * x) ** 2


def _sfx_hit(seed: int, level: str) -> np.ndarray:
    length = {"low": 0.35, "mid": 0.6, "high": 1.0}[level]
    n = int(length * SR)
    tt = np.arange(n) / SR
    f = 55 + 130 * np.exp(-tt * 14)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * (9 if level != "high" else 5))
    body = body + 0.5 * np.sin(2 * np.pi * np.cumsum(2 * f) / SR) * np.exp(-tt * 12)
    click = _lowpass(_noise(n, seed), 6) * np.exp(-tt * 60) * 0.6
    return {"low": 0.6, "mid": 0.85, "high": 1.0}[level] * (body + click)


def _sfx_snatch(seed: int) -> np.ndarray:
    n = int(0.28 * SR)
    tt = np.arange(n) / SR
    chirp = np.sin(2 * np.pi * np.cumsum(900 * np.exp(-tt * 9) + 180) / SR) * np.exp(-tt * 12)
    return 0.6 * chirp + 0.5 * _lowpass(_noise(n, seed), 2) * np.exp(-tt * 40)


def _sfx_glass(seed: int) -> np.ndarray:
    n = int(1.1 * SR)
    tt = np.arange(n) / SR
    vib = 1 + 0.003 * np.sin(2 * np.pi * 5.5 * tt)
    return (0.5 * np.sin(2 * np.pi * 1760 * tt * vib) + 0.35 * np.sin(2 * np.pi * 2637 * tt * vib)
            + 0.2 * np.sin(2 * np.pi * 4186 * tt)) * np.exp(-tt * 4.5) * (1 - np.exp(-tt * 200))


def _sfx_reveal(seed: int) -> np.ndarray:
    n = int(1.2 * SR)
    tt = np.arange(n) / SR
    riser = np.sin(2 * np.pi * np.cumsum(180 + 1100 * (tt / 1.2) ** 2) / SR) * (tt / 1.2) ** 1.5
    swell = _lowpass(_noise(n, seed), 5) * (tt / 1.2) ** 2 * 0.7
    out = (0.55 * riser + swell) * np.where(tt < 0.9, 1.0, 0.0)
    boom = _sfx_hit(seed + 1, "high")
    tail = np.zeros(n)
    s = int(0.9 * SR)
    tail[s:] = boom[: n - s]
    return out + tail


def _sfx_flip(seed: int) -> np.ndarray:
    n = int(0.7 * SR)
    tt = np.arange(n) / SR
    swell = _lowpass(_noise(n, seed), 4)[::-1] * np.exp(-tt[::-1] * 5) * 0.8
    thump = np.sin(2 * np.pi * 48 * tt) * np.exp(-np.maximum(tt - 0.55, 0) * 25) * (tt > 0.55)
    return swell + 0.9 * thump


def _sfx_tick(seed: int) -> np.ndarray:
    n = int(0.03 * SR)
    tt = np.arange(n) / SR
    return 0.25 * np.sin(2 * np.pi * 2200 * tt) * np.exp(-tt * 140)


def _sfx_title_hit(seed: int) -> np.ndarray:
    n = int(1.6 * SR)
    tt = np.arange(n) / SR
    return (np.sin(2 * np.pi * 62 * tt) * np.exp(-tt * 2.6) + 0.5 * np.sin(2 * np.pi * 124 * tt) * np.exp(-tt * 3.2)
            + 0.6 * _lowpass(_noise(n, seed), 30) * np.exp(-tt * 3.5))


def _sfx(cue: AudioCue, seed: int) -> np.ndarray | None:
    name = cue.name
    if name == "whoosh":
        return _sfx_whoosh(seed, cue.duration or 0.7)
    if name.startswith("hit_"):
        return _sfx_hit(seed, name.split("_", 1)[1])
    return {"snatch": _sfx_snatch, "glass": _sfx_glass, "reveal": _sfx_reveal, "flip": _sfx_flip, "tick": _sfx_tick,
            "title_hit": _sfx_title_hit}.get(name, lambda s: None)(seed)


def _ambience(name: str, duration: float, seed: int) -> np.ndarray:
    n = max(1, int(duration * SR))
    noise = _noise(n, seed)
    tt = np.arange(n) / SR
    if name == "rain":
        hiss = noise - _lowpass(noise, 8)  # keep the top: rain is bright
        return 0.10 * hiss * (0.8 + 0.2 * np.sin(2 * np.pi * 0.3 * tt))
    if name == "fog":
        return 0.09 * _lowpass(noise, 120)
    if name == "wind":
        return 0.09 * _lowpass(noise, 40) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.12 * tt))
    if name == "night":
        return 0.05 * np.sin(2 * np.pi * 55 * tt) + 0.03 * np.sin(2 * np.pi * 82.4 * tt)
    return np.zeros(n)


# -- mixing --------------------------------------------------------------------------------------------------------
def synthesize(plan: AudioPlan, total_seconds: float, seed_material: str) -> np.ndarray:
    """Render the whole plan to a stereo float array (N, 2). `seed_material` fixes every random choice."""
    n = int(round(total_seconds * SR))
    key = derive_seed(seed_material, 0, "audio", "key")
    root = ROOTS_HZ[key % len(ROOTS_HZ)]
    bus = np.zeros((n, 2))
    for i, cue in enumerate(sorted(plan.cues, key=lambda c: (c.t, c.kind, c.name))):
        seed = derive_seed(seed_material, i, "audio", f"{cue.kind}:{cue.name}")
        start = int(cue.t * SR)
        if cue.kind == "music" and cue.name.startswith("mood:"):
            mood = cue.name.split(":", 1)[1]
            if mood in CHORDS:
                pad = 0.25  # segments overlap by half a second so they cross-fade
                block = _music(mood, cue.duration + 2 * pad, root, seed, cue.intensity)
                gain = MUSIC_GAIN[0] + MUSIC_GAIN[1] * cue.intensity
                _place(bus, block * gain, start - int(pad * SR))
        elif cue.kind == "sfx":
            mono = _sfx(cue, seed)
            if mono is not None:
                pan = ((seed % 1000) / 1000.0 - 0.5) * 0.8
                _place(bus, _pan(mono * SFX_GAIN * (0.4 + 0.6 * cue.intensity), pan), start)
        elif cue.kind == "ambience":
            block = _ambience(cue.name, cue.duration, seed)
            _place(bus, _pan(block * _sin_env(len(block), 0.6, 0.6), 0.0), start)

    if n == 0:
        return bus
    rms = float(np.sqrt(np.mean(bus ** 2)))
    if rms > 1e-9:
        bus *= min(6.0, max(0.3, 10 ** (TARGET_RMS_DB / 20) / rms))
    bus = np.tanh(bus / CEILING) * CEILING  # soft limiter: no clipping, no surprises
    fade = min(n, int(0.05 * SR)), min(n, int(1.0 * SR))
    bus[: fade[0]] *= np.linspace(0, 1, fade[0])[:, None]
    bus[n - fade[1]:] *= np.linspace(1, 0, fade[1])[:, None]
    return bus


def to_wav_bytes(samples: np.ndarray) -> bytes:
    pcm = np.clip(np.round(samples * 32767.0), -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
