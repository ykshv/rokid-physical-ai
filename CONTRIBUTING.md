# Contributing

Start with a focused issue describing the intended behavior, hardware, firmware, and evidence. Keep credentials, identifiable recordings, serial numbers, and local network details out of reports.

Read [AGENTS.md](AGENTS.md) and the scoped component instructions before changing code. Human and agent contributions use the same [development workflow](docs/development.md), [protocol invariants](docs/protocol.md), and verification profiles. Use Python 3.14+, the Gradle wrapper, and the pinned ROS driver revisions. Run `uv run python tools/check.py` plus the affected Android/robot profiles. Add regression tests for changed authority, protocol, cancellation, and recovery behavior. Describe which checks are unit tests, simulator tests, or physical tests.

New robot profiles must default to motion disabled. Do not introduce model-accessible arming, arbitrary code execution, automatic physical retries, or hidden recording. Public compatibility claims require evidence on that hardware.

By contributing, you agree to license your original contributions under Apache-2.0. Preserve notices for third-party code and assets.
