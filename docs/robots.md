---
description: Configure Franka FR3 or UFACTORY xArm6 with ROS 2 Jazzy, MoveIt, authenticated scene input, an independent motion latch, and hardware qualification.
---
# Robot integration

## Reference profiles

| Profile | Driver | Gripper | Physical status |
| --- | --- | --- | --- |
| Franka Research 3 | `franka_ros2`, ROS 2 Jazzy | Franka Hand | Hardware not available for qualification |
| UFACTORY xArm6 | `xarm_ros2`, ROS 2 Jazzy | Standard parallel gripper | Hardware not available for qualification |

Panda uses a different driver/system compatibility generation. Check the [Franka compatibility matrix](https://franka.de/fr3-compatibility-matrix); do not substitute Panda for FR3. Other robots need an adapter/profile and their own qualification.

## Controller host

Use Ubuntu 24.04 with ROS 2 Jazzy, MoveIt 2 and the matching vendor driver. The application gateway is C++; it does not depend on the ROS distribution's Python interpreter. The separately installed perception worker and agent require Python 3.14+.

For Franka, use the manufacturer's FCI requirements, a suitable realtime kernel and wired robot connection. The Windows computer can run the agent and Android build. Docker Desktop is a build/test environment, not a qualified realtime robot controller.

Pinned vendor source revisions are in `robot_gateway/drivers.repos`. Install vendor runtime dependencies according to their official instructions. The gateway additionally requires `libcpp-httplib-dev`, `libssl-dev`, and `nlohmann-json3-dev`.

```sh
colcon build --packages-select rokid_robot_gateway
colcon test --packages-select rokid_robot_gateway
colcon test-result --verbose
```

Bring up the vendor MoveIt configuration and calibrated collision scene first. Load the matching gateway YAML profile together with the same `robot_description`, `robot_description_semantic`, and planning parameters. A calibrated collision object named `work_table` is required. Validate the actual TCP at the grasp center, downward tool orientation, base frame, table geometry, limits and parallel-gripper mapping before qualification. Set `touch_links` to the exact finger links from that hardware's URDF; do not assume names are interchangeable across driver versions.

Observed object boxes enter the collision world. The target is allowed contact only during its vertical grasp approach, then attached to the planning scene for transport and detached after release. Partial Cartesian approach/retreat paths are rejected. Source and destination must be isolated. The initial geometry uses axis-aligned object envelopes and a Y-axis gripper width; qualify simple rigid cuboids before broadening object shapes or orientations.

## Credentials and startup

Provide these variables outside the checkout:

| Variable | Purpose |
| --- | --- |
| `ROBOT_GATEWAY_TOKEN` | Agent credential, at least 32 characters |
| `ROBOT_PERCEPTION_TOKEN` | Distinct camera-producer credential |
| `ROBOT_TLS_CERT`, `ROBOT_TLS_KEY` | HTTPS server identity |
| `ROBOT_JOURNAL` | Persistent operation journal path |
| `ROBOT_BIND` | Controller bind address; defaults to loopback |

The camera producer alone can publish `/v1/scene`. The agent can inspect scenes, submit `/v1/operations`, query an operation, send heartbeat and stop. The server executes its own observed geometry, not coordinates supplied by the language model.

Profiles default to `hardware_qualified: false`. Physical movement remains latched until a qualified local configuration is loaded and the operator calls the local ROS service `/robot_gateway/arm`. The service requires current perception and an active heartbeat. It is intentionally absent from the model's tools and HTTP API.

Any interrupted execution is uncertain and remains disarmed. After checking the real arm, gripper and object, an operator may call `/robot_gateway/reconcile` (`std_srvs/srv/Trigger`). This records failed, inspected operations; it does not re-arm. Then reconcile the corresponding agent task with `rokid-agent reconcile <TASK_ID>`. Never use reconciliation as a substitute for inspection. Journal writes are synchronized to storage before movement starts.

## Adding an arm

Implement the same bounded pick/place and stop behavior with the vendor's supported controller. Define frames, TCP, workspace, grasp limits, motion limits and result verification. Pass schema, idempotency, disconnect, stop and placement tests, then qualify on that exact hardware and firmware. The common API does not imply universal physical compatibility.
