"""Versioned boundaries shared by the agent, perception and robot gateway."""

import math
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Number = Annotated[float, Field(allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Vector3(Contract):
    x: Number
    y: Number
    z: Number

    def distance(self, other: Vector3) -> float:
        return math.dist((self.x, self.y, self.z), (other.x, other.y, other.z))


class SceneObject(Contract):
    id: Identifier
    label: str = Field(min_length=1, max_length=80)
    center: Vector3
    size: Vector3
    yaw: Number = 0.0
    grasp_width: float = Field(gt=0, le=0.2, allow_inf_nan=False)

    @field_validator("size")
    @classmethod
    def positive_size(cls, value: Vector3) -> Vector3:
        if min(value.x, value.y, value.z) <= 0:
            raise ValueError("Object dimensions must be positive")
        return value


class PlacementZone(Contract):
    id: Identifier
    label: str = Field(min_length=1, max_length=80)
    center: Vector3
    radius: float = Field(gt=0, le=0.5, allow_inf_nan=False)


class SceneObservation(Contract):
    version: Literal[1] = 1
    revision: Identifier
    frame_id: Identifier = "robot_base"
    observed_at: Number
    calibration_id: Identifier
    calibrated: bool
    objects: list[SceneObject] = Field(max_length=20)
    zones: list[PlacementZone] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_ids(self) -> SceneObservation:
        ids = [o.id for o in self.objects] + [z.id for z in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("Scene IDs must be unique")
        return self


class TaskIntent(Contract):
    action: Literal["pick_place"] = "pick_place"
    object_id: Identifier
    destination_id: Identifier
    scene_revision: Identifier
    keyframe_id: Identifier


class RobotCapabilities(Contract):
    robot: Literal["fr3", "xarm6", "simulation"]
    actions: tuple[Literal["pick_place"], ...] = ("pick_place",)
    frame_id: Identifier = "robot_base"
    min_corner: Vector3
    max_corner: Vector3
    max_grasp_width: float = Field(gt=0, le=0.2)
    hardware_qualified: bool = False

    def contains(self, position: Vector3) -> bool:
        return all(
            lo <= p <= hi
            for lo, p, hi in zip(
                self.min_corner.model_dump().values(),
                position.model_dump().values(),
                self.max_corner.model_dump().values(),
                strict=True,
            )
        )


class TaskState(StrEnum):
    PROPOSED = "proposed"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


class TaskExecution(Contract):
    id: Identifier
    session_id: Identifier
    intent: TaskIntent
    state: TaskState
    preview: str
    created_at: Number
    updated_at: Number
    reason: str | None = None


class MotionRequest(Contract):
    version: Literal[1] = 1
    operation_id: Identifier
    scene: SceneObservation
    intent: TaskIntent
    expires_at: Number


class MotionResult(Contract):
    operation_id: Identifier
    state: Literal["executing", "succeeded", "failed", "cancelled", "uncertain"]
    reason: str | None = None


class Proposal(Contract):
    object_id: Identifier
    destination_id: Identifier
    scene_revision: Identifier
    keyframe_id: Identifier
