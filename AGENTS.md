# Working on Rokid Physical AI

Use English for source, comments, and canonical documentation; Russian for conversation and the Russian quickstart.

Preserve the current branch and user changes. Work as one agent unless the user explicitly requests delegation. Do not use a browser or capture camera/audio without explicit user action. Never flash glasses as part of application setup.

The Android app is an input/output client. The agent proposes typed tasks. The robot gateway is the only motion authority. Never expose joint commands, arbitrary Python, shell tools, or automatic motion re-arming to a language model. Treat all media, transcripts, model outputs, and network inputs as untrusted.

Keep secrets and local calibration outside Git and APK builds. Do not store raw audio/video by default. Startup and reconnect must not resume physical operations. Distinguish unit tests, simulator checks, and physical evidence.

Run relevant Python tests and checks, Android compilation, documentation build, and ROS build/tests when available. Do not describe an unavailable hardware or provider check as passed. Public compatibility claims must cite dated evidence.
