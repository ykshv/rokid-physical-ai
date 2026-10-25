import base64
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytest

from rokid_physical_ai.contracts import (
    MotionResult,
    PlacementZone,
    RobotCapabilities,
    SceneObject,
    SceneObservation,
    Vector3,
)
from rokid_physical_ai.frames import FrameBuffer
from rokid_physical_ai.store import Store


@pytest.fixture
def scene():
    return SceneObservation(
        revision="scene_1",
        observed_at=time.time(),
        calibration_id="cal_1",
        calibrated=True,
        objects=[
            SceneObject(
                id="cube",
                label="синий кубик",
                center=Vector3(x=0.4, y=0, z=0.025),
                size=Vector3(x=0.04, y=0.04, z=0.05),
                grasp_width=0.04,
            )
        ],
        zones=[
            PlacementZone(
                id="tray", label="справа", center=Vector3(x=0.4, y=0.15, z=0), radius=0.07
            )
        ],
    )


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "test.sqlite3")
    yield result
    result.close()


@pytest.fixture
def frames():
    result = FrameBuffer()
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))
    assert ok
    result.add("frame_1", base64.b64encode(jpeg).decode())
    return result


@dataclass
class TestGateway:
    __test__ = False
    observation: SceneObservation
    operations: list = field(default_factory=list)
    stopped: int = 0
    result: str = "succeeded"
    fail_execute: bool = False

    async def scene(self):
        return self.observation

    async def capabilities(self):
        return RobotCapabilities(
            robot="simulation",
            min_corner=Vector3(x=0.2, y=-0.3, z=0),
            max_corner=Vector3(x=0.7, y=0.3, z=0.5),
            max_grasp_width=0.08,
        )

    async def execute(self, request):
        self.operations.append(request)
        if self.fail_execute:
            raise TimeoutError("response lost after acceptance")
        return MotionResult(operation_id=request.operation_id, state=self.result)

    async def status(self, operation_id):
        return MotionResult(operation_id=operation_id, state=self.result)

    async def heartbeat(self):
        return None

    async def stop(self):
        self.stopped += 1
        self.result = "cancelled"


@pytest.fixture
def gateway(scene):
    return TestGateway(scene)
