from __future__ import annotations
import json
from typing import Iterable


class StreamFormatError(Exception): ...


def parse_stream(event_format: str, lines: Iterable[str]) -> str:
    if event_format == "vercel-ai":
        out = []
        for line in lines:
            if line.startswith("0:"):
                out.append(json.loads(line[2:]))
            # d:{...} done frame ignored
        return "".join(out).strip()
    if event_format == "raw-sse":
        out = []
        for line in lines:
            if line.startswith("data:"):
                payload = line[len("data:"):].lstrip()
                if payload == "[DONE]":
                    break
                out.append(payload)
        return "".join(out).strip()
    if event_format == "json":
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            out.append(obj.get("delta") or obj.get("text") or "")
        return "".join(out).strip()
    raise StreamFormatError(f"unknown event_format: {event_format!r}")
