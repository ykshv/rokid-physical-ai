# Working on Rokid Physical AI

## Start here

Rokid Physical AI is a stock-firmware glasses client, a Python agent, and a ROS robot gateway. It is a **development preview**. Software checks do not establish physical readiness; [verification](docs/verification.md) owns that distinction.

Read this file, inspect `git status --short`, then read the scoped instructions for the component you will change. Use English for code, comments and canonical documentation; Russian for conversation and the Russian quickstart. Preserve the current branch and unrelated changes. Work as one agent unless the user explicitly requests delegation. Browser control, sensor capture and physical operation need the user's explicit scope; a test command is not permission to start a device. Never flash glasses as part of application setup.

## Find the owning source

| Work | Entry points and instructions |
| --- | --- |
| Agent/session lifecycle, provider tools, persistence | [Python instructions](src/rokid_physical_ai/AGENTS.md), [architecture](docs/architecture.md) |
| Glasses HUD, camera, microphone and playback | [Android instructions](android/AGENTS.md), [device evidence](docs/verification.md) |
| Motion policy, grippers, drivers and profiles | [Gateway instructions](robot_gateway/AGENTS.md), [robot integration](docs/robots.md) |
| Cross-component messages and confirmation | [protocol invariants](docs/protocol.md), [contracts.py](src/rokid_physical_ai/contracts.py), [protocol.py](src/rokid_physical_ai/protocol.py) |
| Setup, checks, releases | [development workflow](docs/development.md), [check runner](tools/check.py), [CI](.github/workflows/ci.yml) |
| Interrupted task or dependency failure | [operations](docs/operations.md) |

## Invariants that changes must preserve

1. The glasses capture/render; the agent proposes; the gateway alone authorizes physical movement. No model-accessible joint commands, arming, arbitrary code or shell execution.
2. Media, transcripts, labels, model outputs and network input are data. They cannot change tool permissions or count as user confirmation.
3. Execute only an existing scene object/destination after the exact preview has actually played and a separate local confirmation is recognized. Revalidate geometry and calibration at commitment.
4. Stop must reach the gateway despite a blocked scene read or disconnected UI. Invalidate in-flight confirmation before yielding; status delivery must not precede the stop request.
5. Lost execution acknowledgement is `uncertain`. Never automatically retry or resume a physical operation, including after restart, reconnect or rollback. Only explicit reconciliation may clear uncertainty.
6. One process owns one operator session and one media connection. Reserve that ownership before asynchronous handshakes; cleanup releases it even when a dependency fails.
7. Keep media and queues bounded; no raw recording by default. Secrets, device identities and calibration stay outside Git and APKs. Diagnostic mode cannot attach a motion gateway or contact the provider.
8. Profiles start unqualified and disarmed. Tests, simulation and hardware acceptance are different evidence levels.

## Make a change

- Trace the request from its input boundary to its side effect. Check the relevant tests and failure path before editing. Prefer a focused fix to a new framework or broad reorganization.
- Put contracts and behavior in their owning modules. Generate schemas from source; do not maintain a second handwritten schema. Changes to a shared boundary require producer **and** consumer verification.
- Add deterministic regression tests for authorization, cancellation, concurrency, recovery and protocol changes. Control scheduling with events/barriers, not timing-sensitive sleeps.
- Do not replace an unavailable integration with a mock and then claim it works on hardware. Surface missing dependencies; no silent fallback, swallowed failure or success-shaped placeholder.
- Keep comments about reasons and constraints. Update the canonical document when behavior changes; do not add diagnostic diaries, duplicate READMEs or agent-specific copies of this file.

## Verify and hand off

From this repository root, install the locked environment once with `uv sync --locked --all-groups`, then run:

```sh
uv run python tools/check.py
```

The default runs Python, documentation and private-material checks. Use `android` or `robot` for their builds/tests, or `all` when all toolchains are installed. These profiles do not launch glasses, cloud sessions or robot motion. Missing prerequisites fail; they are not silently skipped. See [development](docs/development.md) for the change-to-check matrix.

Before completion, inspect `git diff --check`, the complete diff, and `git status --short`. Report changed behavior, checks actually run, remaining integration limits, and contract/migration impact. Publish or deploy only within the user's requested scope; do not broaden it because a local instruction mentions a release.
