import pytest
from evalyn.targets.streams import parse_stream, StreamFormatError

def test_vercel_ai_frames():
    lines = ['0:"Hello "', '0:"world"', 'd:{"finishReason":"stop"}']
    assert parse_stream("vercel-ai", lines) == "Hello world"

def test_raw_sse_data_lines():
    lines = ["data: Hello ", "data: world", "data: [DONE]"]
    assert parse_stream("raw-sse", lines) == "Hello world"

def test_json_delta_lines():
    lines = ['{"delta": "Hello "}', '{"delta": "world"}']
    assert parse_stream("json", lines) == "Hello world"

def test_unknown_format_raises():
    with pytest.raises(StreamFormatError):
        parse_stream("mystery", ["x"])
