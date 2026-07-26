from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from evalyn.targets.schema import Probe, TargetSpec

_ENV_RE = re.compile(r"\$\{(?P<name>[A-Za-z0-9_]+)(?::-(?P<default>[^}]*))?\}")


class PackError(Exception): ...
class AllowlistError(Exception): ...


@dataclass
class Pack:
    spec: TargetSpec
    probes: list[Probe]
    root: Path
    # Raw on-disk bytes of every pack file (target.yaml, probes/*, rubrics/*),
    # keyed by pack-relative name, sorted. The pack fingerprint hashes THESE
    # bytes, so resolved ${ENV} values never leak into the fingerprint.
    raw_files: dict[str, bytes] = field(default_factory=dict)


def _resolve_env_string(value: str) -> str:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` placeholders (upper- or
    lowercase names). Bash ``:-`` semantics: a var that is UNSET **or set but
    empty** falls back to the default (empty string when no default given)."""
    def repl(m: re.Match) -> str:
        val = os.environ.get(m.group("name"))
        if not val:  # unset OR set-but-empty -> default
            return m.group("default") or ""
        return val
    return _ENV_RE.sub(repl, value)


def load_pack(path: str | Path) -> Pack:
    root = Path(path)
    target_file = root / "target.yaml"
    if not target_file.exists():
        raise PackError(f"no target.yaml in {root}")
    raw_files: dict[str, bytes] = {"target.yaml": target_file.read_bytes()}
    raw = yaml.safe_load(raw_files["target.yaml"]) or {}
    if isinstance(raw.get("env"), dict):
        raw["env"] = {k: _resolve_env_string(str(v)) for k, v in raw["env"].items()}
    # Session paths may carry ${ENV[:-default]} placeholders (e.g. a tenant slug in
    # /api/twin/${SLUG}/chat). Resolved here, AFTER raw_files captured the on-disk
    # bytes, so resolved values never reach the pack fingerprint.
    if isinstance(raw.get("sessions"), dict):
        for endpoint in raw["sessions"].values():
            if isinstance(endpoint, dict) and isinstance(endpoint.get("path"), str):
                endpoint["path"] = _resolve_env_string(endpoint["path"])
    try:
        spec = TargetSpec.model_validate(raw)
    except ValidationError as e:
        raise PackError(f"invalid target.yaml: {e}") from e

    probes: list[Probe] = []
    probes_dir = root / "probes"
    probe_files = (sorted({*probes_dir.glob("*.yaml"), *probes_dir.glob("*.yml")})
                   if probes_dir.exists() else [])
    for pf in probe_files:
        raw_files[f"probes/{pf.name}"] = pf.read_bytes()
        entries = yaml.safe_load(raw_files[f"probes/{pf.name}"]) or []
        for entry in entries:
            try:
                probes.append(Probe.model_validate(entry))
            except ValidationError as e:
                raise PackError(f"invalid probe in {pf.name}: {e}") from e

    seen: set[str] = set()
    dupes: set[str] = set()
    for p in probes:
        if p.id in seen:
            dupes.add(p.id)
        seen.add(p.id)
    if dupes:
        raise PackError(f"duplicate probe id(s): {', '.join(sorted(dupes))}")

    rubrics_dir = root / "rubrics"
    if rubrics_dir.exists():
        for rf in sorted(rubrics_dir.glob("*.md")):
            raw_files[f"rubrics/{rf.name}"] = rf.read_bytes()

    return Pack(spec=spec, probes=probes, root=root,
                raw_files=dict(sorted(raw_files.items())))


def resolve_base_url(pack: Pack) -> str:
    url = pack.spec.env.get("base_url", "")
    if url not in pack.spec.allowlist:
        raise AllowlistError(
            f"base_url {url!r} is not in the pack allowlist {pack.spec.allowlist!r}")
    return url
