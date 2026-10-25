"""Device-to-agent control messages; unknown fields never grant authority."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, TypeAdapter

from .contracts import Contract, Identifier


class Signal(Contract):
    type: Literal["heartbeat", "session.start", "session.stop"]


class PreviewPlayed(Contract):
    type: Literal["preview.played"]
    task_id: Identifier


class AudioPlayed(Contract):
    type: Literal["audio.played"]
    item_id: Identifier
    milliseconds: Annotated[StrictInt, Field(ge=0)]


class Diagnostics(Contract):
    type: Literal["diagnostics"]
    camera: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    aec: StrictBool
    tts_ru: StrictBool


type ControlEvent = Annotated[
    Signal | PreviewPlayed | AudioPlayed | Diagnostics, Field(discriminator="type")
]
# Pydantic supports PEP 695 aliases at runtime; its constructor stub expects a class.
CONTROL_EVENT = TypeAdapter[ControlEvent](ControlEvent)  # type: ignore[arg-type]
