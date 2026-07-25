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


def test_named_sse_extracts_content_by_event_and_field():
    lines = ['event: token', 'data: {"type":"token","content":"Hello "}', '',
             'event: token', 'data: {"type":"token","content":"world"}', '',
             'event: done', 'data: {"type":"done"}', '']
    out = parse_stream("named-sse", lines, event="token", field="content")
    assert out == "Hello world"


def test_named_sse_error_event_raises():
    lines = ['event: error', 'data: {"type":"error","message":"boom"}', '']
    with pytest.raises(StreamFormatError):
        parse_stream("named-sse", lines, event="token", field="content")


def test_vercel_malformed_frame_raises_streamformaterror():
    with pytest.raises(StreamFormatError):
        parse_stream("vercel-ai", ['0:{not json'])


def test_vercel_error_frames_raise():
    for frame in ['3:"boom"', 'e:{"error":"boom"}']:
        with pytest.raises(StreamFormatError):
            parse_stream("vercel-ai", [frame])


def test_named_sse_defaults_to_token_content():
    lines = ['event: token', 'data: {"content":"hi"}', '']
    assert parse_stream("named-sse", lines) == "hi"


def test_named_sse_malformed_data_raises():
    lines = ['event: token', 'data: {not json', '']
    with pytest.raises(StreamFormatError):
        parse_stream("named-sse", lines, event="token", field="content")


def test_named_sse_handles_crlf_line_endings():
    lines = ['event: token\r', 'data: {"content":"hi"}\r', '\r']
    assert parse_stream("named-sse", lines, event="token", field="content") == "hi"


def test_raw_sse_strips_exactly_one_leading_space():
    # SSE spec: exactly one space after "data:" is separator; extras are payload
    lines = ["data: x", "data:  y", "data: [DONE]"]
    assert parse_stream("raw-sse", lines) == "x y"


def test_json_malformed_line_raises():
    with pytest.raises(StreamFormatError):
        parse_stream("json", ['{not json'])
