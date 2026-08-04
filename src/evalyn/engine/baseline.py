from __future__ import annotations

import json
from pathlib import Path

from evalyn.engine.run import RunArtifact


def save_baseline(art: RunArtifact, path: str = "runs/baseline.json") -> None:
    # 2026-08-04 ruling: baselines deliberately EXCLUDE per-trial transcripts
    # (privacy/size) — trial_records live in run artifacts only. Blessing
    # evidence (pass_k, checks, trials, ...) stays; nothing reads baseline
    # trial_records and ProbeResult defaults the missing field to [] on load.
    d = art.to_dict()
    for probe in d.get("probes", []):
        probe.pop("trial_records", None)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(d, indent=2, default=str))


def load_baseline(path: str = "runs/baseline.json") -> RunArtifact | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"baseline {p} is not valid JSON (corrupt or truncated?): {e}") from e
    try:
        return RunArtifact.from_dict(data)
    except ValueError as e:
        raise RuntimeError(
            f"baseline {p} predates the Plan #2a artifact schema and cannot be "
            f"gated against — re-create it with --update-baseline ({e})") from e
