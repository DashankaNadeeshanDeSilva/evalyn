from __future__ import annotations

import json
from pathlib import Path

from evalyn.engine.run import RunArtifact


def save_baseline(art: RunArtifact, path: str = "runs/baseline.json") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(art.to_dict(), indent=2, default=str))


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
