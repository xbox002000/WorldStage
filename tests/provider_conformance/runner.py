"""The provider conformance runner: a visual provider, a fixed set of shots from a real world, and a verdict.

    python -m tests.provider_conformance.runner --provider mock-clip [--scale 0.25] [--json report.json]

For each sample (samples.json: one ShotRequest of a real event, see builder.py) the runner

  1. asks the capability registry whether the provider may take the job at all (its features, its limits, and the budget:
     the default policy allows only free providers, so a paid model is skipped with the reason, never run);
  2. makes the RenderRequest the pipeline would make, and calls provider.generate once, at the sample's own seed (no repair:
     what is measured is the provider, not the repair loop);
  3. judges the take with production/shot_qa.diagnose: format, duration, frozen frames, black frames, provider error;
  4. for a provider that says it is deterministic, generates the first sample again and compares the bytes.

A provider passes when every sample is made and none has a failure, and the determinism check (if it applies) holds. A sample
the provider cannot take is `skipped`, which is reported and does not pass (`allow_skipped` is for a model that is only meant
for some of the shots). Passing is what lets a new model go live; the upstream layers are not edited for it.

The suite judges what shot_qa can measure. It does not judge whether a face is the right face or the slap reads as a slap: that
needs a vision inspector (IDENTITY_DRIFT and the like are in contracts/repair.py, with no detector yet) and a person looking.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from capability.registry import CapabilityRegistry
from contracts.backends import ShotRequest
from contracts.base import from_dict, hash_without
from contracts.bible import Bible
from contracts.capability import Policy, Requirement
from contracts.render_request import Take, make_request
from production.provenance import file_sha256
from production.shot_qa import diagnose

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples.json"
BIBLE = HERE / "bible.json"
FFMPEG_DIR = Path(__file__).resolve().parent.parent.parent / "tools" / "ffmpeg" / "bin"
MIN_SAMPLES = 6  # the kinds the suite must cover: two-person dialogue, a bout, a hand-over, a public face slap, a look, a crowd

PASS, FAIL, SKIPPED = "pass", "fail", "skipped"


@dataclass(frozen=True)
class SampleResult:
    sample_id: str
    intent: str
    verdict: str                     # pass | fail | skipped
    failures: list[str] = field(default_factory=list)   # VisualFailure codes, or NONDETERMINISTIC
    evidence: list[dict] = field(default_factory=list)
    note: str = ""                   # why it was skipped, or the provider's error
    seconds: float = 0.0
    artifact_hash: str = ""


@dataclass(frozen=True)
class Report:
    provider_id: str
    provider_version: str
    manifest_hash: str
    results: list[SampleResult]
    passed: bool
    allow_skipped: bool = False
    report_hash: str = ""

    @property
    def counts(self) -> dict[str, int]:
        return {v: sum(r.verdict == v for r in self.results) for v in (PASS, FAIL, SKIPPED)}

    @property
    def pass_rate(self) -> float:
        return round(self.counts[PASS] / len(self.results), 3) if self.results else 0.0

    def text(self) -> str:
        c = self.counts
        lines = [f"{self.provider_id} {self.provider_version}: {'PASS' if self.passed else 'FAIL'} "
                 f"({c[PASS]}/{len(self.results)} samples pass, {c[FAIL]} fail, {c[SKIPPED]} skipped)"]
        for r in self.results:
            tail = ", ".join(r.failures) if r.failures else r.note
            lines.append(f"  {r.verdict.upper():8} {r.sample_id:22} {r.intent:16} {r.seconds:5.1f}s  {tail}")
        return "\n".join(lines)


def load_samples(path: Path = SAMPLES) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not data.get("samples"):
        raise ValueError(f"{path}: no samples")
    return data


def shot_of(sample: dict, size: tuple[int, int] | None = None, scale: float | None = None) -> ShotRequest:
    """The sample's ShotRequest, optionally smaller (the checks do not depend on how many pixels, and ffmpeg's time does)."""
    shot = from_dict(ShotRequest, sample["shot"])
    if size is None and scale:
        size = (max(2, int(shot.width * scale) // 2 * 2), max(2, int(shot.height * scale) // 2 * 2))
    return dataclasses.replace(shot, width=size[0], height=size[1]) if size else shot


def check_fixtures(data: dict, bible: Bible | None = None) -> list[str]:
    """What is wrong with the sample set itself (empty when it is fine): too few, a repeated shot, or an asset the Bible lacks."""
    bad = []
    samples = data["samples"]
    if len(samples) < MIN_SAMPLES:
        bad.append(f"{len(samples)} samples; the suite needs at least {MIN_SAMPLES}")
    ids = [s["id"] for s in samples]
    if len(set(ids)) != len(ids):
        bad.append("a sample id is used twice")
    shots = [json.dumps(s["shot"], sort_keys=True) for s in samples]
    if len(set(shots)) != len(shots):
        bad.append("two samples are the same shot")
    if bible is not None:
        for s in samples:
            for aid in s["bible"]["characters"]:
                if aid not in bible.characters:
                    bad.append(f"{s['id']}: character {aid} is not in the Bible")
            if s["bible"]["scene"] not in bible.scenes:
                bad.append(f"{s['id']}: {s['bible']['scene']} is not in the Bible")
    return bad


def _params(shot: ShotRequest, features: list[str]) -> dict[str, str]:
    return {"shot_id": shot.shot_id, "seconds": f"{shot.duration_seconds:g}", "width": str(shot.width),
            "height": str(shot.height), "fps": str(shot.fps), "features": ",".join(features)}


def run_conformance(provider, data: dict | None = None, *, workdir: Path | None = None, policy: Policy = Policy(),
                    ffmpeg_dir: Path = FFMPEG_DIR, size: tuple[int, int] | None = None, scale: float | None = None,
                    determinism: int = 1, allow_skipped: bool = False, only: list[str] | None = None) -> Report:
    """Run the suite against one visual provider (anything with manifest/available/toolchain/generate).

    policy        the budget and the rules of the registry; the default allows only free providers.
    size, scale   generate smaller than the fixture's canvas (fit is still judged at the real size).
    determinism   how many samples are generated twice when the provider says it is deterministic (0 = none).
    only          sample ids to run (for looking at one failure); a partial run never passes, it is not the suite.
    """
    data = data or load_samples()
    manifest = provider.manifest()
    if "visual.generate" not in manifest.capabilities:
        raise ValueError(f"{manifest.provider_id} does not offer visual.generate")
    registry = CapabilityRegistry()
    registry.register(provider)
    own = workdir is None
    tmp = tempfile.TemporaryDirectory(prefix="conformance_") if own else None
    root = Path(tmp.name) if own else Path(workdir)
    results: list[SampleResult] = []
    rechecked = 0
    try:
        for sample in data["samples"]:
            if only and sample["id"] not in only:
                continue
            real = from_dict(ShotRequest, sample["shot"])
            requirement = Requirement("visual.generate", list(sample.get("requires", ["t2v"])), real.duration_seconds,
                                      real.width, real.height)
            selection = registry.select(requirement, policy)
            if not selection.chosen:
                why = "; ".join(r.reason for r in selection.rejected) or "not chosen"
                results.append(SampleResult(sample["id"], sample["intent"], SKIPPED, note=why))
                continue
            shot = shot_of(sample, size, scale)
            started = time.perf_counter()
            request = make_request(kind="shot", backend=manifest.provider_id, backend_version=manifest.version,
                                   parameters=_params(shot, requirement.features),
                                   packet_hash=sample["source"]["packet_hash"], seed=shot.seed, asset_hashes={},
                                   toolchain=provider.toolchain())
            dest = root / manifest.provider_id / f"{sample['id']}.mp4"
            take = _generate(provider, request, shot, dest)
            failures = diagnose(take, shot, ffmpeg_dir)
            codes = [f.code for f in failures]
            evidence = [{"code": f.code, "detector": f.detector, **f.evidence} for f in failures]
            note = (take.error or "")[:200] if take.status != "ready" else ""
            if not failures and manifest.deterministic and rechecked < determinism:
                rechecked += 1
                again = _generate(provider, request, shot, root / manifest.provider_id / f"{sample['id']}.again.mp4")
                if again.status != "ready" or again.artifact_hash != take.artifact_hash:
                    codes.append("NONDETERMINISTIC")
                    evidence.append({"code": "NONDETERMINISTIC", "detector": "rerun", "first": take.artifact_hash or "",
                                     "second": again.artifact_hash or again.status})
            results.append(SampleResult(sample["id"], sample["intent"], FAIL if codes else PASS, codes, evidence, note,
                                        round(time.perf_counter() - started, 2), take.artifact_hash or ""))
    finally:
        if tmp is not None:
            tmp.cleanup()
    complete = not only
    ok = (complete and bool(results) and all(r.verdict == PASS or (allow_skipped and r.verdict == SKIPPED) for r in results)
          and any(r.verdict == PASS for r in results))
    report = Report(manifest.provider_id, manifest.version, manifest.hash(), results, ok, allow_skipped)
    return dataclasses.replace(report, report_hash=_report_hash(report))


def _report_hash(report: Report) -> str:
    """The verdicts and their evidence, not how long the machine took: two runs of a deterministic provider agree."""
    steady = dataclasses.replace(report, results=[dataclasses.replace(r, seconds=0.0) for r in report.results])
    return hash_without(steady, "report_hash")


def _generate(provider, request, shot: ShotRequest, dest: Path) -> Take:
    """What production/shots.py does: a provider that raises has made a failed take, diagnosed like any other. A ready
    take with no artifact hash gets one, so that the rerun can compare."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        take = provider.generate(request, shot, dest)
    except Exception as e:  # noqa: BLE001
        return Take(request.request_hash, "failed", error=f"{type(e).__name__}: {e}"[:400])
    if take.status == "ready" and take.artifact_path and Path(take.artifact_path).exists() and not take.artifact_hash:
        take = dataclasses.replace(take, artifact_hash=file_sha256(Path(take.artifact_path)))
    return take


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", required=True, help="a visual.generate provider id from the capability registry")
    ap.add_argument("--samples", default=str(SAMPLES))
    ap.add_argument("--scale", type=float, default=None, help="generate at this fraction of the canvas, e.g. 0.25")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--allow-skipped", action="store_true")
    ap.add_argument("--json", default=None, help="also write the report here")
    args = ap.parse_args()
    from capability.defaults import default_registry
    registry = default_registry(lambda h: None)
    try:
        provider = registry.get(args.provider)
    except KeyError:
        print(f"no provider {args.provider!r}; visual.generate has: {registry.catalog().get('visual.generate', [])}")
        return 2
    report = run_conformance(provider, load_samples(Path(args.samples)), scale=args.scale, only=args.only,
                             allow_skipped=args.allow_skipped)
    print(report.text())
    if args.json:
        from contracts.base import to_dict
        Path(args.json).write_text(json.dumps(to_dict(report), ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
