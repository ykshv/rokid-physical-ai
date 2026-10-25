"""Reject common private artifacts and embedded credentials without printing their contents."""

import re
import subprocess
from pathlib import Path

paths = (
    subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    .decode()
    .split("\0")
)
patterns = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{40,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
]
violations = []
for name in filter(None, paths):
    path = Path(name)
    if path.suffix in (".p12", ".jks", ".sqlite3", ".key") or path.name == ".env":
        violations.append(name)
    if path.is_file() and path.stat().st_size < 2_000_000:
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in patterns):
            violations.append(name)
if violations:
    raise SystemExit("Private material detected in: " + ", ".join(sorted(set(violations))))
print("Tracked and non-ignored new files passed the private-material check")
