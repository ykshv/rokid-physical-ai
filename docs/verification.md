---
description: Dated Rokid device results, automated checks, and open acceptance gates for voice, gestures, network recovery, and physical robot manipulation.
---
# Verification

This page separates implementation, software checks, simulation, and physical evidence. Updated 2026-10-25.

| Area | Evidence |
| --- | --- |
| Python runtime | Python 3.14.7; NumPy and OpenCV import verified |
| Server contracts and failure handling | Automated Python tests cover boundaries, stop/confirmation races, session ownership, recovery and response identity; current CI is authoritative for each revision |
| Android | APK compiled and lint passed; installed on stock firmware; operator confirmed HUD placement, audible playback and local voice shutdown |
| OpenAI session | API key not configured in the development environment; live provider test pending |
| ROS gateway | C++ / ROS 2 Jazzy build, policy and persistence-failure tests; shared scene-validation cases run in Python and C++; see CI for each revision |
| RealSense Python binding | `pyrealsense2` 2.59.1.11053 imports on Python 3.14.7; no camera attached |
| Robot simulation | Not yet claimed as verified |
| Physical FR3 / xArm6 | No arm available; no physical manipulation tests performed |
| Model gesture accuracy | No consented, labelled 100-episode dataset available yet |

## Device target

The inspected target is Rokid `RG-glasses`, Android 12/API 32, firmware `1.26.011-20260929-150201`. This is a dated observation of one device, not a guarantee for all products sold as Rokid glasses.

Short explicitly authorized Wi-Fi tests on 2026-10-25 confirmed concurrent Camera2 YUV 640×480 capture and 24 kHz PCM microphone transport, approximately 4.6 delivered frames/s, a bounded 10-second buffer, speaker playback and the locally recognized command «выключись». The operator confirmed that the compact HUD is visible and comfortably positioned. Shutdown released camera, recorder and the foreground service; Android returned audio focus to its iPhone Bluetooth receiver. No raw media was saved or sent to OpenAI.

AEC reports enabled; that does not establish echo performance. The device's high-level recording dump reported a silenced client even while the native recording track and decoded local voice command demonstrated live audio. Qualification therefore checks actual audio and command outcomes, not that flag alone. Stock Russian TTS was unavailable, so previews use server-rendered audio.

The Android surface reports 480×640 at density 240. The HUD uses a small central content area, black background and pixel-sized green text, following the [Rokid AIUI monochrome design reference](https://github.com/yodaos-project/AIUI/blob/main/design/monochrome/design-system-green.md). The reference's 480×352 canvas is a design guideline, not a measured optical-resolution claim for this device.

The 30-minute combined media/voice soak, echo/barge-in measurements, phone-call arbitration, network recovery and full cloud conversation are **not yet accepted**. A short tone test is not a sustained duplex-audio test. No p95 latency or gesture accuracy is claimed.

## Acceptance gates

Software checks are reproducible through the [development workflow](development.md). Mock gateways and injected journal failures verify application behavior; they do not exercise controller timing, power loss or physical stopping distance.

- A 30-minute explicitly started device session with camera, microphone, speaker, interruption and bounded memory.
- At least 100 labelled gesture/command episodes, separating target selection, destination selection and correct clarification. Synthetic contract tests do not count as gesture-model evaluation.
- At least 50 physical trials on a declared object/placement set, with a target of 90% complete successful transfers and separately reported error categories.
- Repeated submission, disconnect, stale scene, object movement, failed grasp, restart and cancellation must not cause duplicate or unconfirmed execution.
- Measure p50/p95 response latency and cost per successful task. The target is p95 first spoken acknowledgement within 3 seconds on the declared test network.
- Verify voice stop, heartbeat loss and the independent hardware stop on the actual controller. Record stopping behavior and latency for the qualified hardware.

Until these gates pass, releases are development previews. A simulated or mocked successful operation must never be presented as a physical result.
