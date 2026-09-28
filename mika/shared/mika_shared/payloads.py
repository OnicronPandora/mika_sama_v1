"""Payloads from the spec: the request, one filter verdict, and one turn's result."""

from pydantic import Field, model_validator

from .base import Contract, NonEmptyStr
from .enums import Emotion, FilterAction, Intent


class UserRequest(Contract):
    """Request payload (Acer -> Mac). The server builds history, RAG context and the prompt itself."""

    user_id: NonEmptyStr
    message: NonEmptyStr


class FilterResult(Contract):
    """The output filter's verdict for one sentence."""

    action: FilterAction
    filter_response: str | None = Field(
        default=None,
        description="What is spoken instead: the REPLACE toast or the BLOCK replacement. None for ALLOW.",
    )
    reason: str | None = None

    @model_validator(mode="after")
    def _response_matches_action(self) -> "FilterResult":
        if self.action is FilterAction.ALLOW and self.filter_response is not None:
            raise ValueError("an ALLOW verdict has no filter_response")
        if self.action is not FilterAction.ALLOW and not (self.filter_response or "").strip():
            raise ValueError(f"a {self.action} verdict needs a filter_response")
        return self


class TurnResult(Contract):
    """Response payload: what one turn produced. Saved to chat_logs and the FIFO cache."""

    intent: Intent
    emotion: Emotion
    reply: str = Field(description="What was actually spoken, after filtering.")
    original_reply: str = Field(description="The raw LLM output.")
    action: FilterAction = Field(description="The most severe sentence action in the turn (FilterAction.most_severe).")
