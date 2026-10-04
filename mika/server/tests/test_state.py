import pytest

from app.personality.engine import Personality
from app.state.manager import ServerState, StateManager
from app.turn.intent import decide_intent
from mika_shared.enums import ClientComponent, ComponentState, Emotion, FilterAction, Intent
from mika_shared.events import ClientStatus

MIKA = Personality(name="Mika-sama", role="AI VTuber", core_identity="You are Mika-sama.", guidelines=[])


def test_state_defaults_are_independent_per_instance():
    first, second = ServerState(), ServerState()
    first.personality["x"] = 1
    first.client_status[ClientComponent.TTS] = ComponentState.READY
    assert second.personality == {} and second.client_status == {}  # default_factory, not a shared dict
    assert first.session_id != second.session_id
    assert (first.shutting_down, first.current_emotion) == (False, Emotion.NEUTRAL)


def test_manager_tracks_clients_services_and_emotion():
    manager = StateManager(MIKA)
    assert manager.state.personality["name"] == "Mika-sama"
    manager.on_client_status(ClientStatus(component=ClientComponent.TTS, status=ComponentState.READY))
    manager.on_client_status(ClientStatus(component=ClientComponent.STT, status=ComponentState.ERROR, detail="no mic"))
    assert manager.client_ready(ClientComponent.TTS)
    assert not manager.client_ready(ClientComponent.STT)
    assert not manager.client_ready(ClientComponent.AVATAR_PAGE)
    manager.set_service("database", "ok")
    manager.set_emotion(Emotion.SAD)
    manager.begin_shutdown()
    state = manager.state
    assert (state.service_status, state.current_emotion, state.shutting_down) == ({"database": "ok"}, Emotion.SAD, True)


@pytest.mark.parametrize(
    ("actions", "failed", "intent"),
    [
        ([], False, Intent.CASUAL_CONVERSATION),
        ([FilterAction.ALLOW, FilterAction.ALLOW], False, Intent.CASUAL_CONVERSATION),
        ([FilterAction.ALLOW, FilterAction.REPLACE], False, Intent.FILTER_INCIDENT),
        ([FilterAction.BLOCK], False, Intent.FILTER_INCIDENT),
        ([FilterAction.BLOCK], True, Intent.ERROR_RECOVERY),
        ([], True, Intent.ERROR_RECOVERY),
    ],
)
def test_intent_is_decided_by_the_system(actions, failed, intent):
    assert decide_intent(actions, failed=failed) is intent
