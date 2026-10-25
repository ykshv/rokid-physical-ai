---
description: Develop Rokid Physical AI with scoped agent instructions, reproducible local and CI checks, shared protocol tests, and explicit release evidence.
---
# Development workflow

The repository is designed for agents and humans to use the same source of truth and verification commands. Start with `AGENTS.md` at the repository root; component instructions live beside Python, Android and ROS sources. They identify ownership, constraints and the relevant tests. User authorization is separate from those instructions.

## Reproducible setup

Use Python 3.14+ and install `uv sync --locked --all-groups`. Run `uv run rokid-agent doctor` to inspect configuration presence; it does not call the provider or connect to hardware. Never paste private state paths or credentials into public reports.

Run checks from the repository root:

```sh
uv run python tools/check.py
```

This runs Python lint/format/types/tests, repository documentation links, the strict documentation build, public HTML checks and a source private-material scan. Failures return a nonzero status immediately. Missing tools never become skipped successes. CI invokes the same profiles on Windows and Linux.

| Change | Required profiles and evidence |
| --- | --- |
| Python logic or configuration | `python`; add regression cases for changed behavior |
| Shared scene or task boundary | `python robot`; update both consumers and schema generation |
| Android protocol, media or HUD | `python android`; qualify relevant behavior on the actual glasses separately |
| Gateway, gripper or robot profile | `robot python`; simulation and physical gates remain separate |
| Documentation or agent instructions | `docs`; verify commands against the owning code |
| Dependency lock or build workflow | Every affected profile; keep compatible changes in one revision |
| Any proposed publication | `secrets`, complete diff review, relevant profiles and an honest evidence statement |

Examples:

```sh
uv run python tools/check.py python docs
uv run python tools/check.py android
uv run python tools/check.py robot
uv run python tools/check.py all
```

Android requires JDK 21 and the SDK from [quickstart](quickstart.md). ROS checks require a Linux Docker engine; the build compiles vendor messages and the gateway, then runs gateway policy tests. These commands never install or launch an APK, open a camera, make a model request, arm a robot or publish a release. Build dependencies may be downloaded.

## Changes to behavior

Trace a proposed change from its input boundary to its side effect. State the invariant it must preserve. For failures involving cancellation or concurrency, make a deterministic regression with controlled await points; a sleep-based stress test is not a substitute for reproducing the race.

Pydantic definitions generate public JSON schemas with `uv run rokid-agent schemas --output dist/schemas`. The scene acceptance fixture in `robot_gateway/test/fixtures/scene_validation.json` runs in both pytest and GTest. Keep all producers/consumers compatible; a new required field or changed meaning requires an explicit protocol migration and supported-version decision.

Normal tests use temporary SQLite stores, fake gateways, synthetic images and scripted provider responses. They never use an ambient API key or connected arm. The [verification gates](verification.md) describe the separate consented dataset and hardware work. Do not expand automated tests into sensor capture or live robot trials implicitly.

## Review and release

Before handing off, inspect `git diff --check`, the complete diff and `git status --short`. Describe behavior and evidence, including unrun checks and their prerequisites. The pull request template asks for compatibility/recovery impact; both human and agent changes use it.

A development release identifies the exact Git revision, tested lockfile/toolchain, APK signing status and SHA-256 checksums. Its notes link to verification evidence. Pin the same revision for the agent, generated schemas, gateway/profile and APK when reproducing a failure; provider model and prompt identifiers are recorded in source. Model aliases are not immutable provider weights and require fresh live evaluation when changed.

Rollback does not undo physical side effects. Stop the active session and gateway, inspect/reconcile uncertain operations, preserve the state database/journal, then restore a compatible application revision. Never delete the journal or replace it with a clean file to make a rollback appear successful. See [operations](operations.md).

## Public website and search

Keep `https://ykshv.github.io/rokid-physical-ai/` as the canonical documentation URL and `https://ykshv.github.io/rokid-physical-ai/sitemap.xml` as its sitemap. The GitHub About URL, generated canonical links and sitemap must agree. `tools/check_publication.py` validates navigation pages, unique titles/descriptions, social metadata, visible author links and homepage structured data before deployment.

The homepage's `SoftwareSourceCode` describes this repository and uses the same author identity as the personal website, `https://igor-ya.ru/#person`. Keep authorship visible, preserve truthful qualification limits, and link only to existing relevant articles. The shared documentation theme and README structure also apply to [Rula](https://ykshv.github.io/rula/).

GitHub project Pages live under a path: crawler policy belongs to the origin's `/robots.txt`, not a file inside the project directory. A missing origin robots file does not itself block indexing. Do not add an ineffective project-level file or special AI text files as an indexing requirement.

After publication, inspect response headers, canonical HTML and sitemap. A maintainer with Search Console or Bing Webmaster Tools access can submit the sitemap and inspect indexing. Passing HTTP/build checks establishes eligibility, not guaranteed indexing, rankings or AI citations.
