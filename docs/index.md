---
title: Rokid Physical AI — voice and gesture interface for robot arms
description: An open architecture connecting Rokid smart glasses to robot arms through voice, gestures, and calibrated tabletop perception.
---
# Rokid Physical AI

**Voice and gesture interface for robot arms, using Rokid smart glasses.**

Point at an object. Say what you want done. Let your robot handle the movement.

Rokid Physical AI connects a wearable voice-and-camera interface to a physical AI agent. The agent interprets the request and maintains task context. A separate robot controller validates and executes the movement.

The first application is tabletop pick and place with a parallel gripper. You indicate an object and a destination, hear a concrete description, and confirm by voice. The robot returns an execution result to the glasses.

## Start here

- [Run the application](quickstart.md): Python 3.14+, Android build, pairing, and diagnostic sessions.
- [Understand the architecture](architecture.md): authority boundaries, APIs, and persistence.
- [Connect a robot](robots.md): Franka Research 3 and UFACTORY xArm6 profiles.
- [Calibrate the workspace](calibration.md): cameras, markers, and metric coordinates.
- [Check verification status](verification.md): software, device, simulation, and hardware evidence.
- [Инструкция на русском](ru.md).

## Intended hardware

Rokid glasses running Android 12, a computer running the agent, a fixed RGB-D camera, and a robot arm with a two-finger parallel gripper. A Linux controller runs ROS 2 and the robot driver. Eye tracking is not required.

The project is in active development. Supported interfaces and physical qualification are tracked separately in the [verification matrix](verification.md).

## Common questions

### Does the application need custom firmware?

The Android client runs on stock firmware. Camera, microphone, short speaker playback, HUD placement and local voice shutdown were checked on one Rokid RG-glasses device. See the dated [device evidence](verification.md) for firmware and remaining tests.

### Can the language model move the robot directly?

The model proposes a typed task. A separate gateway validates geometry, motion permission and constraints. Execution requires the exact spoken preview and a separate local voice confirmation. The model has no joint-control or arming tool.

### Which robots have been physically tested?

Neither FR3 nor xArm6 is physically qualified yet. Their gateway code has software checks; physical manipulation, full cloud conversation and model gesture accuracy remain acceptance gates.

## Author and related work

Created and maintained by [Igor Yakushev](https://igor-ya.ru/). Related writing: [Physical AI and robot learning](https://igor-ya.ru/posts/physical-ai-robot-learning/) (Russian).

[Rula](https://ykshv.github.io/rula/) is another project by the same author: a local-first Russian voice avatar with a browser VRM interface.

Source code: [github.com/ykshv/rokid-physical-ai](https://github.com/ykshv/rokid-physical-ai). Apache-2.0.
