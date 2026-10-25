import base64
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rokid_physical_ai.app import Settings, create_app
from rokid_physical_ai.contracts import TaskIntent, Vector3
from rokid_physical_ai.frames import FrameBuffer
from rokid_physical_ai.perception import rigid_transform


def test_pairing_code_is_single_use_and_credentials_hashed(store):
    code = store.pairing_code()
    device, token = store.pair(code)
    assert store.authenticate(token) == device
    assert store.authenticate("wrong") is None
    with pytest.raises(ValueError):
        store.pair(code)
    raw = store.db.execute("SELECT hash FROM devices").fetchone()[0]
    assert token not in raw


def test_expired_pairing_is_rejected(store):
    code = store.pairing_code()
    store.db.execute("UPDATE pairing SET expires=?", (time.time() - 1,))
    store.db.commit()
    with pytest.raises(ValueError):
        store.pair(code)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_coordinates_rejected(value):
    with pytest.raises(ValidationError):
        Vector3(x=value, y=0, z=0)


@pytest.mark.parametrize("extra", ["joint_positions", "shell", "python", "force", "confirmed"])
def test_model_cannot_add_actuator_or_authority_fields(extra):
    with pytest.raises(ValidationError):
        TaskIntent.model_validate(
            dict(
                object_id="x",
                destination_id="y",
                scene_revision="z",
                keyframe_id="f",
                **{extra: True},
            )
        )


def test_frame_memory_is_bounded_and_duplicate_ids_rejected():
    frames = FrameBuffer()
    _, data = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))
    encoded = base64.b64encode(data).decode()
    for i in range(100):
        frames.add(f"f_{i}", encoded)
    assert len(frames.frames) == 50
    with pytest.raises(ValueError):
        frames.add("f_99", encoded)
    with pytest.raises(ValueError):
        frames.get("f_0")


def test_registration_rejects_degenerate_and_bad_correspondences():
    with pytest.raises(ValueError):
        rigid_transform(np.zeros((4, 3)), np.zeros((4, 3)))
    source = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
    target = source + [0.1, 0.2, 0.3]
    np.testing.assert_allclose(rigid_transform(source, target)[:3, 3], [0.1, 0.2, 0.3])
    target[-1, 2] += 0.1
    with pytest.raises(ValueError):
        rigid_transform(source, target)


def test_http_health_and_pairing(tmp_path):
    app = create_app(Settings(tmp_path, diagnostic=True))
    code = app.state.store.pairing_code()
    with TestClient(app) as client:
        assert client.get("/healthz").json()["diagnostic"] is True
        response = client.post("/v1/pair", json={"code": code})
        assert response.status_code == 200
        assert client.post("/v1/pair", json={"code": code}).status_code == 401


def test_unauthenticated_websocket_is_rejected(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    app = create_app(Settings(tmp_path, diagnostic=True))
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/control"):
            pytest.fail("Unauthenticated websocket accepted")


def test_real_control_media_protocol_without_provider_or_camera(tmp_path):
    app = create_app(Settings(tmp_path, diagnostic=True))
    _, token = app.state.store.pair(app.state.store.pairing_code())
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        with client.websocket_connect("/v1/control", headers=headers) as control:
            session = control.receive_json()["session_id"]
            with client.websocket_connect(f"/v1/media/{session}", headers=headers) as media:
                control.send_json({"type": "session.start"})
                assert control.receive_json()["type"] == "session.started"
                assert media.receive_json()["type"] == "audio"
                # Diagnostic playback acknowledgements must not require an OpenAI connection.
                control.send_json(
                    {"type": "audio.played", "item_id": "diagnostic-tone", "milliseconds": 200}
                )
                media.send_bytes(b"\0" * 960)
                control.send_json({"type": "heartbeat"})
                control.send_json({"type": "session.stop"})
