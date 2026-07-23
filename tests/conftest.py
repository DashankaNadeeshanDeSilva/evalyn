import threading
import time
import httpx
import pytest
from examples.toy_target import Handler
from http.server import ThreadingHTTPServer


@pytest.fixture(scope="session")
def toy_target():
    server = ThreadingHTTPServer(("127.0.0.1", 8899), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    # wait until it answers
    for _ in range(50):
        try:
            httpx.post("http://127.0.0.1:8899/session", json={}, timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    yield "http://127.0.0.1:8899"
    server.shutdown()
