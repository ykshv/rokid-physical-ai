import asyncio
import time

import pytest

from rokid_physical_ai.contracts import Proposal, TaskState, Vector3
from rokid_physical_ai.engine import TaskEngine


@pytest.fixture
def engine(store, gateway, frames):
    async def emit(event):
        events.append(event)

    events = []
    value = TaskEngine(store, gateway, "session_1", frames, emit)
    value.events = events
    return value


def proposal(**changes):
    return Proposal(
        object_id="cube", destination_id="tray", scene_revision="scene_1", keyframe_id="frame_1"
    ).model_copy(update=changes)


async def test_only_local_confirmation_after_playback_starts_motion(engine, gateway):
    task = await engine.propose(proposal())
    assert not gateway.operations
    assert not await engine.confirm()
    engine.preview_played(task["task_id"])
    assert await engine.confirm()
    await engine.runner
    assert len(gateway.operations) == 1
    assert not await engine.confirm()
    assert engine.store.get(task["task_id"]).state == TaskState.SUCCEEDED


async def test_parallel_confirmations_execute_at_most_once(engine, gateway):
    task = await engine.propose(proposal())
    engine.preview_played(task["task_id"])
    assert sum(await asyncio.gather(engine.confirm(), engine.confirm())) == 1
    await engine.runner
    assert len(gateway.operations) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"object_id": "missing"},
        {"destination_id": "missing"},
        {"scene_revision": "old"},
        {"keyframe_id": "missing"},
    ],
)
async def test_invalid_grounding_never_moves(engine, gateway, changes):
    with pytest.raises(ValueError):
        await engine.propose(proposal(**changes))
    assert not gateway.operations


async def test_moved_object_invalidates_confirmation(engine, gateway):
    task = await engine.propose(proposal())
    engine.preview_played(task["task_id"])
    moved = gateway.observation.objects[0].model_copy(
        update={"center": Vector3(x=0.5, y=0, z=0.025)}
    )
    gateway.observation = gateway.observation.model_copy(update={"objects": [moved]})
    assert not await engine.confirm()
    assert not gateway.operations
    assert engine.store.get(task["task_id"]).state == TaskState.CANCELLED


async def test_expired_confirmation_does_not_move(engine, gateway):
    task = await engine.propose(proposal())
    engine.preview_played(task["task_id"])
    engine.preview_played_at = time.monotonic() - 16
    assert not await engine.confirm()
    assert not gateway.operations


async def test_timeout_after_submission_is_uncertain_not_retried(engine, gateway):
    gateway.fail_execute = True
    task = await engine.propose(proposal())
    engine.preview_played(task["task_id"])
    await engine.confirm()
    await engine.runner
    assert len(gateway.operations) == 1
    assert gateway.stopped == 1
    assert engine.store.get(task["task_id"]).state == TaskState.UNCERTAIN


async def test_disconnect_cancels_pending_and_stops_gateway(engine, gateway):
    task = await engine.propose(proposal())
    await engine.close()
    assert gateway.stopped == 1
    assert not await engine.confirm()
    assert engine.store.get(task["task_id"]).state == TaskState.CANCELLED


async def test_restart_marks_submitted_task_uncertain(engine):
    task = await engine.propose(proposal())
    stored = engine.store.get(task["task_id"])
    engine.store.put(stored.model_copy(update={"state": TaskState.EXECUTING}))
    engine.store.recover()
    assert engine.store.get(task["task_id"]).state == TaskState.UNCERTAIN


async def test_busy_proposal_cannot_replace_confirmed_description(engine):
    first = await engine.propose(proposal())
    with pytest.raises(ValueError):
        await engine.propose(proposal())
    assert engine.pending == first["task_id"]
