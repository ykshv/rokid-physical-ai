---
description: Operate and recover the Rokid agent without replaying physical actions, exposing captured content or mistaking build checks for hardware readiness.
---
# Operations and recovery

Run one agent process for one operator. The in-process session registry does not coordinate multiple Uvicorn workers or replicas; do not scale this deployment by increasing worker count. Keep the state directory and robot journal persistent and outside the checkout. Agent/perception credentials and controller network access have separate scopes.

`rokid-agent doctor` reports configuration presence, not dependency readiness. `/healthz` confirms that the HTTP application is alive; it does not certify provider connectivity, calibration, robot readiness or audio routing. Use the scenario outcomes in [verification](verification.md) for acceptance.

## Stop or uncertain execution

1. Stop the session and gateway. Use the independent physical emergency stop when required by the actual robot procedure. Voice stop is not a certified safety function.
2. Inspect the arm, gripper, held object and destination. Preserve the operation ID, agent database and gateway journal. Do not send a replacement pick/place while the result is uncertain.
3. On the controller, with motion stopped, reconcile through `/robot_gateway/reconcile` only after inspection, as described in [robot integration](robots.md). It keeps the gateway disarmed.
4. Run `uv run rokid-agent reconcile <TASK_ID>` on the agent. It accepts only a matching terminal gateway result. Missing, executing or uncertain results do not clear uncertainty.
5. Re-establish current calibration/perception and perform explicit local arming only when the equipment procedure permits it. A restart or reconnect never supplies this permission.

If the gateway has no record for an operation that the agent marked uncertain, keep the system stopped and investigate the submission/journal boundary. There is no automatic database edit or force-success command. Do not infer no movement from a 404 after a journal loss.

## Failure triage

| Symptom | Inspect | Expected containment |
| --- | --- | --- |
| Provider unavailable, rejected request or exhausted budget | Key presence, deployment model/prompt revision and sanitized error category | Session ends; no automatic provider fallback or motion retry |
| Stale/changed scene or missing registration marker | Camera producer, clock synchronization, calibration identity and observed scene | Clarify or cancel; do not bypass freshness checks |
| Confirmation never executes | Actual preview completion, local recognizer, current geometry and confirmation window | Pending/expired proposal does not grant motion |
| Silence while iPhone is connected | App focus acquisition, actual playback progress and device routing | Focus loss stops the session; no global volume/pairing changes |
| Missing heartbeat or media | Connection lifecycle and bounded queue pressure | Session/lease terminates; new connection does not resume movement |
| Journal/storage error | Persistent disk availability, permissions and retained operation history | Stop and inspect; do not replace state with an empty journal |

Normal logs contain categories, identifiers and counters; they must not contain media, transcripts, provider error bodies or tokens. Share only sanitized excerpts. Recording new evaluation material is a separate explicit workflow with consent and retention rules.

## Deployment evidence

Keep the Git revision, Python/Gradle/ROS versions, dependency lock, profile/calibration identity and firmware associated with an acceptance run. API availability and a passing container build are not physical evidence. The current known gaps and dated device observations belong to [verification](verification.md); avoid copying them into run logs or agent instruction files.
