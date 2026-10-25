# Contributing

Start with a focused issue describing the intended behavior, hardware, firmware, and evidence. Keep credentials, identifiable recordings, serial numbers, and local network details out of reports.

Use Python 3.14+, the Gradle wrapper, and the pinned ROS driver revisions. Run the checks in the [quickstart](docs/quickstart.md). Add regression tests for changed authority, protocol, cancellation, and recovery behavior. Describe which checks are unit tests, simulator tests, or physical tests.

New robot profiles must default to motion disabled. Do not introduce model-accessible arming, arbitrary code execution, automatic physical retries, or hidden recording. Public compatibility claims require evidence on that hardware.

By contributing, you agree to license your original contributions under Apache-2.0. Preserve notices for third-party code and assets.
