"""Intent is set by the system, never by the LLM (decision 2026-09-27)."""

from collections.abc import Iterable

from mika_shared.enums import FilterAction, Intent


def decide_intent(actions: Iterable[FilterAction], *, failed: bool = False) -> Intent:
    """error_recovery if the turn failed, filter_incident if any sentence was filtered, else casual."""
    if failed:
        return Intent.ERROR_RECOVERY
    if any(action is not FilterAction.ALLOW for action in actions):
        return Intent.FILTER_INCIDENT
    return Intent.CASUAL_CONVERSATION
