"""Exercise actual ASGI handshakes with a deterministic transport barrier."""

import asyncio
import json

import pytest

from rokid_physical_ai.app import Settings, create_app


class Socket:
    def __init__(self, app, path, token, accept_gate=None):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.accepting = asyncio.Event()
        self.accept_gate = accept_gate
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "wss",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("testclient", 123),
            "server": ("testserver", 443),
            "subprotocols": [],
            "root_path": "",
        }
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(scope, self.incoming.get, self.send))

    async def send(self, message):
        if message["type"] == "websocket.accept":
            self.accepting.set()
            if self.accept_gate:
                await self.accept_gate.wait()
        await self.outgoing.put(message)

    async def receive(self):
        return await asyncio.wait_for(self.outgoing.get(), 2)

    async def close(self):
        if self.accept_gate:
            self.accept_gate.set()
        self.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self.task, 3)


@pytest.mark.parametrize("channel", ["control", "media"])
async def test_concurrent_handshake_cannot_take_second_session_or_media_lease(tmp_path, channel):
    app = create_app(Settings(tmp_path, diagnostic=True))
    _, token = app.state.store.pair(app.state.store.pairing_code())
    sockets = []
    gate = asyncio.Event()
    async with app.router.lifespan_context(app):
        try:
            path = "/v1/control"
            if channel == "media":
                control = Socket(app, path, token)
                sockets.append(control)
                assert (await control.receive())["type"] == "websocket.accept"
                ready = json.loads((await control.receive())["text"])
                path = f"/v1/media/{ready['session_id']}"
            first = Socket(app, path, token, gate)
            sockets.append(first)
            await asyncio.wait_for(first.accepting.wait(), 2)
            second = Socket(app, path, token)
            sockets.append(second)
            rejected = await second.receive()
            assert rejected["type"] == "websocket.close"
            assert rejected["code"] == 1008
        finally:
            gate.set()
            for socket in reversed(sockets):
                await socket.close()
