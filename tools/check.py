"""Run the same explicit verification profiles locally and in CI; never access hardware."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
GRADLE = (
    ["cmd.exe", "/d", "/c", str(ROOT / "android/gradlew.bat")]
    if os.name == "nt"
    else ["sh", str(ROOT / "android/gradlew")]
)
PROFILES = {
    "python": [
        [PYTHON, "-m", "ruff", "check", "src", "tests", "tools"],
        [PYTHON, "-m", "ruff", "format", "--check", "src", "tests", "tools"],
        [PYTHON, "-m", "mypy", "src"],
        [PYTHON, "-m", "pytest", "-q"],
    ],
    "docs": [
        [PYTHON, "tools/check_docs.py"],
        [PYTHON, "-m", "zensical", "build", "--strict"],
        [PYTHON, "tools/check_publication.py"],
    ],
    "secrets": [[PYTHON, "tools/check_secrets.py"]],
    "android": [GRADLE + ["-p", "android", "assembleDebug", "lint", "--no-daemon"]],
    "robot": [
        ["docker", "build", "-f", "robot_gateway/Dockerfile", "-t", "rokid-gateway:check", "."]
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="*", help="python, docs, secrets, android, robot, or all")
    args = parser.parse_args()
    profiles = args.profiles or ["python", "docs", "secrets"]
    if "all" in profiles:
        if profiles != ["all"]:
            parser.error("Use all on its own")
        profiles = list(PROFILES)
    if any(profile not in PROFILES for profile in profiles):
        parser.error("Unknown profile; choose python, docs, secrets, android, robot, or all")
    for profile in dict.fromkeys(profiles):
        for command in PROFILES[profile]:
            print(f"[{profile}] {subprocess.list2cmdline(command)}", flush=True)
            try:
                subprocess.run(command, cwd=ROOT, check=True)
            except FileNotFoundError:
                print(f"Required executable unavailable: {command[0]}", file=sys.stderr)
                return 1
            except subprocess.CalledProcessError as exc:
                return exc.returncode or 1
    print("Selected verification profiles passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
