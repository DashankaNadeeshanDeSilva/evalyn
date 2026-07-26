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


def test_named_sse_event_type_resets_at_dispatch_boundary():
    # PR #4 fix #7 (SSE spec): the event type resets after each blank-line
    # dispatch — a later UNNAMED data frame must NOT inherit `event: token`
    lines = ['event: token', 'data: {"content":"hello"}', '',
             'data: {"content":" world"}', '']
    assert parse_stream("named-sse", lines, event="token", field="content") == "hello"


def test_named_sse_unnamed_frame_belongs_to_default_message_event():
    # per SSE spec a data frame with no event name is the "message" event —
    # matched only when the pack asks for event_name "message"
    lines = ['data: {"content":"hi"}', '']
    assert parse_stream("named-sse", lines, event="message", field="content") == "hi"
    assert parse_stream("named-sse", lines, event="token", field="content") == ""


def test_named_sse_early_error_event_does_not_poison_later_unnamed_frames():
    # a dispatched `event: error` block must not make every later unnamed
    # data frame raise
    lines = ['event: error', 'data: {"message":"transient"}']
    with pytest.raises(StreamFormatError):
        parse_stream("named-sse", lines, event="token", field="content")
    lines = ['event: error', '', 'data: {"content":"ok"}', '']
    assert parse_stream("named-sse", lines, event="token", field="content") == ""


def test_vercel_malformed_frame_raises_streamformaterror():
    with pytest.raises(StreamFormatError):
        parse_stream("vercel-ai", ['0:{not json'])


def test_vercel_error_frames_raise():
    # ONLY `3:` is the AI SDK error part
    with pytest.raises(StreamFormatError):
        parse_stream("vercel-ai", ['3:"boom"'])


def test_vercel_finish_step_and_lifecycle_frames_are_not_errors():
    # round-2 N5: `e:` is the AI SDK finish-STEP part, `f:` start-step and `d:`
    # finish-message — lifecycle frames every real AI SDK stream emits; they
    # must be consumed silently, never raised as errors
    lines = ['f:{"messageId":"m1"}', '0:"Hello "', '0:"world"',
             'e:{"finishReason":"stop"}', 'd:{"finishReason":"stop"}']
    assert parse_stream("vercel-ai", lines) == "Hello world"


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
