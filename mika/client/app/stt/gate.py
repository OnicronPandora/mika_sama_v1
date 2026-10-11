"""Half-duplex: the microphone is muted while Mika answers, so she never transcribes her own voice (spec).

Muted from the moment a message goes to the Mac (typed or spoken) until the reply is over:
- the avatar page reports that the reply's last audio chunk finished playing (playback_finished at last_seq),
  then a short echo guard passes;
- or the reply had nothing to play (turn_end without sentences, or an error);
- or nobody reports playback in time (no avatar page, or a page that stopped answering): the wait ends after
  the reply's audio length plus a margin.

Every message is answered by exactly one turn or one error, in order, so the gate counts messages still waiting
for their turn and turns still playing. Losing the Mac's connection resets it.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class _Turn:
    last_seq: int | None = None  # known once the turn has been spoken in full
    deadline: float | None = None  # when to stop waiting for the page's playback report
    finished_seq: int = -1  # the highest seq the page has finished playing


class HalfDuplexGate:
    def __init__(self, *, echo_guard: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._echo_guard = echo_guard
        self._clock = clock
        self._waiting = 0  # messages sent whose turn hasn't started yet
        self._turns: dict[str, _Turn] = {}  # turns started and not yet over
        self._quiet_until = 0.0  # the echo guard after the last turn

    @property
    def muted(self) -> bool:
        now = self._clock()
        for turn_id, turn in list(self._turns.items()):
            if turn.deadline is not None and now >= turn.deadline:
                log.warning("No playback report for turn %s; unmuting the microphone anyway", turn_id)
                self._finish(turn_id)
        return self._waiting > 0 or bool(self._turns) or now < self._quiet_until

    def message_sent(self) -> None:
        self._waiting += 1

    def message_refused(self) -> None:
        """The Mac answered a message with an error instead of a turn."""
        self._waiting = max(0, self._waiting - 1)

    def turn_started(self, turn_id: str) -> None:
        self._waiting = max(0, self._waiting - 1)
        self._turns[turn_id] = _Turn()

    def turn_spoken(self, turn_id: str, last_seq: int | None, *, wait: float | None) -> None:
        """All of the turn's audio has gone to the avatar page. wait: how long its playback can still take
        (None if there is nothing to play, or no page to play it)."""
        turn = self._turns.get(turn_id)
        if turn is None:
            return
        if last_seq is None or wait is None or turn.finished_seq >= last_seq:
            self._finish(turn_id)
        else:
            turn.last_seq, turn.deadline = last_seq, self._clock() + wait

    def playback_finished(self, turn_id: str, seq: int) -> None:
        turn = self._turns.get(turn_id)
        if turn is None:
            return
        turn.finished_seq = max(turn.finished_seq, seq)
        if turn.last_seq is not None and seq >= turn.last_seq:
            self._finish(turn_id)

    def turn_failed(self, turn_id: str) -> None:
        """An error for this turn: its sentences, if any, won't come."""
        if turn_id in self._turns:
            del self._turns[turn_id]
        else:  # the turn failed before it started
            self._waiting = max(0, self._waiting - 1)

    def reset(self) -> None:
        """The connection to the Mac was lost: no reply is coming."""
        self._waiting = 0
        self._turns.clear()

    def _finish(self, turn_id: str) -> None:
        del self._turns[turn_id]
        self._quiet_until = self._clock() + self._echo_guard
