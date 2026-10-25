---
description: Install the Rokid APK, pair it with a Python 3.14 agent over TLS, and verify local camera and audio before enabling the voice agent.
---
# Get started

## Agent

Install Python **3.14 or later** and [uv](https://docs.astral.sh/uv/). The lockfile records the tested dependency resolution.

```sh
git clone https://github.com/ykshv/rokid-physical-ai.git
cd rokid-physical-ai
uv sync --locked --all-groups
uv run rokid-agent doctor
```

Start a local diagnostic server first:

```sh
uv run rokid-agent serve --host <COMPUTER_LAN_ADDRESS> --diagnostic
```

Use a specific LAN IP or hostname, not `0.0.0.0`: the generated TLS certificate is bound to this identity. State, the private TLS key, and device credentials live in the OS user-data directory outside the checkout. Existing TLS identities are reused. When changing the hostname, deliberately provision a new identity and re-pair the device.

The diagnostic mode exercises microphone/frame transport and returns a short generated audio tone. It does not call OpenAI or move a robot. Media stays in memory. Server shutdown logs counters, not captured content. Add `--vosk-model <LOCAL_MODEL_DIRECTORY>` to test local voice shutdown without a cloud provider. Say «выключись» to finish; this closes capture and releases audio focus.

## Android application

Use JDK 21, Android SDK platform 37 and Build Tools 36.0.0. Compilation uses current tools while the application targets the stock Android 12 glasses environment.

```sh
cd android
./gradlew assembleDebug lint
```

On Windows use `gradlew.bat`. Set `ANDROID_HOME` to your SDK directory. Install `app/build/outputs/apk/debug/app-debug.apk` using a previously paired ADB connection. Use an explicit serial and isolated ADB server:

```sh
adb -P 15048 -s <GLASSES_SERIAL> install -r app/build/outputs/apk/debug/app-debug.apk
adb -P 15048 -s <GLASSES_SERIAL> shell pm grant io.github.ykshv.rokidphysicalai android.permission.CAMERA
adb -P 15048 -s <GLASSES_SERIAL> shell pm grant io.github.ykshv.rokidphysicalai android.permission.RECORD_AUDIO
```

These permissions do not start recording. Pair from the repository root while the server is running:

```sh
uv run rokid-agent pair --endpoint https://<COMPUTER_LAN_ADDRESS>:8768 --adb <PATH_TO_ADB> --serial <GLASSES_SERIAL>
```

Pairing uses a five-minute single-use code and pins the server certificate. The provisioning activity is protected by Android's `DUMP` permission for ADB/shell access. The individual device credential is encrypted using Android Keystore. No provider key is embedded in the APK.

**Open Rokid Physical AI on the glasses to explicitly start the session.** Initial Android permission dialogs belong to setup. The working interface uses voice and a small two-line HUD on a black optical background. No automatic recording or reconnect-to-motion is enabled. Russian speech is rendered on the server; the tested stock TTS engine has no Russian voice.

The glasses may also be an iPhone Bluetooth audio receiver. The app requests transient exclusive audio focus for its active conversation, uses assistant speech attributes and the built-in speaker/microphone, and releases focus on shutdown. Focus loss ends the session; regaining focus never resumes robot motion. It does not change Bluetooth pairing, global volume, or call mode. Phone-call and all third-party playback combinations still require qualification.

For capability inspection without capture:

```sh
adb -P 15048 -s <GLASSES_SERIAL> shell am start -n io.github.ykshv.rokidphysicalai/.MainActivity --ez diagnostics_only true
```

## Voice agent

Set `OPENAI_API_KEY` in the server process environment. Never put it into the repository, APK, command examples, or issue reports. Download the [Russian small Vosk model](https://alphacephei.com/vosk/models) into a local directory outside the checkout. The offline recognizer handles stop/cancel and explicit confirmation independently of the provider.

The tested local model is `vosk-model-small-ru-0.22` (Apache-2.0), archive SHA-256 `961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4`. This local command recognizer is separate from the conversational model. The assistant's voice is AI-generated.

```sh
uv run rokid-agent serve --host <COMPUTER_LAN_ADDRESS> --vosk-model <LOCAL_MODEL_DIRECTORY>
```

For robot tasks also supply `--workspace-calibration` and `--glasses-calibration`, plus `ROBOT_GATEWAY_URL`, `ROBOT_GATEWAY_TOKEN`, and `ROBOT_GATEWAY_CA`. See [robot setup](robots.md) and [calibration](calibration.md). Without a configured robot the voice interface reports that dependency explicitly.

## Checks

```sh
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest
uv run zensical build --strict
```
