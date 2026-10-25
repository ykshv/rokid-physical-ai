# Architecture

## Three authorities

The **Android application** captures an explicitly started session and renders audio. The **Python agent** understands requests and proposes typed tasks. The **C++ robot gateway** is the only physical-motion authority. The language model receives no joint, shell, or arbitrary-code tool.

The agent uses Python 3.14+, FastAPI, Pydantic, SQLite, OpenCV, and the OpenAI Realtime WebSocket API. The selected model is `gpt-realtime-2.1`; prompt and tool definitions are versioned in source. Official protocol: [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations).

## Interaction

1. The device authenticates its control and media sockets. One operator session is accepted.
2. Audio is PCM16 mono at 24 kHz. Images use the qualified 640×480 sensor stream, sampled at up to 5 Hz.
3. A bounded ten-second memory buffer preserves brief gestures. Registered frames receive object/zone IDs projected from the calibrated scene.
4. `get_scene` returns candidate IDs; `propose_task` requests a specific object and destination. Missing markers or expired evidence cause clarification.
5. The server renders a deterministic description using `gpt-realtime-2.1-mini` with no tools. Audio is held until the returned transcript matches the description. The device acknowledges actual playback completion. Only then, after a short echo guard and a separately recognized “подтверждаю”, can the engine submit the operation. Interruption invalidates the preview.
6. The gateway checks its own scene, local motion latch, workspace and gripper limits. Completion requires an observed placement, not just a motor acknowledgement.

The keyframe and scene are timestamped independently. Device-provided timestamps do not grant freshness. `robot_base` is the protocol coordinate frame; each gateway profile maps it to the configured URDF base frame.

## Public contracts

Canonical definitions are in `src/rokid_physical_ai/contracts.py`. Generate JSON Schema from those definitions:

```sh
uv run rokid-agent schemas --output dist/schemas
```

| Contract | Meaning |
| --- | --- |
| `SceneObservation` | Objects, destinations, calibration identity and observation time |
| `TaskIntent` | Pick/place request referring to existing scene IDs and a keyframe |
| `RobotCapabilities` | Adapter identity, supported operations, grasp and workspace limits |
| `TaskExecution` | Durable task state and reason for an unsuccessful or uncertain outcome |
| `MotionRequest` | Idempotent, time-limited execution request |

HTTP `/v1/pair` accepts a single-use pairing code. Authenticated `/v1/control` and `/v1/media/{session_id}` WebSockets carry application events and media. Provider errors are reduced to categories before reaching logs or the glasses.

## Failure and recovery

The agent persists operations before submitting them. A lost acknowledgement produces `uncertain`, not success or an automatic retry. A restart cancels unconfirmed proposals and marks interrupted execution uncertain. Reconnection does not re-arm the robot.

Task state transitions are retained in SQLite. After physically inspecting an interrupted operation, the operator reconciles the stopped local gateway and runs `rokid-agent reconcile <TASK_ID>`; an unresolved or executing gateway result cannot clear the agent's uncertainty.

Control heartbeat and media loss terminate the session. The gateway has an independent heartbeat watchdog. A local stop recognizer supplements the robot's physical emergency-stop system; it is not a certified safety function.

Sessions are bounded to 55 minutes and 30 tool calls. Audio queues, frame buffers, messages, and provider output are bounded. Raw media and transcripts are not stored by default. Test recordings and evaluation datasets require a deliberate recording workflow outside the normal runtime.
