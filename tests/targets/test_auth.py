from evalyn.targets.auth import auth_headers
from evalyn.targets.schema import AuthSpec


def test_bearer():
    assert auth_headers(AuthSpec(kind="bearer", token="t")) == {"Authorization": "Bearer t"}


def test_header():
    assert auth_headers(AuthSpec(kind="header", header_name="X-Key", token="t")) == {"X-Key": "t"}


def test_none():
    assert auth_headers(AuthSpec(kind="none")) == {}
