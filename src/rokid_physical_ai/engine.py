"""Single-session task authority with durable idempotency and explicit confirmation."""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable

from .contracts import (
    MotionRequest,
    Proposal,
    SceneObservation,
    TaskExecution,
    TaskIntent,
    TaskState,
)
from .frames import FrameBuffer
from .gateway import Gateway
from .store import Store

Emit = Callable[[dict], Awaitable[None]]


class TaskEngine:
    def __init__(
        self, store: Store, gateway: Gateway, session_id: str, frames: FrameBuffer, emit: Emit
    ):
        self.store, self.gateway, self.session_id = store, gateway, session_id
        self.frames, self.emit = frames, emit
        self.lock = asyncio.Lock()
        self.pending: str | None = None
        self.active: str | None = None
        self.preview_played_at: float | None = None
        self.preview_scene: SceneObservation | None = None
        self.runner: asyncio.Task | None = None
        self.closed = False

    async def propose(self, proposal: Proposal) -> dict:
        async with self.lock:
            if self.closed or self.pending or self.active:
                raise ValueError("session_busy_or_closed")
            if any(t.state == TaskState.UNCERTAIN for t in self.store.tasks()):
                raise ValueError("operator_reconciliation_required")
            self.frames.get(proposal.keyframe_id)
            scene = await self.gateway.scene()
            if (
                not scene.calibrated
                or scene.revision != proposal.scene_revision
                or not 0 <= time.time() - scene.observed_at <= 2
            ):
                raise ValueError("scene_changed_or_uncalibrated")
            obj = next((o for o in scene.objects if o.id == proposal.object_id), None)
            zone = next((z for z in scene.zones if z.id == proposal.destination_id), None)
            if obj is None or zone is None:
                raise ValueError("unknown_object_or_destination")
            preview = (
                f"Перенести предмет {obj.label} в зону {zone.label}. "
                "Для выполнения скажите: подтверждаю."
            )
            now = time.time()
            task = TaskExecution(
                id=uuid.uuid4().hex,
                session_id=self.session_id,
                intent=TaskIntent(**proposal.model_dump()),
                state=TaskState.PROPOSED,
                preview=preview,
                created_at=now,
                updated_at=now,
            )
            self.store.put(task)
            self.pending, self.preview_scene = task.id, scene
            self.preview_played_at = None
            await self.emit({"type": "confirmation", "task_id": task.id, "text": preview})
            return {
                "task_id": task.id,
                "state": task.state,
                "instruction": "The device reads the preview. Wait for local voice confirmation.",
            }

    def preview_played(self, task_id: str) -> None:
        if task_id == self.pending:
            self.preview_played_at = time.monotonic()

    async def confirm(self) -> bool:
        async with self.lock:
            if (
                self.closed
                or not self.pending
                or self.preview_played_at is None
                or time.monotonic() - self.preview_played_at > 15
            ):
                return False
            task = self.store.get(self.pending)
            current = await self.gateway.scene()
            previous = self.preview_scene
            if previous is None or not current.calibrated:
                raise ValueError("calibration_lost")
            old = next(o for o in previous.objects if o.id == task.intent.object_id)
            new = next((o for o in current.objects if o.id == old.id), None)
            if (
                new is None
                or old.center.distance(new.center) > 0.005
                or current.calibration_id != previous.calibration_id
                or current.zones != previous.zones
                or not 0 <= time.time() - current.observed_at <= 2
            ):
                await self._cancel_pending("scene_changed_confirm_again")
                return False
            self.active, self.pending = task.id, None
            task = task.model_copy(update={"state": TaskState.EXECUTING, "updated_at": time.time()})
            self.store.put(task)
            request = MotionRequest(
                operation_id=task.id,
                scene=current,
                intent=task.intent.model_copy(update={"scene_revision": current.revision}),
                expires_at=time.time() + 2,
            )
            self.runner = asyncio.create_task(self._execute(request))
            return True

    async def _execute(self, request: MotionRequest) -> None:
        try:
            result = await self.gateway.execute(request)
            deadline = time.monotonic() + 90
            while result.state == "executing":
                if time.monotonic() > deadline:
                    await self.gateway.stop()
                    raise TimeoutError("execution_deadline")
                await asyncio.sleep(0.25)
                result = await self.gateway.status(request.operation_id)
            state, reason = TaskState(result.state), result.reason
        except asyncio.CancelledError:
            state, reason = TaskState.UNCERTAIN, "cancelled_reconcile_gateway"
        except Exception:
            # A transport timeout cannot establish whether the robot moved.
            state, reason = TaskState.UNCERTAIN, "gateway_result_unconfirmed"
            try:
                await self.gateway.stop()
            except Exception:
                reason = "gateway_result_and_stop_unconfirmed"
        task = self.store.get(request.operation_id)
        self.store.put(
            task.model_copy(update={"state": state, "reason": reason, "updated_at": time.time()})
        )
        self.active = None
        await self.emit(
            {"type": "task.result", "task_id": task.id, "state": state, "reason": reason}
        )

    async def _cancel_pending(self, reason: str) -> None:
        if self.pending:
            task = self.store.get(self.pending)
            self.store.put(
                task.model_copy(
                    update={
                        "state": TaskState.CANCELLED,
                        "reason": reason,
                        "updated_at": time.time(),
                    }
                )
            )
            self.pending = None
            await self.emit(
                {"type": "task.result", "task_id": task.id, "state": "cancelled", "reason": reason}
            )

    async def stop(self, reason: str = "user_stop") -> None:
        async with self.lock:
            await self._cancel_pending(reason)
            await self.gateway.stop()

    async def close(self) -> None:
        self.closed = True
        try:
            await self.stop("session_disconnected")
        finally:
            if self.runner:
                if not self.runner.done():
                    self.runner.cancel()
                await asyncio.gather(self.runner, return_exceptions=True)
