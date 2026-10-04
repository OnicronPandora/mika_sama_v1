"""Server state (spec: shutting_down, client_status, service_status, personality, current_emotion).

The Mac is the only machine that owns state (decision 2026-09-26). All of it lives on the server's single
event loop, so it needs no locks.
"""

from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from mika_shared.enums import ClientComponent, ComponentState, Emotion
from mika_shared.events import ClientStatus

from ..personality.engine import Personality


class ServerState(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)  # one per server run; stored with every chat log
    shutting_down: bool = False
    client_status: dict[ClientComponent, ComponentState] = Field(default_factory=dict)
    service_status: dict[str, str] = Field(default_factory=dict)  # e.g. {"database": "ok", "ollama": "ok"}
    personality: dict = Field(default_factory=dict)  # decision #10: default_factory, not Field(dict)
    current_emotion: Emotion = Emotion.NEUTRAL


class StateManager:
    def __init__(self, personality: Personality) -> None:
        self.state = ServerState(personality=personality.model_dump())

    def on_client_status(self, event: ClientStatus) -> None:
        self.state.client_status[event.component] = event.status

    def set_service(self, name: str, status: str) -> None:
        self.state.service_status[name] = status

    def set_emotion(self, emotion: Emotion) -> None:
        self.state.current_emotion = emotion

    def begin_shutdown(self) -> None:
        self.state.shutting_down = True

    def client_ready(self, component: ClientComponent) -> bool:
        return self.state.client_status.get(component) is ComponentState.READY
