"""Half-duplex: the microphone stays muted from a message until Mika's reply has finished playing."""

from app.stt.gate import HalfDuplexGate


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def gate() -> tuple[HalfDuplexGate, Clock]:
    clock = Clock()
    return HalfDuplexGate(echo_guard=0.5, clock=clock), clock


def test_muted_until_the_last_sentence_has_played_then_the_echo_guard():
    g, clock = gate()
    assert not g.muted
    g.message_sent()
    assert g.muted  # waiting for Mika
    g.turn_started("t1")
    g.turn_spoken("t1", last_seq=1, wait=30)
    g.playback_finished("t1", 0)
    assert g.muted  # one sentence still playing
    g.playback_finished("t1", 1)
    assert g.muted  # the echo guard
    clock.now += 0.5
    assert not g.muted


def test_a_playback_report_before_the_turn_is_spoken_counts():
    g, clock = gate()
    g.message_sent()
    g.turn_started("t1")
    g.playback_finished("t1", 0)  # the page finished the only sentence before turn_end reached the speaker
    g.turn_spoken("t1", last_seq=0, wait=30)
    clock.now += 0.5
    assert not g.muted


def test_nothing_to_play_unmutes_at_once():
    g, clock = gate()
    g.message_sent()
    g.turn_started("t1")
    g.turn_spoken("t1", last_seq=None, wait=30)  # a reply without sentences
    clock.now += 0.5
    assert not g.muted
    g.message_sent()
    g.turn_started("t2")
    g.turn_spoken("t2", last_seq=2, wait=None)  # no avatar page to play it
    clock.now += 0.5
    assert not g.muted


def test_without_a_playback_report_the_wait_runs_out():
    g, clock = gate()
    g.message_sent()
    g.turn_started("t1")
    g.turn_spoken("t1", last_seq=1, wait=8)
    clock.now += 7.9
    assert g.muted
    clock.now += 0.1
    assert g.muted  # the wait is over; now the echo guard
    clock.now += 0.5
    assert not g.muted


def test_errors_unmute():
    g, _ = gate()
    g.message_sent()
    g.message_refused()  # "Mika is busy"
    assert not g.muted
    g.message_sent()
    g.turn_failed("t1")  # failed before turn_start
    assert not g.muted
    g.message_sent()
    g.turn_started("t2")
    g.turn_failed("t2")  # failed after turn_start, before any sentence
    assert not g.muted


def test_two_messages_keep_it_muted_until_both_replies_are_over():
    g, clock = gate()
    g.message_sent()
    g.message_sent()  # Pandora typed while Mika was answering
    g.turn_started("t1")
    g.turn_spoken("t1", last_seq=0, wait=30)
    g.playback_finished("t1", 0)
    clock.now += 1
    assert g.muted  # the second reply hasn't started
    g.turn_started("t2")
    g.turn_spoken("t2", last_seq=0, wait=30)
    g.playback_finished("t2", 0)
    clock.now += 1
    assert not g.muted


def test_losing_the_mac_unmutes():
    g, _ = gate()
    g.message_sent()
    g.turn_started("t1")
    g.reset()
    assert not g.muted
    g.playback_finished("t1", 0)  # late reports for forgotten turns are ignored
    g.turn_spoken("t1", last_seq=0, wait=30)
    assert not g.muted
