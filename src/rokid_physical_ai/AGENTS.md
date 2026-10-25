# Python agent

Inherits the repository [AGENTS.md](../../AGENTS.md). Python **3.14+**; dependencies and resolution belong to [pyproject.toml](../../pyproject.toml) and `uv.lock`.

## Ownership

- [app.py](app.py) owns authenticated device sessions, media lifecycle and integration of local commands, narration and provider tools.
- [engine.py](engine.py) owns task transitions and confirmation. [store.py](store.py) persists operations, transitions and hashed credentials. A model tool cannot mutate state directly.
- [contracts.py](contracts.py) owns shared domain messages; [protocol.py](protocol.py) owns inbound device control messages. [gateway.py](gateway.py) validates robot responses, including operation identity.
- [realtime.py](realtime.py) owns provider transport, prompt, tool schemas and budgets. [narration.py](narration.py) renders the exact preview; [speech.py](speech.py) handles local control words independently of the provider.
- [frames.py](frames.py) owns bounded ephemeral images. [perception.py](perception.py) and [camera_worker.py](camera_worker.py) own calibrated geometry. Client timestamps never grant freshness.

## Changes that need special care

- All engine/session state runs on one asyncio event loop. SQLite and image decoding have their own thread boundaries. Do not move stateful engine methods into worker threads.
- A lock serializes proposals/confirmation; it must not delay the gateway stop request. Invalidate pending asynchronous reads before awaiting stop. Cancellation before an asyncio task first runs still needs a durable terminal state.
- Persist `executing` before dispatch. After dispatch, cancellation or missing/mismatched results means uncertainty. Never infer a physical result from a transport exception.
- Keep blocking recognition/image work off the event loop. Every new background task needs an owner, error observation and cancellation during teardown.
- Do not log captured content, provider errors, arbitrary client diagnostics or credentials. Use bounded categories, operation/session IDs and counters.
- Keep provider models/prompts/tools in source and dependencies locked. A provider or prompt change needs scripted protocol tests plus an explicitly authorized live evaluation before claiming compatibility; there is no automatic model fallback.

Run `uv run python tools/check.py python` from the repository root. Relevant suites: [engine races/recovery](../../tests/test_engine.py), [ASGI session ownership](../../tests/test_sessions.py), [boundary validation](../../tests/test_boundaries.py), [narration](../../tests/test_narration.py), [cross-language scene cases](../../tests/test_contract_parity.py). These use temporary state and synthetic input, without provider keys or hardware.
