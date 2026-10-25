import time

import httpx
import pytest

from rokid_physical_ai.contracts import MotionRequest, TaskIntent
from rokid_physical_ai.gateway import HttpGateway


@pytest.mark.parametrize("method", ["execute", "status"])
@pytest.mark.parametrize("matches", [True, False])
async def test_transport_binds_result_to_requested_operation(scene, method, matches):
    operation_id = "a" * 32
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "operation_id": operation_id if matches else "b" * 32,
                "state": "succeeded",
            },
        )

    gateway = HttpGateway("https://gateway.invalid", "test-only-token")
    await gateway.close()
    gateway.client = httpx.AsyncClient(
        base_url="https://gateway.invalid", transport=httpx.MockTransport(respond)
    )
    argument = (
        operation_id
        if method == "status"
        else MotionRequest(
            operation_id=operation_id,
            scene=scene,
            expires_at=time.time() + 2,
            intent=TaskIntent(
                object_id="cube",
                destination_id="tray",
                scene_revision=scene.revision,
                keyframe_id="frame_1",
            ),
        )
    )
    try:
        if matches:
            result = await getattr(gateway, method)(argument)
            assert result.state == "succeeded"
        else:
            with pytest.raises(ValueError, match="gateway_operation_mismatch"):
                await getattr(gateway, method)(argument)
        assert len(seen) == 1  # No retry, including after a protocol error.
    finally:
        await gateway.close()
