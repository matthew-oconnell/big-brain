#!/usr/bin/env python3
"""
Minimal terminal capture script — called from the shell hook after every command.

Must stay fast: uses only stdlib, no bb package imports.
Usage: python3 capture.py <cmd> <cwd> <exit_code>
"""

import json
import sys
import urllib.error
import urllib.request

DAEMON_URL = "http://localhost:7777/ingest/terminal"


def main() -> None:
    if len(sys.argv) < 2:
        return

    cmd = sys.argv[1].strip()
    cwd = sys.argv[2] if len(sys.argv) > 2 else ""
    exit_code = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    if not cmd:
        return

    payload = json.dumps({"cmd": cmd, "cwd": cwd, "exit_code": exit_code}).encode()
    req = urllib.request.Request(
        DAEMON_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        # Daemon not running — silently ignore
        pass


if __name__ == "__main__":
    main()
