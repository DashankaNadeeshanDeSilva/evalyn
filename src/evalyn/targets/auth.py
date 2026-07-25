from __future__ import annotations
from evalyn.targets.schema import AuthSpec


def auth_headers(spec: AuthSpec) -> dict[str, str]:
    if spec.kind == "bearer":
        return {"Authorization": f"Bearer {spec.token or ''}"}
    if spec.kind == "header":
        return {spec.header_name or "X-API-Key": spec.token or ""}
    return {}
