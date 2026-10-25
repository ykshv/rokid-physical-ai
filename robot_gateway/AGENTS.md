# Robot gateway

Inherits the repository [AGENTS.md](../AGENTS.md). This C++20 / ROS 2 Jazzy component is the sole physical-motion authority. Read [robot integration](../docs/robots.md) before changing a driver, profile, frame or gripper mapping.

## Ownership and invariants

- [policy.hpp](include/policy.hpp) validates geometry, freshness and supported tasks independently of the agent. [journal.hpp](include/journal.hpp) prevents persistence failures from appearing successful. [main.cpp](src/main.cpp) owns HTTPS, journal storage, local arm/reconcile services, watchdog, MoveIt and gripper adapters.
- [drivers.repos](drivers.repos) pins driver revisions. Keep Docker build pins consistent when changing them. Compilation of vendor message packages does not qualify the full driver or hardware.
- FR3 and xArm6 profiles remain `hardware_qualified: false` until dated physical evidence exists. FR3 and Panda are different compatibility profiles.
- Agent and scene-producer credentials are separate. Only observed, authenticated geometry can reach planning. A model/HTTP request cannot arm or bypass workspace, grasp, collision or freshness checks.
- Persist operation identity before movement; repeated identical requests return the same operation, changed content under the same ID is rejected. A journal failure must not be converted into success or permission to start another operation.
- Keep watchdog/stop independent of provider availability. Stop the sequence between stages; never continue after an uncertain grasp, partial Cartesian path or loss of perception. Controller and physical-stop behavior still require hardware qualification.
- The MoveIt world needs a calibrated `work_table`, the correct TCP and finger links. Endpoint success does not establish collision safety or observed placement.
- Reconciliation is a local operator attestation after inspection. It never re-arms; startup and reconnect remain disarmed.

Run `uv run python tools/check.py robot` from the repository root. This builds the container and runs policy tests; it does not connect to a robot. Scene validation changes must also pass `uv run python tools/check.py python`: [shared fixture cases](test/fixtures/scene_validation.json) run in both languages. Never label this build as a simulator or physical trial.
