"""Redaction — a chokepoint, not a habit (Plan #4, Task 4).

This cockpit renders transcripts and discovery findings from a **real shipped
product**, on a laptop that will be plugged into a projector. A leaked
identifier is not a bug report, it is an incident, so redaction here is
*default-on and structural*: every route mounted on the `/api` router runs
through `RedactingRoute`, which scrubs the response body **after** model
serialization. An endpoint cannot bypass it by forgetting to call something.

Three properties earn that description:

* **One gate, at the boundary.** A future task adding `/api/whatever` inherits
  redaction by mounting on the same router. The only escape is the explicit
  `@no_redact` marker, which the design spec pins to exactly two routes
  (`/api/meta`, `/api/health`) and which the route-table test enumerates. The
  SSE tailer is the one other call site, and it scrubs at the source via
  `scrub_text` — buffering a stream here to rewrite it would defeat streaming.
* **Nesting is not an escape.** `scrub` walks the whole structure. A redactor
  that only rewrote the top level would be *worse* than none, because findings
  and transcripts keep their payload three or four levels down and the thing
  would still look like it worked.
* **The pack's own `not_contains` values are secrets.** A `not_contains` value
  is, by construction, a string the product must never emit —
  `discovered-pii-leak-0bf80f3b.yaml` embeds a real email address as one, and
  twincore's are the system-prompt fragments that must not leak. So
  `harvest_from_probes` lifts them into the literal table and the finding is
  redacted *by construction*, not because a regex was clever enough. Its
  opposite, `contains`, is **not** harvested (ruling R4-18): a `contains` value
  is the string the product *should* emit. Twincore's are whole refusal
  sentences — the `redirect_constants`, which are also the probe's `reference`
  — so harvesting them would blank out exactly the transcripts where the model
  answered correctly. The two lists are semantic opposites; only one of them
  names a secret.

**Fail closed, everywhere.** Unknown value types pass through untouched (they
cannot carry a string), a container that refuses to be walked collapses to a
marker, depth is capped so a cycle or a pathological artifact terminates, and a
body the route cannot scrub is **withheld with a 500** rather than returned
unredacted. Degradation, not failure — but never degradation into a leak.

**No web framework on import.** `RedactingRoute` and
`redacting_exception_handlers` both need FastAPI, so the first is built on
first attribute access (PEP 562) and the second imports inside its body rather
than at module level. That keeps
`import evalyn.ui.redact` free of fastapi — the same discipline that keeps
`evalyn/ui/__init__.py` empty — so the "install `evalyn[ui]`" refusal stays a
sentence a human reads instead of an `ImportError` from three modules away.
"""
from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from evalyn.ui.models import REDACTION_MARKER_RE, ErrorCode, redaction_marker

if TYPE_CHECKING:                       # pragma: no cover - typing only
    from evalyn.targets.schema import Probe

__all__ = [
    # `RedactingRoute` is materialised by `__getattr__` (PEP 562) rather than
    # bound at import, which is what keeps FastAPI out of this module's import
    # graph. Ruff cannot see a lazy binding, hence the silence.
    "Redactor", "RedactingRoute", "no_redact", "is_no_redact",  # noqa: F822
    "redacting_exception_handlers",
    "NO_REDACT_ATTR", "MAX_DEPTH", "MIN_HARVEST_LENGTH",
    "WORDLIKE_LITERAL_MAX_LENGTH",
]


# --------------------------------------------------------------------------
# 1. Patterns
# --------------------------------------------------------------------------
#
# Order is load-bearing and runs top to bottom. `bearer|basic` must fire before
# the generic `key: value` rule, or `authorization: Basic <base64>` would have
# the *word* "Basic" redacted and the credential left standing — a rule that
# looks like it worked and leaks anyway. Every replacement is a marker, so a
# second pass over the output is a no-op: idempotence falls out of the ordering
# rather than being asserted on top of it.

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: `Bearer <credential>` / `Basic <base64>` / `token <credential>`. The scheme
#: word is kept — it is not the secret, and "an Authorization header was here"
#: is exactly the context an operator needs. (Written as `authorization: Basic
#: …` the shape-blind rule below then takes the scheme too. Over-redaction is
#: an acceptable outcome; the ordering exists so the *credential* is never the
#: thing left behind.)
_SCHEME_CRED_RE = re.compile(r"(?i)\b(bearer|basic|token)\s+([A-Za-z0-9._~+/\-]{8,}={0,2})")

#: Provider key shapes: OpenAI/Anthropic `sk-…`, AWS `AKIA…`, GitHub `ghp_…`,
#: Slack `xox…`.
_KEY_SHAPE_RE = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}"
    r"|\bAKIA[0-9A-Z]{12,}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{16,}\b"
    r"|\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"
)

#: `api_key = hunter2` in free text — the shape-blind fallback, which is what
#: catches a secret that looks like nothing in particular.
_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)\b(api[_\- ]?key|apikey|secret|password|passwd|access[_\-]?token"
    r"|refresh[_\-]?token|token|authorization)\b(\s*[:=]\s*[\"']?)([^\s\"',}]{4,})"
)

#: Home directories, which name their owner. Note the character classes carry
#: no whitespace, so a path stops at the end of the path and does not swallow
#: the rest of the sentence.
_POSIX_HOME_RE = re.compile(r"/(?:Users|home)/[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-+@%~]*)*")
_WINDOWS_HOME_RE = re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._\-]+(?:\\[A-Za-z0-9._\-+@%~]*)*")

#: E.164, compact or separated. The digit count is checked in code rather than
#: in the pattern: `+` followed by 8–15 digits is a phone number, `+` followed
#: by four is a diff hunk header.
_PHONE_RE = re.compile(r"(?<![\w+])\+\d(?:[ .\-]?\d){6,17}(?!\d)")

#: Trailing sentence punctuation a greedy path match would otherwise swallow.
_PATH_TAIL = ".,;:!?)]}'\"" + "»"

#: A key whose *name* says the value is a credential. Shape-blind by design:
#: `{"api_key": "hunter2"}` matches no pattern above and must still go.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)^(?:x-)?(?:api[_\-]?key|apikey|secret|password|passwd|token"
    r"|access[_\-]?token|refresh[_\-]?token|auth|authorization|credentials?"
    r"|bearer|private[_\-]?key|session[_\-]?key)$"
)

#: Beyond this nesting the walk stops and the subtree collapses to a marker.
#: Real artifacts are under ten deep; anything past this is a cycle or an
#: attempt to bury a payload below the walker, and both fail closed.
MAX_DEPTH = 64

#: A harvested literal shorter than this is refused. An empty check value would
#: match between every character in the corpus, and a two-letter one would turn
#: the transcript into confetti.
MIN_HARVEST_LENGTH = 3


def _digits(text: str) -> int:
    return sum(char.isdigit() for char in text)


def _sub_marker(kind: str):
    def _replace(match: re.Match[str]) -> str:
        return redaction_marker(kind)
    return _replace


def _replace_phone(match: re.Match[str]) -> str:
    return redaction_marker("phone") if 8 <= _digits(match.group()) <= 15 else match.group()


def _replace_path(match: re.Match[str]) -> str:
    matched = match.group()
    tail = ""
    while matched and matched[-1] in _PATH_TAIL:
        tail = matched[-1] + tail
        matched = matched[:-1]
    if not matched:
        return match.group()
    return redaction_marker("path") + tail


def _replace_scheme_cred(match: re.Match[str]) -> str:
    return f"{match.group(1)} {redaction_marker('token')}"


def _replace_assigned(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}{redaction_marker('token')}"


#: `(compiled, replacement)`, applied in this order to every string.
_PATTERNS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (_EMAIL_RE, _sub_marker("email")),
    (_SCHEME_CRED_RE, _replace_scheme_cred),
    (_KEY_SHAPE_RE, _sub_marker("token")),
    (_ASSIGNED_SECRET_RE, _replace_assigned),
    (_POSIX_HOME_RE, _replace_path),
    (_WINDOWS_HOME_RE, _replace_path),
    (_PHONE_RE, _replace_phone),
)


#: "A word character that is not `_`" — the one character class the guard uses,
#: for both halves of the decision: what makes a literal a bare word, and what
#: counts as a neighbour once it is. `\w` is Unicode-aware, so this covers `ü`,
#: `λ`, `システム` and every other script a transcript can carry; subtracting `_`
#: is what makes an underscore punctuation rather than a letter.
_WORD_CHAR = r"[^\W_]"
_WORD_RUN_RE = re.compile(_WORD_CHAR + r"+", re.UNICODE)

#: The length at which a literal stops being read as a word and starts being
#: read as a secret. Eight is the shortest length any credential policy defends
#: (NIST SP 800-63B's floor for a user-chosen secret), so below it "this is a
#: word of ordinary prose" is the better guess, and above it the opposite is.
WORDLIKE_LITERAL_MAX_LENGTH = 8


def _is_wordlike(value: str) -> bool:
    """Could this literal be a *fragment of an ordinary word* rather than a hit?

    Both halves are needed and neither is about the surrounding text:

    * **Short.** A long literal is not a coincidence, whatever it is made of.
    * **A single run of letters and digits.** `.`, `/`, `-`, `@`, `_` and
      whitespace are the shapes secrets take — filenames, paths, addresses,
      identifiers, phrases — and the shapes words do not, so a literal carrying
      one cannot be swallowed by a word however short it is.

    Deliberately *not* a mixed-case test, which the round-4 brief floated: title
    case is both the commonest way a word is written and the exact shape of the
    canonical word-like literal (`Acme`), so "contains upper and lower" would
    classify the one value this predicate exists to guard as a secret. An
    internal-case-transition test would be a third proxy of the same brittle
    family, and it would buy only short camelCase literals — a class with no
    claim on either failure mode.
    """
    return (len(value) < WORDLIKE_LITERAL_MAX_LENGTH
            and _WORD_RUN_RE.fullmatch(value) is not None)


def _literal_pattern(value: str) -> str:
    r"""Escape a harvested literal, and guard it **only where it might be a word**.

    Anchoring used to be a property of the literal's *neighbours* — "is the next
    character a letter?" — as a stand-in for "is this match an accidental
    substring?". Three rounds re-tuned that character class and each one traded
    one failure for the other, because the proxy only holds for space-separated
    scripts: tighten it to `[A-Za-z0-9]` and `Acmeüberwachung` fragments; widen
    it to `[^\W_]` and `システムプロンプトはBOUNDARIES.mdです` hands back a
    system-prompt fragment, since welding a Latin token to its neighbours is not
    a coincidence in Japanese, Chinese, Thai or Korean — it is how the prose is
    written. There is no setting that serves both jobs.

    The error was structural: **the guard sat on the leak path.** In a default-on
    chokepoint, a Unicode character-class question must never get to decide
    whether a secret is emitted. So the guard now depends on the literal's own
    specificity (`_is_wordlike`), which the redactor knows for certain, instead
    of on the script of the text around it, which it can only guess at:

    * **A specific literal matches unanchored** — `BOUNDARIES.md`,
      `/opt/twincore-secrets`, a leaked address. Leak risk goes to zero in every
      script. What is traded away is the possibility of fragmenting a word that
      happens to contain a 13-character filename, which is not a real event.
    * **A word-like literal keeps the `[^\W_]` guard** — the `Acme` class. The
      class question survives there, and it no longer matters: a bare word under
      eight characters is not a secret, so an escape leaks nothing and an
      over-fire costs cosmetics. Both wrong answers are cheap.

    That is the point of the split, and it is the right way round: for a
    redaction cockpit, over-redacting ordinary text is the cheap failure and
    emitting a secret is the expensive one.

    `MIN_HARVEST_LENGTH` still applies underneath, and stays at 3 rather than
    rising to swallow this class: raising it would silently *drop* every short
    `not_contains` value a pack declared, turning a cosmetic problem into a
    value the chokepoint never looks for at all.
    """
    if not _is_wordlike(value):
        return re.escape(value)
    return rf"(?<!{_WORD_CHAR}){re.escape(value)}(?!{_WORD_CHAR})"


def _classify(literal: str) -> str:
    """Name a harvested literal by what it *is*, not by how it was learned.

    The leaked value in `discovered-pii-leak-0bf80f3b.yaml` is an email that
    happens also to be a check value; `«redacted:email»` tells an operator what
    was hidden, `«redacted:check_value»` only tells them where it came from.
    """
    if _EMAIL_RE.fullmatch(literal):
        return "email"
    if _PHONE_RE.fullmatch(literal) and 8 <= _digits(literal) <= 15:
        return "phone"
    if _POSIX_HOME_RE.fullmatch(literal) or _WINDOWS_HOME_RE.fullmatch(literal):
        return "path"
    if _KEY_SHAPE_RE.fullmatch(literal):
        return "token"
    return "check_value"


# --------------------------------------------------------------------------
# 2. The redactor
# --------------------------------------------------------------------------

class Redactor:
    """Rewrites strings anywhere inside a JSON-able structure.

    Stateless per call and safe to share: `scrub` builds new containers and
    never mutates its input, because the caller's object is often a cache entry
    that other requests still hold.
    """

    def __init__(self, extra_values: Iterable[str] = ()) -> None:
        #: lower-cased literal -> marker kind. Matching is case-insensitive: an
        #: email retyped in a different case is the same leak.
        self._literals: dict[str, str] = {}
        self._literal_re: re.Pattern[str] | None = None
        self.add_values(extra_values)

    # -- learning ---------------------------------------------------------

    def add_values(self, values: Iterable[str]) -> None:
        """Add literals to scrub verbatim. Silently refuses useless ones."""
        for value in values or ():
            if not isinstance(value, str):
                continue
            if len(value.strip()) < MIN_HARVEST_LENGTH:
                continue
            if REDACTION_MARKER_RE.fullmatch(value):
                continue
            key = value.lower()
            if key not in self._literals:
                self._literals[key] = _classify(value)
                self._literal_re = None          # invalidate the compiled union

    def harvest_from_probes(self, probes: Iterable[Probe]) -> None:
        """Lift every **`not_contains`** value out of a pack into the table.

        The filter is on *sensitivity*, not on which fields happen to be
        populated. A `not_contains` value is a string the product must never
        emit, so it is a secret the pack itself has already identified. A
        `contains` value is the opposite — the answer the product is supposed
        to give — and twincore's are whole assistant sentences, so harvesting
        them would replace the model's correct answer with a marker (ruling
        R4-18, deviating from the spec deliberately).

        Reads the type off a `Probe` or off a plain dict alike, which is how a
        salvaged (unparseable) pack still contributes its secrets. A check that
        does not say what it is contributes nothing: there is no way to tell
        which of the two lists it belongs to.
        """
        for probe in probes or ():
            try:
                for check in _attr(probe, "checks") or ():
                    if _attr(check, "type") != "not_contains":
                        continue
                    value = _attr(check, "value")
                    if isinstance(value, str):
                        self.add_values([value])
                    # The schema says `values` is a `contains`-only form, but it
                    # is not statically validated (schema.py, Plan #3 register
                    # row 16), so a `not_contains` carrying one is accepted
                    # input. Reading it costs nothing and refusing it would be a
                    # leak on a technicality.
                    values = _attr(check, "values")
                    if isinstance(values, (list, tuple)):
                        self.add_values(values)
            except Exception:                    # a pack is untrusted input
                continue

    # -- scrubbing --------------------------------------------------------

    def scrub(self, obj: Any) -> Any:
        """Return `obj` with every string inside it redacted.

        Mappings, sequences, sets, **pydantic models and dataclasses** are all
        walked; a model or dataclass comes back as its scrubbed `dict`
        projection rather than as its own type (see `_walk`).

        Total by construction: an unexpected type comes back untouched, and an
        unexpected *failure* comes back as a marker rather than as the
        original, because the one outcome this must never have is a leak.
        """
        try:
            return self._walk(obj, 0)[0]
        except Exception:
            # The load-bearing net, not belt and braces: this is what a
            # `RecursionError` or a container that lies about its own shape
            # actually lands in, and `test_a_container_that_refuses_to_be_walked
            # _collapses_to_the_error_marker` holds it. Note what it costs — a
            # failure here is indistinguishable from a body that *contains* the
            # error marker, which is why the depth cap is asserted by the
            # `«redacted:too_deep»` marker rather than by an absence.
            return redaction_marker("error")

    def scrub_text(self, text: str) -> str:
        """The SSE tailer's entry point — one string, no structure."""
        if not isinstance(text, str):
            return text
        return self._scrub_string(text)

    # -- internals --------------------------------------------------------

    def _scrub_string(self, text: str) -> str:
        if not text:
            return text
        literal_re = self._literal_union()
        if literal_re is not None:
            text = literal_re.sub(self._replace_literal, text)
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def _literal_union(self) -> re.Pattern[str] | None:
        """One alternation over every harvested literal, longest first.

        Longest-first matters: a short literal that is a prefix of a longer one
        would otherwise fragment it, leaving the tail of the longer secret in
        the output.
        """
        if self._literal_re is None and self._literals:
            ordered = sorted(self._literals, key=len, reverse=True)
            self._literal_re = re.compile(
                "|".join(_literal_pattern(value) for value in ordered), re.IGNORECASE)
        return self._literal_re

    def _replace_literal(self, match: re.Match[str]) -> str:
        return redaction_marker(self._literals.get(match.group().lower(), "check_value"))

    def _walk(self, obj: Any, depth: int) -> tuple[Any, bool]:
        """Return `(scrubbed, changed)`. `changed` propagates up the tree."""
        if depth > MAX_DEPTH:
            return redaction_marker("too_deep"), True

        if isinstance(obj, str):
            out = self._scrub_string(obj)
            return out, out != obj

        if isinstance(obj, Mapping):
            return self._walk_mapping(obj, depth)

        if isinstance(obj, (list, tuple, set, frozenset)):
            try:
                items = [self._walk(item, depth + 1) for item in obj]
            except Exception:
                return redaction_marker("error"), True
            changed = any(flag for _, flag in items)
            values = [value for value, _ in items]
            try:
                return type(obj)(values), changed     # keep list/tuple/set as it was
            except Exception:
                return values, changed

        # A pydantic model or a dataclass *does* carry strings — `ui.models` is
        # nothing but models — so neither may fall through to the leaf case
        # below. Both collapse to their mapping projection and are then walked
        # like any other mapping, which is also how they pick up the `redacted`
        # flag. Rebuilding the original type is not available: a scrubbed value
        # would have to re-satisfy the field's own validators, and every wire
        # model is `extra="forbid"`.
        if isinstance(obj, BaseModel) or (
                dataclasses.is_dataclass(obj) and not isinstance(obj, type)):
            try:
                projection = (obj.model_dump() if isinstance(obj, BaseModel)
                              else dataclasses.asdict(obj))
            except Exception:
                return redaction_marker("error"), True
            return self._walk_mapping(projection, depth)

        # numbers, bools, None, and anything exotic: no string, nothing to do
        return obj, False

    def _walk_mapping(self, obj: Mapping, depth: int) -> tuple[Any, bool]:
        out: dict[Any, Any] = {}
        changed = False
        try:
            items = list(obj.items())
        except Exception:
            return redaction_marker("error"), True

        for key, value in items:
            new_key = key
            if isinstance(key, str) and key != "redacted":
                new_key = self._scrub_string(key)
                changed = changed or new_key != key
            if (isinstance(key, str) and isinstance(value, str)
                    and _SENSITIVE_KEY_RE.match(key)):
                # The name says credential; the shape is irrelevant.
                new_value = (value if REDACTION_MARKER_RE.fullmatch(value)
                             else redaction_marker("token"))
                changed = changed or new_value != value
            else:
                new_value, sub_changed = self._walk(value, depth + 1)
                changed = changed or sub_changed
            out[new_key] = new_value

        # Task 1 put `redacted: bool` on the models precisely because every one
        # of them is `extra="forbid"`, so this can only ever *set* a key that
        # the object already declared — inventing one would fail re-parsing.
        if changed and "redacted" in out:
            out["redacted"] = True
        return out, changed


def _attr(obj: Any, name: str) -> Any:
    """Read `name` off a pydantic model or a plain mapping, or give up."""
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


# --------------------------------------------------------------------------
# 3. The route class and its one escape hatch
# --------------------------------------------------------------------------

NO_REDACT_ATTR = "__evalyn_no_redact__"


def no_redact(fn):
    """Mark an endpoint exempt from the chokepoint. **Two routes, ever.**

    `/api/meta` and `/api/health` are exempt because they carry no run content
    at all — and `MetaResponse` still makes its own filesystem fields
    display-safe in the model (ruling R4-14), because an exempt route is not an
    unexamined one. Anything that renders a transcript, a finding, a report or
    a log is not a candidate.

    Sets an attribute rather than wrapping, so FastAPI still sees the original
    signature, docstring and annotations of the endpoint it is decorating.
    """
    setattr(fn, NO_REDACT_ATTR, True)
    return fn


def is_no_redact(endpoint: Any) -> bool:
    """True when `endpoint` (or anything it wraps) carries the marker."""
    seen = 0
    while endpoint is not None and seen < 10:
        if getattr(endpoint, NO_REDACT_ATTR, False):
            return True
        endpoint = getattr(endpoint, "__wrapped__", None)
        seen += 1
    return False


_DEFAULT_REDACTOR: Redactor | None = None
_REDACTING_ROUTE: Any = None


def _default_redactor() -> Redactor:
    """Used when the app has not installed one — never "no redaction"."""
    global _DEFAULT_REDACTOR
    if _DEFAULT_REDACTOR is None:
        _DEFAULT_REDACTOR = Redactor()
    return _DEFAULT_REDACTOR


def _redactor_for(request: Any) -> Redactor:
    redactor = getattr(getattr(request, "app", None), "state", None)
    redactor = getattr(redactor, "redactor", None)
    return redactor if isinstance(redactor, Redactor) else _default_redactor()


def _withheld_response():
    """A body that could not be scrubbed is not a body that gets returned."""
    from starlette.responses import Response

    payload = {"error": {
        "code": ErrorCode.unreadable_artifact.value,
        "message": ("response redaction failed; the body was withheld rather than "
                    "returned unredacted"),
    }}
    return Response(content=json.dumps(payload), status_code=500,
                    media_type="application/json")


def _scrub_as_text(redactor: Redactor, body: bytes | bytearray) -> bytes:
    """Scrub a rendered body as UTF-8 text.

    The decode is **strict** on purpose: a `UnicodeDecodeError` is the only
    evidence this module accepts that a body is genuinely binary. A label is
    not evidence — an endpoint can put any string in `media_type`.
    """
    return redactor.scrub_text(bytes(body).decode("utf-8")).encode("utf-8")


def _scrub_response(request: Any, response: Any) -> Any:
    """Rewrite a rendered body in place, or refuse to return it.

    Runs **after** serialization, which is the whole point: it sees exactly the
    bytes the browser would have seen, so no endpoint can arrange for its
    payload to arrive by a route the scrubber does not cover.
    """
    body = getattr(response, "body", None)
    if not isinstance(body, (bytes, bytearray)) or not body:
        return response                      # streaming, file, or empty: not ours
    media = (getattr(response, "media_type", None) or "").lower()
    redactor = _redactor_for(request)

    try:
        if "json" in media:
            try:
                new_body = json.dumps(
                    redactor.scrub(json.loads(body)),
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
            except (ValueError, UnicodeDecodeError):
                # A JSON-labelled body that is not JSON still gets scrubbed as
                # text — degrading to "unparsed" must not degrade to "unread".
                new_body = _scrub_as_text(redactor, body)
        else:
            # Everything else is text until the bytes say otherwise. The default
            # has to be this way round: `media` is `""` for Starlette's bare
            # `Response`, and `application/x-yaml` is the conventional type for
            # the raw view of `FindingDetail.probe_yaml` — i.e. the file with
            # the real address. A content type this function does not recognise
            # must never be a silent opt-out; only `@no_redact` is one.
            new_body = _scrub_as_text(redactor, body)
    except UnicodeDecodeError:
        return response                      # genuinely binary: not text, not ours
    except Exception:
        return _withheld_response()

    if new_body != body:
        response.body = bytes(new_body)
        response.headers["content-length"] = str(len(response.body))
    return response


# --------------------------------------------------------------------------
# 4. The second gate: bodies rendered above the route
# --------------------------------------------------------------------------
#
# `get_route_handler` wraps the *endpoint call*. An `HTTPException` never
# returns from the endpoint — Starlette's `ExceptionMiddleware` catches it and
# renders the body itself, above the route and therefore outside the route
# class entirely. So does every registered handler, and so does the last-resort
# 500. Those bodies are precisely the ones that carry the operator's run
# directory under `$HOME`: "no such run at /Users/alice/…" is the single most
# likely string to appear on a projector when a demo goes wrong.
#
# Hence a second gate with the same fail-closed rule. It is a factory rather
# than a module constant because the app owns the redactor, and because
# building it must not import FastAPI at module import time.

#: HTTP status -> the closed `ErrorCode` set. The 422 mapping is the contract
#: written down in `models.py`: a rejected **write body** is `launch_refused`,
#: a rejected **path or query parameter** is `not_found` (the resource cannot
#: exist, and saying so leaks nothing about the filesystem). `ErrorCode` has no
#: "server error" member, so anything unmapped reuses `unreadable_artifact`
#: with a message that says what actually happened — same stand-in the withheld
#: 500 already makes, and the same open question for the Plan #4 final review.
_STATUS_TO_CODE = {
    400: ErrorCode.launch_refused,
    403: ErrorCode.launch_refused,
    404: ErrorCode.not_found,
    409: ErrorCode.busy,
    422: ErrorCode.launch_refused,
    423: ErrorCode.busy,
    429: ErrorCode.busy,
    503: ErrorCode.busy,
}


def _envelope(redactor: Redactor, code: ErrorCode, message: str, status: int,
              headers: Any = None) -> Any:
    """Render `ErrorEnvelope` — scrubbed whole, not just in the message field."""
    from starlette.responses import Response

    from evalyn.ui.models import ApiError, ErrorEnvelope

    payload = ErrorEnvelope(error=ApiError(code=code, message=message)).model_dump(
        mode="json", exclude_none=True)
    return Response(content=json.dumps(redactor.scrub(payload), ensure_ascii=False),
                    status_code=status, media_type="application/json",
                    headers=headers or None)


def _validation_code(exc: Any) -> ErrorCode:
    """`body` -> `launch_refused`; a path or query parameter -> `not_found`."""
    try:
        locations = {str(error.get("loc", ("",))[0]) for error in exc.errors()}
    except Exception:
        return ErrorCode.launch_refused
    return ErrorCode.launch_refused if "body" in locations else ErrorCode.not_found


def _validation_message(exc: Any) -> str:
    """Name the fields, never quote the input.

    `exc.errors()` carries `input` — the client's own payload verbatim — and a
    rejected body is exactly where a hostile or confused client puts a path.
    Only `loc` and `msg` are echoed, and the whole envelope is scrubbed after.
    """
    try:
        parts = [
            f"{'.'.join(str(piece) for piece in error.get('loc', ()))}: "
            f"{error.get('msg', 'invalid')}"
            for error in exc.errors()[:5]
        ]
    except Exception:
        parts = []
    return "request validation failed" + (f": {'; '.join(parts)}" if parts else "")


def redacting_exception_handlers(redactor: Redactor | None = None) -> dict[Any, Any]:
    """The exception handlers the app **must** mount alongside `RedactingRoute`.

    Mounting `route_class=RedactingRoute` is not sufficient on its own: error
    bodies never pass through the route class. Returns
    `{exception_class: handler}` covering the three classes that render above
    it — `HTTPException` (Starlette's, which FastAPI's subclasses, so keying on
    the base catches both), `RequestValidationError`, and the last-resort
    `Exception`.

    `redactor` pins one for every request; left `None`, each handler resolves
    `app.state.redactor` per request exactly as the route class does, falling
    back to the module default — never to "no redaction".

    Imports live in the body so that `import evalyn.ui.redact` still pulls no
    fastapi and no starlette, for the same reason `RedactingRoute` is lazy.
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException

    def _redactor(request: Any) -> Redactor:
        return redactor if redactor is not None else _redactor_for(request)

    async def http_exception_handler(request: Any, exc: Any) -> Any:
        status = getattr(exc, "status_code", 500)
        return _envelope(
            _redactor(request),
            _STATUS_TO_CODE.get(status, ErrorCode.unreadable_artifact),
            str(getattr(exc, "detail", "") or "request failed"),
            status,
            getattr(exc, "headers", None),
        )

    async def validation_exception_handler(request: Any, exc: Any) -> Any:
        return _envelope(_redactor(request), _validation_code(exc),
                         _validation_message(exc), 422)

    async def unhandled_exception_handler(request: Any, exc: Any) -> Any:
        # The message is dropped, not scrubbed. An unhandled exception's text is
        # arbitrary — a repr of whatever object blew up — so there is nothing to
        # be gained by trying to filter it and a leak to be had by trying.
        return _envelope(
            _redactor(request), ErrorCode.unreadable_artifact,
            "internal error; the details were withheld rather than returned "
            "unredacted (see the terminal running `evalyn ui`)", 500)

    return {
        HTTPException: http_exception_handler,
        RequestValidationError: validation_exception_handler,
        Exception: unhandled_exception_handler,
    }


def _build_redacting_route() -> Any:
    """Built on first access so importing this module needs no FastAPI."""
    from fastapi.routing import APIRoute

    class RedactingRoute(APIRoute):
        """The `/api` router's route class — redaction by default.

        A route added to a router carrying `route_class=RedactingRoute` is
        scrubbed whether or not its author thought about redaction. That is the
        difference between a chokepoint and a convention: forgetting is not one
        of the available outcomes.
        """

        def get_route_handler(self):
            original = super().get_route_handler()
            exempt = is_no_redact(self.endpoint)

            async def redacting_handler(request):
                response = await original(request)
                if exempt:
                    return response
                return _scrub_response(request, response)

            return redacting_handler

    return RedactingRoute


def __getattr__(name: str) -> Any:
    """PEP 562 — `RedactingRoute` materialises here, once, and stays that class.

    Once is load-bearing: the route-table test asserts membership by identity,
    and a fresh class per access would make that assertion quietly never match.
    """
    if name == "RedactingRoute":
        global _REDACTING_ROUTE
        if _REDACTING_ROUTE is None:
            _REDACTING_ROUTE = _build_redacting_route()
        return _REDACTING_ROUTE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
