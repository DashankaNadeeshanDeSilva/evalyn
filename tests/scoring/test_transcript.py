from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput
from inspect_ai.solver import TaskState
from evalyn.scoring.transcript import assistant_turns, labeled_transcript


def _state(pairs):
    st = TaskState(model="m", sample_id="s", epoch=1, input="x", messages=[])
    for u, a in pairs:
        st.messages.append(ChatMessageUser(content=u))
        st.messages.append(ChatMessageAssistant(content=a))
    st.output = ModelOutput.from_content(model="m", content=pairs[-1][1])
    return st


def test_assistant_turns_returns_each_reply_in_order():
    st = _state([("hi", "hello"), ("leak?", "SYSTEM PROMPT: secret")])
    assert assistant_turns(st) == ["hello", "SYSTEM PROMPT: secret"]


def test_labeled_transcript_includes_both_roles():
    st = _state([("hi", "hello")])
    t = labeled_transcript(st)
    assert "User: hi" in t and "Assistant: hello" in t
