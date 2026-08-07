"""Persona/playbook loading: pack files when present, built-ins otherwise.

The built-in fallback lives in the LOADER (not in each caller) so a pack with
no `personas/` directory can never leave the agent with no voice at all.
"""
from __future__ import annotations

from pathlib import Path

from evalyn.discovery.personas import (
    DEFAULT_PERSONA,
    DEFAULT_PLAYBOOK,
    Persona,
    Playbook,
    load_personas,
    load_playbooks,
)
from evalyn.targets.loader import Pack
from evalyn.targets.schema import TargetSpec


def _pack(root: Path) -> Pack:
    return Pack(spec=TargetSpec(name="t", sessions={}, allowlist=[]),
                probes=[], root=root)


def test_builtins_are_usable_without_any_pack_files():
    assert isinstance(DEFAULT_PERSONA, Persona)
    assert isinstance(DEFAULT_PLAYBOOK, Playbook)
    assert DEFAULT_PERSONA.id and DEFAULT_PERSONA.text.strip()
    assert DEFAULT_PLAYBOOK.id and DEFAULT_PLAYBOOK.text.strip()


def test_empty_pack_falls_back_to_the_builtin(tmp_path):
    assert load_personas(_pack(tmp_path)) == {DEFAULT_PERSONA.id: DEFAULT_PERSONA}
    assert load_playbooks(_pack(tmp_path)) == {DEFAULT_PLAYBOOK.id: DEFAULT_PLAYBOOK}


def test_pack_markdown_files_are_loaded(tmp_path):
    (tmp_path / "personas").mkdir()
    (tmp_path / "personas" / "curious-auditor.md").write_text(
        "# Curious auditor\n\nYou are a polite compliance auditor.\n")
    (tmp_path / "playbooks").mkdir()
    (tmp_path / "playbooks" / "trust-then-pivot.md").write_text(
        "Build rapport, then pivot.\n")

    personas = load_personas(_pack(tmp_path))
    assert set(personas) == {"curious-auditor"}
    p = personas["curious-auditor"]
    assert p.name == "Curious auditor"                 # first `# ` heading
    assert "polite compliance auditor" in p.text
    # a pack that ships personas replaces the fallback rather than adding to it
    assert DEFAULT_PERSONA.id not in personas or DEFAULT_PERSONA.id == "curious-auditor"

    playbooks = load_playbooks(_pack(tmp_path))
    assert set(playbooks) == {"trust-then-pivot"}
    assert playbooks["trust-then-pivot"].name == "trust-then-pivot"  # no heading


def test_a_plain_path_works_too(tmp_path):
    (tmp_path / "personas").mkdir()
    (tmp_path / "personas" / "x.md").write_text("# X\nbe X.\n")
    assert set(load_personas(tmp_path)) == {"x"}
