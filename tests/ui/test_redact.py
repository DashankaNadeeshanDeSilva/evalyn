"""The redaction chokepoint (Plan #4, Task 4).

These tests are written to be **discriminating**: each one names the literal it
expects to disappear and asserts against the *whole* serialized body, so a
redactor that only walks the top level, or that stops at the first match, fails
here rather than on a projector.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import yaml

from evalyn.targets.schema import Check, Probe
from evalyn.ui.models import REDACTION_MARKER_RE, redaction_marker
from evalyn.ui.redact import Redactor, no_redact

# A value that no pattern can recognise: not an email, not a phone, not a path,
# not a key shape. If this ever disappears from a body it is because harvesting
# put it in the literal table — never because a regex guessed.
SENTINEL = "zqx-sentinel-73914-quiet"

EMAIL = "owner@example.com"
PHONE = "+14155552671"
HOMEDIR = "/Users/alice/Drive/Projects/evalyn/runs/x.json"
BEARER_SECRET = "sk-live-9f8e7d6c5b4a32100011"

#: Not valid UTF-8 (a lone 0x89, a bare 0xff/0xfe pair): genuinely binary, the
#: one thing a text scrubber must hand back untouched.
BINARY_BODY = b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01owner@example.com"


def _nested() -> dict:
    """One structure carrying every pattern at a different nesting depth."""
    return {
        "run_id": "20260807T101112-0bf80f3b-twincore",
        "redacted": False,
        "turns": [
            {
                "role": "assistant",
                "content": f"mail {EMAIL} or call {PHONE}",
            },
            {
                "role": "assistant",
                "meta": {
                    "log_path": HOMEDIR,
                    "headers": {"authorization": f"Bearer {BEARER_SECRET}"},
                },
            },
        ],
    }


# --------------------------------------------------------------------------
# 1. The patterns, nested
# --------------------------------------------------------------------------

def test_every_pattern_is_scrubbed_however_deeply_it_is_nested():
    out = Redactor().scrub(_nested())
    blob = json.dumps(out)

    for leaked in (EMAIL, PHONE, HOMEDIR, BEARER_SECRET):
        assert leaked not in blob, f"{leaked!r} survived redaction"

    assert redaction_marker("email") in out["turns"][0]["content"]
    assert redaction_marker("phone") in out["turns"][0]["content"]
    assert out["turns"][1]["meta"]["log_path"] == redaction_marker("path")
    assert redaction_marker("token") in out["turns"][1]["meta"]["headers"]["authorization"]


def test_every_marker_matches_the_frozen_contract_marker_grammar():
    out = json.dumps(Redactor().scrub(_nested()), ensure_ascii=False)
    # Four patterns fired; every one of them must spell itself the one legal way.
    assert len(REDACTION_MARKER_RE.findall(out)) >= 4
    assert "«redacted:" in out
    for fragment in out.split("«redacted:")[1:]:
        kind = fragment.split("»")[0]
        assert REDACTION_MARKER_RE.fullmatch(f"«redacted:{kind}»"), kind


def test_the_input_is_never_mutated_in_place():
    before = _nested()
    snapshot = json.dumps(before)
    Redactor().scrub(before)
    assert json.dumps(before) == snapshot


def test_a_string_at_the_top_level_is_scrubbed_too():
    assert Redactor().scrub(f"ping {EMAIL}") == f"ping {redaction_marker('email')}"


def test_dict_keys_are_scrubbed_as_well_as_values():
    out = Redactor().scrub({"counts": {EMAIL: 3}})
    assert EMAIL not in json.dumps(out)
    assert redaction_marker("email") in out["counts"]


def test_a_value_under_a_secret_shaped_key_goes_even_when_it_looks_harmless():
    out = Redactor().scrub({"config": {"api_key": "hunter2", "pack": "twincore"}})
    assert out["config"]["api_key"] == redaction_marker("token")
    assert out["config"]["pack"] == "twincore"          # collateral damage check


def test_non_string_leaves_are_left_exactly_as_they_are():
    payload = {"passed": 12, "cost_usd": 0.41, "ok": True, "next": None}
    assert Redactor().scrub(payload) == payload


# --------------------------------------------------------------------------
# 2. Harvesting the pack's own check values
# --------------------------------------------------------------------------

def _probe_with_secret(value: str, check_type: str = "not_contains") -> Probe:
    return Probe(
        id="pii-leak",
        category="pii",
        turns=["what is the owner's contact?"],
        checks=[Check(type=check_type, value=value, required=True)],
    )


def test_without_harvesting_the_sentinel_survives():
    """The red half of the pair below — proves no regex can claim the credit."""
    body = {"content": f"the answer is {SENTINEL}"}
    assert SENTINEL in json.dumps(Redactor().scrub(body))


def test_harvest_from_probes_scrubs_a_check_value_no_pattern_could_match():
    redactor = Redactor()
    redactor.harvest_from_probes([_probe_with_secret(SENTINEL)])
    out = redactor.scrub({"content": f"the answer is {SENTINEL}"})
    assert SENTINEL not in json.dumps(out)
    assert redaction_marker("check_value") in out["content"]


def test_harvesting_reaches_the_multi_value_or_form():
    probe = Probe(
        id="redirect", category="injection", turns=["hi"],
        checks=[Check(type="contains", values=[SENTINEL, "other-long-value"])],
    )
    redactor = Redactor()
    redactor.harvest_from_probes([probe])
    assert SENTINEL not in json.dumps(redactor.scrub({"a": SENTINEL}))


def test_a_harvested_value_that_is_an_email_still_reads_as_an_email():
    """Label by what the literal *is*, not by how it was learned."""
    redactor = Redactor()
    redactor.harvest_from_probes([_probe_with_secret(EMAIL)])
    assert redactor.scrub(EMAIL) == redaction_marker("email")


def test_extra_values_are_honoured_from_the_constructor():
    assert Redactor(extra_values=[SENTINEL]).scrub(SENTINEL) == redaction_marker("check_value")


def test_a_short_or_empty_check_value_is_never_harvested():
    """An empty literal would match between every character in the corpus."""
    redactor = Redactor(extra_values=["", "   ", "no"])
    assert redactor.scrub("no problem, none at all") == "no problem, none at all"


def test_harvesting_survives_a_probe_that_is_not_shaped_like_a_probe():
    redactor = Redactor()
    redactor.harvest_from_probes([None, object(), {"checks": [{"value": SENTINEL}]}])
    assert SENTINEL not in redactor.scrub(SENTINEL)


# --------------------------------------------------------------------------
# 3. `redacted: bool` — set, never invented
# --------------------------------------------------------------------------

def test_scrubbing_sets_redacted_true_on_the_containing_object():
    out = Redactor().scrub(_nested())
    assert out["redacted"] is True


def test_the_flag_is_set_at_every_level_that_declares_it():
    out = Redactor().scrub({
        "redacted": False,
        "gate": {"redacted": False, "report_md": f"contact {EMAIL}"},
        "sibling": {"redacted": False, "note": "nothing sensitive here"},
    })
    assert out["redacted"] is True
    assert out["gate"]["redacted"] is True
    assert out["sibling"]["redacted"] is False, "an untouched object must not claim it was scrubbed"


def test_the_flag_is_never_added_to_an_object_that_did_not_declare_it():
    """Every response model is `extra='forbid'`; inventing the key breaks parsing."""
    out = Redactor().scrub({"content": EMAIL})
    assert "redacted" not in out


def test_the_flag_is_left_alone_when_nothing_was_scrubbed():
    payload = {"redacted": False, "content": "all clear"}
    assert Redactor().scrub(payload) == payload


# --------------------------------------------------------------------------
# 4. Idempotence
# --------------------------------------------------------------------------

def test_scrub_is_idempotent():
    redactor = Redactor(extra_values=[SENTINEL])
    once = redactor.scrub({**_nested(), "s": SENTINEL})
    assert redactor.scrub(once) == once


def test_a_marker_is_never_itself_redacted():
    for kind in ("email", "phone", "path", "token", "check_value"):
        marker = redaction_marker(kind)
        assert Redactor().scrub(marker) == marker


# --------------------------------------------------------------------------
# 5. Degradation, not failure
# --------------------------------------------------------------------------

def test_scrubbing_an_unexpected_type_returns_it_rather_than_raising():
    sentinel = object()
    assert Redactor().scrub(sentinel) is sentinel
    assert Redactor().scrub(b"bytes are opaque") == b"bytes are opaque"


def test_a_tuple_and_a_set_are_walked_without_raising():
    out = Redactor().scrub({"t": (EMAIL,), "s": {EMAIL}})
    assert EMAIL not in json.dumps(out, default=list)


def test_a_pathologically_deep_structure_does_not_blow_the_stack():
    deep: object = EMAIL
    for _ in range(5000):
        deep = {"next": deep}
    out = Redactor().scrub(deep)          # must not raise RecursionError
    assert EMAIL not in json.dumps(out)


def test_a_cycle_terminates():
    node: dict = {"content": EMAIL}
    node["self"] = node
    Redactor().scrub(node)                # must not hang or raise


def test_scrub_text_is_available_for_the_sse_tailer():
    assert Redactor().scrub_text(f"data: {EMAIL}") == f"data: {redaction_marker('email')}"
    assert Redactor().scrub_text(None) is None      # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 6. `RedactingRoute` — the chokepoint itself
# --------------------------------------------------------------------------
#
# **Deferred to Task 6 (controller instruction).** The route-table test — walk
# `app.routes`, assert every `/api` route is a `RedactingRoute` or carries the
# marker, and that the marked set is *exactly* `{"/api/meta", "/api/health"}` —
# belongs in this file but cannot exist yet: it asserts over an app, and
# `create_app` arrives in Task 6. The app factory's task inherits it. The tests
# below cover the mechanism; only the census of the real route table is missing.

def _app():
    from fastapi import APIRouter, FastAPI
    from fastapi.responses import PlainTextResponse, StreamingResponse

    from evalyn.ui.redact import RedactingRoute

    router = APIRouter(route_class=RedactingRoute)

    @router.get("/leaky")
    async def leaky() -> dict:
        return {"content": f"contact {EMAIL}", "redacted": False}

    @router.get("/exempt")
    @no_redact
    async def exempt() -> dict:
        return {"content": f"mail {EMAIL}"}

    @router.get("/stderr", response_class=PlainTextResponse)
    async def stderr() -> str:
        return f"Traceback from {HOMEDIR}"

    @router.get("/events")
    async def events() -> StreamingResponse:
        async def gen():
            yield f"data: {EMAIL}\n\n".encode()
        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.get("/boom")
    async def boom() -> dict:
        return {"content": f"mail {EMAIL}"}

    @router.get("/yaml")
    async def yaml_view():
        """`FindingDetail.probe_yaml` rendered raw — the conventional type for it."""
        from starlette.responses import Response
        return Response(content=f"value: {EMAIL}\n", media_type="application/x-yaml")

    @router.get("/bare")
    async def bare():
        """A plain Starlette `Response`: `media_type` is `None` by default."""
        from starlette.responses import Response
        return Response(content=json.dumps({"content": f"mail {EMAIL}"}))

    @router.get("/binary")
    async def binary():
        from starlette.responses import Response
        return Response(content=BINARY_BODY, media_type="application/octet-stream")

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


async def _get(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ui") as client:
        return await client.get(path)


async def test_a_route_under_the_redacting_router_is_scrubbed_without_asking():
    response = await _get(_app(), "/api/leaky")
    assert EMAIL not in response.text
    assert redaction_marker("email") in response.json()["content"]
    assert response.json()["redacted"] is True


async def test_the_rewritten_body_carries_an_honest_content_length():
    response = await _get(_app(), "/api/leaky")
    assert int(response.headers["content-length"]) == len(response.content)


async def test_only_an_explicitly_marked_endpoint_escapes():
    response = await _get(_app(), "/api/exempt")
    assert EMAIL in response.text


async def test_a_plain_text_body_is_scrubbed_too():
    """`/api/runs/{id}/stderr` is text, and stderr is where paths and keys live."""
    response = await _get(_app(), "/api/stderr")
    assert HOMEDIR not in response.text
    assert redaction_marker("path") in response.text


async def test_a_yaml_body_is_scrubbed_and_not_waved_through_as_binary():
    """`application/x-yaml` is the raw-YAML view of `FindingDetail.probe_yaml`.

    That view serves `discovered-pii-leak-0bf80f3b.yaml` — the file with the
    real address this module exists for. A content-type the scrubber does not
    recognise must **not** mean "pass it through".
    """
    response = await _get(_app(), "/api/yaml")
    assert EMAIL not in response.text
    assert redaction_marker("email") in response.text


async def test_a_response_with_no_media_type_at_all_is_still_scrubbed():
    """Starlette's plain `Response` has `media_type = None`.

    An endpoint that hands back a bare `Response` has not opted out of anything
    — `no_redact` is the only opt-out there is.
    """
    response = await _get(_app(), "/api/bare")
    assert EMAIL not in response.text
    assert redaction_marker("email") in response.text


async def test_a_genuinely_binary_body_is_handed_back_byte_for_byte():
    """The one documented limit: bytes that are not UTF-8 are not text.

    Pass-through here is deliberate and narrow — it is reached only by a
    `UnicodeDecodeError`, never by a content type the scrubber failed to
    recognise. The body must come back intact rather than mangled or withheld.
    """
    response = await _get(_app(), "/api/binary")
    assert response.status_code == 200
    assert response.content == BINARY_BODY


async def test_a_streaming_response_is_passed_through_untouched():
    """The SSE tailer scrubs at the source; buffering the stream here would
    defeat streaming altogether."""
    response = await _get(_app(), "/api/events")
    assert EMAIL in response.text


async def test_a_redaction_failure_withholds_the_body_rather_than_leaking_it(monkeypatch):
    from evalyn.ui import redact as redact_mod

    def explode(self, obj):                    # noqa: ARG001
        raise RuntimeError("redactor is broken")

    monkeypatch.setattr(redact_mod.Redactor, "scrub", explode)
    response = await _get(_app(), "/api/boom")
    assert response.status_code == 500
    assert EMAIL not in response.text
    assert response.json()["error"]["code"]


async def test_the_app_state_redactor_is_the_one_that_runs():
    app = _app()
    app.state.redactor = Redactor(extra_values=[SENTINEL])
    # the harvested literal only disappears if the route consulted app.state
    response = await _get(app, "/api/leaky")
    assert redaction_marker("email") in response.text
    app2 = _app()
    app2.state.redactor = Redactor(extra_values=["contact"])
    assert "contact" not in (await _get(app2, "/api/leaky")).text


def test_no_redact_marks_the_function_without_changing_what_it_does():
    from evalyn.ui.redact import is_no_redact

    @no_redact
    def handler(x):
        """docstring survives"""
        return x * 2

    assert is_no_redact(handler) is True
    assert handler(3) == 6
    assert handler.__doc__ == "docstring survives"
    assert handler.__name__ == "handler"

    def plain():
        pass

    assert is_no_redact(plain) is False
    assert is_no_redact(None) is False


def test_the_route_class_is_a_fastapi_route_subclass():
    from fastapi.routing import APIRoute

    from evalyn.ui.redact import RedactingRoute

    assert issubclass(RedactingRoute, APIRoute)
    # Fetched twice, it must be the *same* class object, or an `isinstance`
    # check in the Task 6 route-table test would silently never match.
    from evalyn.ui.redact import RedactingRoute as Again
    assert Again is RedactingRoute


def test_importing_the_module_does_not_drag_in_fastapi():
    """The redactor proper is pure stdlib, and stays importable without the
    `[ui]` extra — otherwise Task 6's "install `evalyn[ui]`" refusal would be an
    `ImportError` from three modules away instead of a sentence a human reads.
    A subprocess, because this interpreter has already imported everything.
    """
    import subprocess
    import sys

    probe = ("import evalyn.ui.redact, sys, json;"
             "print(json.dumps(sorted({name.split('.')[0] for name in sys.modules}"
             " & {'fastapi', 'uvicorn'})))")
    done = subprocess.run([sys.executable, "-c", probe], check=True,
                          capture_output=True, text=True)
    assert json.loads(done.stdout) == [], done.stdout


@pytest.mark.parametrize("leak", [
    "owner@example.com",
    "first.last+tag@sub.domain.co.uk",
    "+14155552671",
    "+1 415 555 2671",
    "+49 30 901820",
    "/Users/alice/notes.txt",
    "/home/bob/.config/evalyn/keys.json",
    r"C:\Users\carol\AppData\evalyn.log",
    "Bearer sk-live-9f8e7d6c5b4a32100011",
    "sk-ant-api03-AAAABBBBCCCCDDDDEEEE",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
    "authorization: Basic YWxpY2U6c2VjcmV0Cg==",
    # shape-blind: nothing about these values gives them away, only the name
    # in front of them — and stderr is full of exactly this
    "api_key=s3cr3t-value",
    "password: correcthorsebattery",
])
def test_each_known_leak_shape_is_caught(leak: str):
    out = Redactor().scrub(f"prefix {leak} suffix")
    assert REDACTION_MARKER_RE.search(out), f"{leak!r} was not redacted at all"
    assert leak not in out


def test_the_scheme_word_survives_but_the_credential_does_not():
    """The ordering claim, asserted rather than assumed.

    With the generic `key: value` rule running first, `authorization: Basic
    <base64>` has the *word* `Basic` redacted and the credential left standing
    — a redaction that looks like it worked. This is the test that fails when
    that ordering is disturbed; the shape table above does not, because
    "the input string is absent" is satisfied either way.
    """
    out = Redactor().scrub("authorization: Basic YWxpY2U6c2VjcmV0Cg==")
    assert "YWxpY2U6c2VjcmV0Cg" not in out
    # Standing alone, the scheme word is context an operator wants and is kept.
    # (Behind `authorization:` it goes too, because the shape-blind rule redacts
    # everything after a credential-named key — over-redaction, not a leak.)
    assert Redactor().scrub(f"Bearer {BEARER_SECRET}") == f"Bearer {redaction_marker('token')}"


@pytest.mark.parametrize("keep", [
    "the gate passed 48 of 50 probes",
    "packs/twincore/probes/injection.yaml",
    "20260807T101112-0bf80f3b-twincore",
    "version 0.4.0, cost 0.41 usd",
    "/usr/local/lib/python3.12/site-packages",
    "runs/.evalyn-ui/meta.json",
])
def test_ordinary_cockpit_text_is_left_alone(keep: str):
    assert Redactor().scrub(keep) == keep


# --------------------------------------------------------------------------
# 8. The real corpus — the file that is actually going on the projector
# --------------------------------------------------------------------------

DISCOVERY = (Path(__file__).resolve().parents[2]
             / "packs" / "twincore" / "discoveries"
             / "discovered-pii-leak-0bf80f3b.yaml")

#: This file's own source must never spell the leaked address — `tests/` is
#: tracked in a public repo, which is the whole reason `discoveries/` is not.
_EMAIL_SHAPE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@pytest.mark.skipif(not DISCOVERY.exists(),
                    reason="the staged discovery is gitignored — local corpus only")
def test_the_staged_pii_leak_finding_is_scrubbed_end_to_end():
    """`FindingDetail.probe_yaml` serves this file's bytes verbatim.

    It carries a live address in three places — the confirmation line, the
    turns preview, and the `not_contains` check value — and it is the exhibit
    the discover demo opens. Nothing here is hardcoded: the assertion is
    "no address-shaped string survives", so the test cannot leak what it
    guards.
    """
    raw = DISCOVERY.read_text()
    assert _EMAIL_SHAPE.search(raw), "corpus changed; this test would pass vacuously"

    probes = [Probe.model_validate(entry) for entry in yaml.safe_load(raw)]
    redactor = Redactor()
    redactor.harvest_from_probes(probes)

    out = redactor.scrub({"probe_yaml": raw, "provenance": {"confirmation": raw},
                          "redacted": False})
    assert not _EMAIL_SHAPE.search(json.dumps(out)), "an address survived the chokepoint"
    assert out["redacted"] is True

    leaked = [c.value for p in probes for c in p.checks if c.type == "not_contains"]
    assert leaked and leaked[0] not in json.dumps(out)
