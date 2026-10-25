"""Agent-side gateway client. No actuator API is exposed to a model."""

from typing import Protocol

import httpx

from .contracts import MotionRequest, MotionResult, RobotCapabilities, SceneObservation


class Gateway(Protocol):
    async def scene(self) -> SceneObservation: ...
    async def capabilities(self) -> RobotCapabilities: ...
    async def execute(self, request: MotionRequest) -> MotionResult: ...
    async def status(self, operation_id: str) -> MotionResult: ...
    async def stop(self) -> None: ...
    async def heartbeat(self) -> None: ...


class HttpGateway:
    def __init__(self, url: str, token: str, ca: str | bool = True):
        import ssl

        if not url.startswith("https://"):
            raise ValueError("Robot gateway requires HTTPS")
        verify = ssl.create_default_context(cafile=ca) if isinstance(ca, str) else ca
        self.client = httpx.AsyncClient(
            base_url=url, verify=verify, timeout=5, headers={"Authorization": f"Bearer {token}"}
        )

    async def scene(self) -> SceneObservation:
        response = await self.client.get("/v1/scene")
        response.raise_for_status()
        return SceneObservation.model_validate(response.json())

    async def capabilities(self) -> RobotCapabilities:
        response = await self.client.get("/v1/capabilities")
        response.raise_for_status()
        return RobotCapabilities.model_validate(response.json())

    async def execute(self, request: MotionRequest) -> MotionResult:
        response = await self.client.post("/v1/operations", json=request.model_dump())
        response.raise_for_status()
        return self._result(response, request.operation_id)

    async def status(self, operation_id: str) -> MotionResult:
        response = await self.client.get(f"/v1/operations/{operation_id}")
        response.raise_for_status()
        return self._result(response, operation_id)

    @staticmethod
    def _result(response: httpx.Response, operation_id: str) -> MotionResult:
        result = MotionResult.model_validate(response.json())
        if result.operation_id != operation_id:
            raise ValueError("gateway_operation_mismatch")
        return result

    async def stop(self) -> None:
        response = await self.client.post("/v1/stop")
        response.raise_for_status()

    async def heartbeat(self) -> None:
        response = await self.client.post("/v1/heartbeat")
        response.raise_for_status()

    async def close(self) -> None:
        await self.client.aclose()
