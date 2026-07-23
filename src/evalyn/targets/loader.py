from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from evalyn.targets.schema import Probe, TargetSpec

_ENV_RE = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::-(?P<default>[^}]*))?\}")


class PackError(Exception): ...
class AllowlistError(Exception): ...


@dataclass
class Pack:
    spec: TargetSpec
    probes: list[Probe]
    root: Path


def _resolve_env_string(value: str) -> str:
    def repl(m: re.Match) -> str:
        return os.environ.get(m.group("name"), m.group("default") or "")
    return _ENV_RE.sub(repl, value)


def load_pack(path: str | Path) -> Pack:
    root = Path(path)
    target_file = root / "target.yaml"
    if not target_file.exists():
        raise PackError(f"no target.yaml in {root}")
    raw = yaml.safe_load(target_file.read_text()) or {}
    if isinstance(raw.get("env"), dict):
        raw["env"] = {k: _resolve_env_string(str(v)) for k, v in raw["env"].items()}
    try:
        spec = TargetSpec.model_validate(raw)
    except Exception as e:  # pydantic ValidationError
        raise PackError(f"invalid target.yaml: {e}") from e

    probes: list[Probe] = []
    probes_dir = root / "probes"
    probe_files = (sorted({*probes_dir.glob("*.yaml"), *probes_dir.glob("*.yml")})
                   if probes_dir.exists() else [])
    for pf in probe_files:
        entries = yaml.safe_load(pf.read_text()) or []
        for entry in entries:
            try:
                probes.append(Probe.model_validate(entry))
            except Exception as e:
                raise PackError(f"invalid probe in {pf.name}: {e}") from e

    seen: set[str] = set()
    dupes: set[str] = set()
    for p in probes:
        if p.id in seen:
            dupes.add(p.id)
        seen.add(p.id)
    if dupes:
        raise PackError(f"duplicate probe id(s): {', '.join(sorted(dupes))}")

    return Pack(spec=spec, probes=probes, root=root)


def resolve_base_url(pack: Pack) -> str:
    url = pack.spec.env.get("base_url", "")
    if url not in pack.spec.allowlist:
        raise AllowlistError(
            f"base_url {url!r} is not in the pack allowlist {pack.spec.allowlist!r}")
    return url
