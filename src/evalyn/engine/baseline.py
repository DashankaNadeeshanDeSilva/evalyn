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
    return RunArtifact.from_dict(json.loads(p.read_text()))
