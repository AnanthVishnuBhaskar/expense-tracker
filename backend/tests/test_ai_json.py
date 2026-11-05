from types import SimpleNamespace

import pytest

from app.config import Settings
from app.pipeline.ai import AIError, AnthropicReceiptAI
from app.pipeline.schemas import QualityCheck


class FakeMessages:
    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=self.replies.pop(0))],
            usage=None,
            _request_id="req_abc",
        )


def make_ai(replies: list[str]) -> tuple[AnthropicReceiptAI, FakeMessages]:
    messages = FakeMessages(replies)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicReceiptAI(Settings(), client=client), messages


GOOD = (
    '{"is_receipt": true, "readable": true, "receipt_count": 1, "issues": [], "retake_hint": null}'
)


def ask(ai: AnthropicReceiptAI) -> QualityCheck:
    return ai._json(model="m", content=[{"type": "text", "text": "hi"}], schema=QualityCheck)


def test_json_reply_wrapped_in_a_code_fence_is_read():
    ai, messages = make_ai([f"Here you go:\n```json\n{GOOD}\n```"])
    assert ask(ai).receipt_count == 1
    assert len(messages.calls) == 1


def test_invalid_json_is_retried_once_with_the_error():
    ai, messages = make_ai(['{"is_receipt": true}', GOOD])
    assert ask(ai).is_receipt
    retry = messages.calls[1]["messages"]
    assert retry[1]["role"] == "assistant" and "did not match" in retry[2]["content"]


def test_invalid_json_twice_is_a_clear_error():
    ai, _ = make_ai(["no json here", "still none"])
    with pytest.raises(AIError, match="could not be understood"):
        ask(ai)
