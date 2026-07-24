from __future__ import annotations

from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.solver import TaskState


def assistant_turns(state: TaskState) -> list[str]:
    return [m.text for m in state.messages if isinstance(m, ChatMessageAssistant)]


def labeled_transcript(state: TaskState) -> str:
    blocks: list[str] = []
    for m in state.messages:
        if isinstance(m, ChatMessageUser):
            blocks.append(f"User: {m.text}")
        elif isinstance(m, ChatMessageAssistant):
            blocks.append(f"Assistant: {m.text}")
    return "\n".join(blocks)
