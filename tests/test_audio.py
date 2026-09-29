from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from audio.backend import SynthAudioBackend
from audio.synth import CHORDS, SR, _sfx, audio_toolchain, synthesize, to_wav_bytes
from contracts.packet import AudioCue, AudioPlan
from narrative.audio_plan import compile_audio_plan
from render.hyperframes_backend import FFMPEG_DIR, HyperFramesBackend
from tests.world_fixture import compile_all

FFMPEG = FFMPEG_DIR / "ffmpeg.exe"


def plan(*cues):
    return AudioPlan(list(cues))


MUSIC = AudioCue(0.0, "music", "mood:tense", 6.0, 0.7)


def energy(x, start, end):
    return float(np.mean(x[int(start * SR):int(end * SR)] ** 2))


class SynthTests(unittest.TestCase):
    def test_same_plan_and_seed_give_identical_bytes_and_other_seeds_differ(self):
        p = plan(MUSIC, AudioCue(2.0, "sfx", "whoosh", 0.7, 0.5), AudioCue(3.0, "ambience", "rain", 2.0, 0.4))
        a, b = to_wav_bytes(synthesize(p, 6.0, "s1")), to_wav_bytes(synthesize(p, 6.0, "s1"))
        self.assertEqual(hashlib.sha256(a).digest(), hashlib.sha256(b).digest())
        self.assertNotEqual(a, to_wav_bytes(synthesize(p, 6.0, "s2")))

    def test_output_is_a_valid_stereo_wav_of_the_right_length(self):
        x = synthesize(plan(MUSIC), 6.0, "s")
        with wave.open(io.BytesIO(to_wav_bytes(x))) as w:
            self.assertEqual((w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()), (2, SR, 2, 6 * SR))

    def test_levels_are_sane_and_never_clip(self):
        loud = plan(MUSIC, AudioCue(1.0, "sfx", "hit_high", 0.0, 1.0), AudioCue(1.0, "sfx", "reveal", 0.0, 1.0),
                    AudioCue(1.0, "sfx", "title_hit", 0.0, 1.0))
        x = synthesize(loud, 6.0, "s")
        self.assertTrue(np.all(np.isfinite(x)))
        self.assertLessEqual(float(np.abs(x).max()), 0.96)
        rms_db = 20 * np.log10(np.sqrt(np.mean(x ** 2)))
        self.assertTrue(-24 < rms_db < -14, rms_db)

    def test_an_empty_plan_is_silence_not_an_error(self):
        x = synthesize(plan(), 2.0, "s")
        self.assertEqual(x.shape, (2 * SR, 2))
        self.assertEqual(float(np.abs(x).max()), 0.0)

    def test_an_effect_raises_the_energy_where_it_is_placed(self):
        base = synthesize(plan(MUSIC), 6.0, "s")
        hit = synthesize(plan(MUSIC, AudioCue(3.0, "sfx", "hit_high", 0.0, 1.0)), 6.0, "s")
        ratio_base = energy(base, 3.0, 3.6) / energy(base, 0.6, 2.6)
        ratio_hit = energy(hit, 3.0, 3.6) / energy(hit, 0.6, 2.6)
        self.assertGreater(ratio_hit, ratio_base * 1.5)

    def test_moods_sound_different_and_all_are_defined(self):
        spectra = {}
        for mood in CHORDS:
            x = synthesize(plan(AudioCue(0.0, "music", f"mood:{mood}", 4.0, 0.6)), 4.0, "s")
            spectra[mood] = np.abs(np.fft.rfft(x[:, 0]))[:4000]
        moods = list(spectra)
        for i, a in enumerate(moods):
            for b in moods[i + 1:]:
                corr = float(np.corrcoef(spectra[a], spectra[b])[0, 1])
                self.assertLess(corr, 0.995, (a, b))

    def test_cues_outside_the_episode_are_ignored_safely(self):
        x = synthesize(plan(MUSIC, AudioCue(50.0, "sfx", "hit_low", 0.0, 0.5), AudioCue(5.9, "sfx", "reveal", 0.0, 1.0)), 6.0, "s")
        self.assertEqual(x.shape[0], 6 * SR)

    def test_unknown_effects_are_skipped(self):
        self.assertIsNone(_sfx(AudioCue(0.0, "sfx", "kazoo", 0.0, 0.5), 1))
        synthesize(plan(MUSIC, AudioCue(1.0, "sfx", "kazoo", 0.0, 0.5)), 3.0, "s")

    def test_toolchain_names_the_synthesiser_and_numpy(self):
        self.assertIn("numpy-", audio_toolchain())
        self.assertIn("synth-", audio_toolchain())


class AudioPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = compile_all()

    def test_music_covers_the_whole_episode_without_gaps(self):
        for p in self.packets:
            music = [c for c in p.audio_plan.cues if c.kind == "music"]
            self.assertEqual(music[0].t, 0.0)
            for a, b in zip(music, music[1:]):
                self.assertAlmostEqual(a.t + a.duration, b.t, places=2)
            self.assertAlmostEqual(music[-1].t + music[-1].duration, p.qa.total_seconds, places=2)

    def test_every_cue_is_inside_the_episode_and_known_to_the_synth(self):
        for p in self.packets:
            self.assertEqual(list(p.audio_plan.cues), sorted(p.audio_plan.cues, key=lambda c: (c.t, c.kind, c.name)))
            for c in p.audio_plan.cues:
                self.assertTrue(0 <= c.t <= p.qa.total_seconds, c)
                if c.kind == "music":
                    self.assertIn(c.name.split(":", 1)[1], CHORDS)
                elif c.kind == "sfx":
                    self.assertIsNotNone(_sfx(c, 1), c.name)
            self.assertTrue(p.qa.require_audio)

    def test_story_beats_get_their_own_sounds(self):
        names = {c.name for p in self.packets for c in p.audio_plan.cues}
        self.assertTrue({"title_hit", "whoosh", "tick"} <= names)
        self.assertTrue(names & {"snatch", "glass", "reveal", "flip"})  # the fixture week has drama

    def test_the_plan_reacts_to_the_beat(self):
        from contracts.scene_spec import Beat, Participant, Place
        from narrative.compiler import BEATS  # noqa: F401
        beat = Beat(event_id=1, event_type="confront", variant="lie_exposed", location=Place("cafe", "Cafe", 0, 0), day=1,
                    clock="12:00", weather="rain", participants=[Participant("a", "actor"), Participant("b", "target")],
                    prop=None, thoughts=[], motivation=None, trust_flipped=True, importance=0.95)
        import dataclasses
        from contracts.packet import Lighting
        shot = dataclasses.replace(self.packets[0].shots[0], lighting=Lighting("night", "rain"))
        p = compile_audio_plan([beat], [shot], 2.0, 10.0)
        names = [c.name for c in p.cues]
        for expected in ("mood:clash", "reveal", "hit_high", "flip", "rain", "night"):
            self.assertIn(expected, names)

    def test_audio_plans_are_deterministic(self):
        again = compile_all()
        self.assertEqual([p.audio_plan for p in self.packets], [p.audio_plan for p in again])


class BackendTests(unittest.TestCase):
    def test_the_score_is_pinned_in_the_render_request(self):
        packet = compile_all()[0]
        backend = HyperFramesBackend(lambda h: packet)
        request = backend.make_request(packet)
        wav = SynthAudioBackend(lambda h: packet).score_bytes(packet, 0)
        self.assertEqual(request.asset_hashes["score"], "sha256:" + hashlib.sha256(wav).hexdigest())
        self.assertEqual(request.parameters["score"], "synth")
        self.assertIn("synth-", request.toolchain.audio)
        self.assertNotEqual(request.request_hash, backend.make_request(packet, seed=1).request_hash)  # another seed, another score

    def test_the_audio_backend_writes_the_same_file_as_it_hashes(self):
        packet = compile_all()[0]
        audio = SynthAudioBackend(lambda h: packet)
        backend = HyperFramesBackend(lambda h: packet)
        with tempfile.TemporaryDirectory() as tmp:
            out = audio.render(backend.make_request(packet), Path(tmp) / "score.wav")
            self.assertEqual(out.read_bytes(), audio.score_bytes(packet, 0))
        self.assertTrue(audio.capabilities().deterministic and not audio.capabilities().remote)

    @unittest.skipUnless(FFMPEG.exists(), "local ffmpeg not installed")
    def test_a_real_episode_score_has_broadcast_loudness(self):
        packet = compile_all()[0]
        wav = SynthAudioBackend(lambda h: packet).score_bytes(packet, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.wav"
            path.write_bytes(wav)
            out = subprocess.run([str(FFMPEG), "-v", "info", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        line = next(l for l in out.splitlines() if l.strip().startswith("I:"))
        lufs = float(line.split()[1])
        self.assertTrue(-23 < lufs < -12, lufs)  # short-form video sits around -14 to -16


if __name__ == "__main__":
    unittest.main()
