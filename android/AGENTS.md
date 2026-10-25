# Rokid Android client

Inherits the repository [AGENTS.md](../AGENTS.md). Read the dated [device evidence](../docs/verification.md) before assuming a camera, display or audio capability.

## Responsibilities

[CaptureService.kt](app/src/main/java/io/github/ykshv/rokidphysicalai/CaptureService.kt) owns capture, audio focus, sockets, playback and teardown. [CameraCapture.kt](app/src/main/java/io/github/ykshv/rokidphysicalai/CameraCapture.kt) serializes Camera2 lifecycle. [Identity.kt](app/src/main/java/io/github/ykshv/rokidphysicalai/Identity.kt) owns certificate pinning and encrypted device credentials. [GlassesHud.kt](app/src/main/java/io/github/ykshv/rokidphysicalai/GlassesHud.kt) owns optical layout; the Activity is not a phone dashboard.

## Preserve these constraints

- Keep a black optical background and sparse central text. Android's 480×640 surface is not the measured optical resolution. Do not replace the qualified HUD with a full-screen panel, filled background or ordinary phone layout.
- No capture during pairing or capability inspection. A foreground session starts explicitly; focus loss, transport failure or stop tears down camera, recorder, playback, sockets and wake lock. Reconnection is not permission to resume capture/motion.
- The glasses can receive iPhone Bluetooth audio. Keep assistant speech attributes consistent between `AudioFocusRequest` and `AudioTrack`, request transient exclusive focus, and release it on shutdown. Do not change global volume, Bluetooth pairing or call mode to conceal routing failures.
- The short-prompt start threshold is intentional: the device's default streaming buffer otherwise prevented the tested short tone from starting.
- Playback completion means the hardware playback head reached the last sample, not that bytes entered a queue. `preview.played` grants the server a confirmation window; never send it early or after an audio-generation flush.
- Keep queues bounded and reject stale playback generations. Close Camera2 on its owning handler. Preserve cleanup on partial startup failures.
- No provider secret in the APK; only the separately provisioned per-device credential. Preserve pinning, hostname verification and the restricted provisioning Activity.

Run `uv run python tools/check.py android` from the repository root with JDK 21 and `ANDROID_HOME` configured as in [quickstart](../docs/quickstart.md). Building does not install or launch the app. Device checks require an explicit user session; report compilation, installation and user-observed behavior separately.
