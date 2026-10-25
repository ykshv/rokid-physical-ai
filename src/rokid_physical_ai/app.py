"""TLS-facing application with separate control/media connections and bounded sessions."""

import asyncio
import base64
import contextlib
import logging
import math
import os
import struct
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import Field

from .contracts import Contract, Identifier, Proposal
from .engine import TaskEngine
from .frames import FrameBuffer
from .gateway import Gateway
from .narration import synthesize
from .perception import Calibration, GlassesCalibration, annotate_glasses
from .protocol import CONTROL_EVENT, AudioPlayed, Diagnostics, PreviewPlayed
from .realtime import Realtime
from .speech import LocalCommands
from .store import Store

logger = logging.getLogger("rokid")


class PairRequest(Contract):
    code: str = Field(min_length=20, max_length=100)


class FrameMessage(Contract):
    type: str = Field(pattern="^frame$")
    id: Identifier
    jpeg: str = Field(max_length=400_000)


@dataclass
class Settings:
    state_dir: Path
    diagnostic: bool = False
    vosk_model: Path | None = None
    workspace_calibration: Path | None = None
    glasses_calibration: Path | None = None


class Session:
    def __init__(
        self,
        device: str,
        control: WebSocket,
        store: Store,
        gateway: Gateway | None,
        settings: Settings,
    ):
        self.id, self.device = uuid.uuid4().hex, device
        self.control = control
        self.media: WebSocket | None = None
        self.settings, self.gateway, self.store = settings, gateway, store
        self.frames = FrameBuffer()
        self.engine = (
            TaskEngine(store, gateway, self.id, self.frames, self.emit) if gateway else None
        )
        self.realtime: Realtime | None = None
        self.local: LocalCommands | None = None
        self.calibration: Calibration | None = None
        self.intrinsics: GlassesCalibration | None = None
        self.grounded: dict[str, tuple[str, float]] = {}
        self.last_heartbeat = time.monotonic()
        self.started = False
        self.started_at = time.monotonic()
        self.frames_received = self.audio_bytes = 0
        self.audio_peak = 0
        self.provider_task: asyncio.Task | None = None
        self.speech_task: asyncio.Task | None = None
        self.preview_id: str | None = None
        self.confirm_after = float("inf")
        self.control_lock, self.media_lock = asyncio.Lock(), asyncio.Lock()

    async def emit(self, event: dict) -> None:
        if event.get("type") == "user.speech_started":
            if self.preview_id and self.engine:
                await self.cancel_narration()
                await self.engine.stop("preview_interrupted")
            await self.emit({"type": "audio.clear"})
            return
        if event.get("type") == "confirmation":
            self.preview_id = event["task_id"]
            self.confirm_after = float("inf")
            self.speech_task = asyncio.create_task(self.narrate(event["text"], self.preview_id))
            return
        if event.get("type") == "task.result":
            await self.cancel_narration()
            text = {
                "succeeded": "Задача выполнена.",
                "cancelled": "Задача отменена.",
            }.get(event["state"], "Выполнение не подтверждено. Проверьте робота.")
            if not self.settings.diagnostic and self.started:
                self.speech_task = asyncio.create_task(self.narrate(text))
        if event.get("type") == "audio" and self.speech_task and not self.speech_task.done():
            if not event.get("narration"):
                return
        if event.get("type") in ("audio", "audio.clear"):
            if self.media:
                async with self.media_lock:
                    await asyncio.wait_for(self.media.send_json(event), 2)
        else:
            async with self.control_lock:
                await asyncio.wait_for(self.control.send_json(event), 2)

    async def cancel_narration(self) -> None:
        self.preview_id = None
        self.confirm_after = float("inf")
        if self.speech_task and self.speech_task is not asyncio.current_task():
            self.speech_task.cancel()
            await asyncio.gather(self.speech_task, return_exceptions=True)
        self.speech_task = None

    async def narrate(self, text: str, task_id: str | None = None) -> None:
        await self.emit({"type": "audio.clear"})
        pcm = await synthesize(os.environ["OPENAI_API_KEY"], text)
        item = "preview_" + task_id if task_id else "notice_" + uuid.uuid4().hex
        for start in range(0, len(pcm), 4800):
            last = start + 4800 >= len(pcm)
            await self.emit(
                {
                    "type": "audio",
                    "item_id": item,
                    "narration": True,
                    "audio": base64.b64encode(pcm[start : start + 4800]).decode(),
                    "preview_task_id": task_id if last else None,
                    "last": last,
                }
            )
            await asyncio.sleep(0.1)

    def preview_played(self, task_id: str) -> None:
        if self.engine and task_id == self.preview_id:
            self.preview_id = None
            if self.local:
                self.local.reset()
            self.confirm_after = time.monotonic() + 0.5
            self.engine.preview_played(task_id)

    async def start(self) -> None:
        if self.started or self.media is None:
            raise ValueError("session_already_started_or_media_missing")
        if self.settings.vosk_model:
            self.local = await asyncio.to_thread(LocalCommands, self.settings.vosk_model)
        if not self.settings.diagnostic:
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise ValueError("OPENAI_API_KEY_missing_on_server")
            if not self.settings.vosk_model:
                raise ValueError("local_speech_model_required")
            if self.settings.workspace_calibration and self.settings.glasses_calibration:
                self.calibration = Calibration.load(self.settings.workspace_calibration)
                self.intrinsics = GlassesCalibration.model_validate_json(
                    self.settings.glasses_calibration.read_text(encoding="utf-8")
                )
            self.realtime = Realtime(key, self.emit, self.tool)
            await self.realtime.open()
            self.provider_task = asyncio.create_task(self.realtime.receive())
        self.started = True
        await self.emit({"type": "session.started", "diagnostic": self.settings.diagnostic})
        if not self.settings.diagnostic:
            self.speech_task = asyncio.create_task(self.narrate("Рабочая сессия начата. Я слушаю."))
        if self.settings.diagnostic:
            tone = b"".join(
                struct.pack("<h", int(1800 * math.sin(2 * math.pi * 440 * n / 24000)))
                for n in range(4800)
            )
            await self.emit(
                {
                    "type": "audio",
                    "item_id": "diagnostic-tone",
                    "last": True,
                    "audio": base64.b64encode(tone).decode(),
                }
            )

    async def tool(self, name: str, args: dict) -> dict:
        if self.engine is None or self.gateway is None:
            return {"error": "robot_gateway_not_configured"}
        if name == "get_scene" and not args:
            if self.calibration is None or self.intrinsics is None or self.realtime is None:
                return {"error": "camera_calibration_required"}
            scene = await self.gateway.scene()
            frames = []
            self.grounded.clear()
            for frame in self.frames.samples():
                try:
                    annotated = await asyncio.to_thread(
                        annotate_glasses, frame.jpeg, scene, self.intrinsics, self.calibration
                    )
                except ValueError:
                    continue
                await self.realtime.image(frame.id, annotated)
                self.grounded[frame.id] = (scene.revision, time.monotonic())
                frames.append(frame.id)
            if not frames:
                return {"error": "workspace_markers_not_visible", "action": "ask_user"}
            return {"scene": scene.model_dump(), "keyframe_ids": frames}
        if name == "propose_task":
            proposal = Proposal.model_validate(args)
            evidence = self.grounded.get(proposal.keyframe_id)
            if (
                evidence is None
                or evidence[0] != proposal.scene_revision
                or time.monotonic() - evidence[1] > 10
            ):
                raise ValueError("ungrounded_keyframe")
            return await self.engine.propose(proposal)
        if name == "task_status" and not args:
            return {
                "tasks": [t.model_dump() for t in self.store.tasks() if t.session_id == self.id][
                    -10:
                ]
            }
        if name == "cancel_task" and not args:
            await self.engine.stop()
            return {"stop_requested": True}
        raise ValueError("unknown_tool_or_arguments")

    async def audio(self, pcm: bytes) -> None:
        if not self.started or len(pcm) % 2 or not 0 < len(pcm) <= 9600:
            raise ValueError("invalid_audio_chunk_or_inactive_session")
        self.audio_bytes += len(pcm)
        if self.settings.diagnostic:
            self.audio_peak = max(
                self.audio_peak, *(abs(v[0]) for v in struct.iter_unpack("<h", pcm))
            )
        command = await asyncio.to_thread(self.local.accept, pcm) if self.local else None
        if command in ("стоп", "отмена", "выключись"):
            logger.info("local_command=%s", command)
            await self.cancel_narration()
            if self.engine:
                await self.engine.stop()
            await self.emit({"type": "audio.clear"})
            if command == "выключись":
                await self.emit({"type": "session.ended"})
                await self.control.close(code=1000)
            return
        if command == "подтверждаю" and self.engine and time.monotonic() >= self.confirm_after:
            accepted = await self.engine.confirm()
            await self.emit({"type": "confirmation.result", "accepted": accepted})
        if self.realtime and not (self.speech_task and not self.speech_task.done()):
            await self.realtime.audio(pcm)

    async def watchdog(self) -> None:
        next_report = time.monotonic() + 10
        while True:
            await asyncio.sleep(0.5)
            if time.monotonic() - self.last_heartbeat > 3:
                raise TimeoutError("device_heartbeat_lost")
            if time.monotonic() - self.started_at > 3300:
                raise TimeoutError("session_duration_limit")
            if self.provider_task and self.provider_task.done():
                self.provider_task.result()
                raise RuntimeError("provider_disconnected")
            if self.speech_task and self.speech_task.done():
                self.speech_task.result()
            if self.gateway and self.started:
                await self.gateway.heartbeat()
            if self.started and time.monotonic() >= next_report:
                logger.info(
                    "session_metrics seconds=%d frames=%d audio_bytes=%d "
                    "buffered_frames=%d peak=%d",
                    time.monotonic() - self.started_at,
                    self.frames_received,
                    self.audio_bytes,
                    len(self.frames.frames),
                    self.audio_peak,
                )
                next_report = time.monotonic() + 60
                self.audio_peak = 0

    async def close(self) -> None:
        self.started = False
        await self.cancel_narration()
        if self.engine:
            with contextlib.suppress(Exception):
                await self.engine.close()
        if self.provider_task:
            self.provider_task.cancel()
            await asyncio.gather(self.provider_task, return_exceptions=True)
        if self.realtime:
            await self.realtime.close()
        if self.media:
            with contextlib.suppress(Exception):
                await self.media.close()
        self.frames.frames.clear()
        logger.info(
            "session_closed frames=%d audio_bytes=%d", self.frames_received, self.audio_bytes
        )


def create_app(settings: Settings, gateway: Gateway | None = None) -> FastAPI:
    if settings.diagnostic and gateway is not None:
        raise ValueError("diagnostic_mode_must_not_connect_to_robot")
    store = Store(settings.state_dir / "agent.sqlite3")
    store.recover()
    sessions: dict[str, Session] = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        for session in list(sessions.values()):
            await session.close()
        store.close()

    app = FastAPI(title="Rokid Physical AI", version="0.1.0.dev1", lifespan=lifespan)
    app.state.store = store

    @app.get("/healthz")
    def health():
        return {
            "status": "ok",
            "diagnostic": settings.diagnostic,
            "robot_configured": gateway is not None,
        }

    @app.post("/v1/pair")
    def pair(body: PairRequest):
        try:
            device, token = store.pair(body.code)
            return {"device_id": device, "token": token}
        except ValueError as exc:
            raise HTTPException(401, "invalid_pairing_code") from exc

    async def identity(ws: WebSocket) -> str | None:
        header = ws.headers.get("authorization", "")
        device = store.authenticate(header[7:]) if header.startswith("Bearer ") else None
        if not device:
            await ws.close(code=1008)
        return device

    @app.websocket("/v1/control")
    async def control(ws: WebSocket):
        device = await identity(ws)
        if not device:
            return
        if sessions:
            await ws.close(code=1008, reason="one_operator_session_allowed")
            return
        # Reserve before the first transport await: two simultaneous handshakes
        # must not both observe an empty registry and become motion operators.
        session = Session(device, ws, store, gateway, settings)
        sessions[session.id] = session
        workers: list[asyncio.Task] = []

        async def read_control():
            while True:
                event = CONTROL_EVENT.validate_python(await ws.receive_json())
                kind = event.type
                if kind == "heartbeat":
                    session.last_heartbeat = time.monotonic()
                elif kind == "session.start":
                    await session.start()
                elif isinstance(event, PreviewPlayed):
                    session.preview_played(event.task_id)
                elif isinstance(event, AudioPlayed):
                    if session.realtime and event.item_id == session.realtime.output_item:
                        session.realtime.played_ms = min(event.milliseconds, 60000)
                elif kind == "session.stop":
                    break
                elif isinstance(event, Diagnostics):
                    # An allowlist prevents arbitrary client dumps entering logs.
                    logger.info(
                        "device_capabilities camera=%s aec=%s tts_ru=%s",
                        event.camera,
                        event.aec,
                        event.tts_ru,
                    )
                else:
                    raise ValueError("unknown_control_event")

        try:
            await asyncio.wait_for(ws.accept(), 2)
            workers = [asyncio.create_task(read_control()), asyncio.create_task(session.watchdog())]
            await session.emit({"type": "session.ready", "session_id": session.id})
            done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("session_failed category=%s", type(exc).__name__)
            with contextlib.suppress(Exception):
                await session.emit(
                    {"type": "error", "code": "session_dependency_or_protocol_error"}
                )
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            try:
                await session.close()
            finally:
                sessions.pop(session.id, None)
                with contextlib.suppress(Exception):
                    await ws.close()

    @app.websocket("/v1/media/{session_id}")
    async def media(ws: WebSocket, session_id: str):
        device = await identity(ws)
        if not device:
            return
        session = sessions.get(session_id)
        if session is None or session.device != device or session.media:
            await ws.close(code=1008)
            return
        session.media = ws
        try:
            await asyncio.wait_for(ws.accept(), 2)
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await session.audio(message["bytes"])
                elif message.get("text") is not None:
                    if not session.started:
                        raise ValueError("session_not_started")
                    frame = FrameMessage.model_validate_json(message["text"])
                    await asyncio.to_thread(session.frames.add, frame.id, frame.jpeg)
                    session.frames_received += 1
        except WebSocketDisconnect, ValueError:
            pass
        finally:
            # Media loss also invalidates the control session and movement lease.
            with contextlib.suppress(Exception):
                await session.control.close(code=1011, reason="media_disconnected")
            session.media = None

    return app
