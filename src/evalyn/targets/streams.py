from __future__ import annotations
import json
from typing import Iterable


class StreamFormatError(Exception): ...


def _strip_one_space(s: str) -> str:
    return s[1:] if s.startswith(" ") else s


def parse_stream(event_format: str, lines: Iterable[str], *,
                 event: str | None = None, field: str | None = None) -> str:
    lines = list(lines)
    if event_format == "vercel-ai":
        out = []
        for line in lines:
            if line.startswith("0:"):
                try:
                    out.append(json.loads(line[2:]))
                except (json.JSONDecodeError, TypeError) as e:
                    raise StreamFormatError(f"bad vercel-ai frame: {line!r}") from e
            elif line.startswith(("3:", "e:")):
                raise StreamFormatError(f"vercel-ai error frame: {line!r}")
        return "".join(out).strip()
    if event_format == "raw-sse":
        out = []
        for line in lines:
            if line.startswith("data:"):
                payload = _strip_one_space(line[len("data:"):])
                if payload == "[DONE]":
                    break
                out.append(payload)
        return "".join(out).strip()
    if event_format == "named-sse":
        ev = event or "token"
        fld = field or "content"
        cur_event = None
        out = []
        for line in lines:
            line = line.rstrip("\r")
            if line.startswith("event:"):
                cur_event = _strip_one_space(line[len("event:"):])
            elif line.startswith("data:"):
                payload = _strip_one_space(line[len("data:"):])
                if cur_event == "error":
                    raise StreamFormatError(f"named-sse error event: {payload}")
                if cur_event == ev:
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError as e:
                        raise StreamFormatError(f"bad named-sse data: {payload!r}") from e
                    out.append(str(obj.get(fld, "")))
        return "".join(out).strip()
    if event_format == "json":
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise StreamFormatError(f"bad json line: {line!r}") from e
            out.append(obj.get("delta") or obj.get("text") or "")
        return "".join(out).strip()
    raise StreamFormatError(f"unknown event_format: {event_format!r}")
