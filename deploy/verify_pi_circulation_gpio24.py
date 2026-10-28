#!/usr/bin/env python3
"""Supervised GPIO24 flow test. Never doses or configures automation."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from urllib.request import urlopen


PIN = "24"
LOCK_PATH = "/run/verde-manual-pumps.lock"
BASELINE = ("no", "pd")


def pinctrl(binary, *args):
    return subprocess.run(
        (binary, *args), check=True, capture_output=True, text=True, timeout=3
    ).stdout.strip()


def pin_state(binary):
    return pinctrl(binary, "get", PIN)


def baseline_state(binary):
    return bool(re.match(r"^24:\s+no\s+pd\s+\|", pin_state(binary)))


def service_outputs_disabled():
    with urlopen("http://127.0.0.1:8000/api/status", timeout=5) as response:
        automation = json.load(response).get("automation", {})
    return automation.get("actuation_enabled") is False


def answer(prompt):
    response = input(prompt).strip().lower()
    if response not in ("yes", "no", "unsure"):
        raise ValueError("Expected yes, no, or unsure; test stopped")
    return response


def restore(binary):
    pinctrl(binary, "set", PIN, *BASELINE)
    if not baseline_state(binary):
        raise RuntimeError("GPIO24 did not return to its starting mode")


def test_level(binary, level, seconds):
    try:
        pinctrl(binary, "set", PIN, "op", level)
        state = pin_state(binary)
        if not re.match(rf"^24:\s+op\s+{level}\b", state):
            raise RuntimeError(f"GPIO24 did not enter requested state: {state}")
        print(f"GPIO24 {level.upper()} for {seconds:g} seconds: {state}", flush=True)
        time.sleep(seconds)
    finally:
        restore(binary)
        print(f"GPIO24 restored: {pin_state(binary)}", flush=True)
    observed = answer(f"During GPIO24 {level.upper()}, was water flowing? [yes/no/unsure] ")
    if answer("Is water flowing again now? [yes/no/unsure] ") != "yes":
        raise RuntimeError("Baseline flow not restored; test stopped")
    return observed


def run(seconds):
    import fcntl

    if os.geteuid() != 0:
        raise RuntimeError("Run with sudo; GPIO writes require root")
    binary = shutil.which("pinctrl")
    if binary is None:
        raise RuntimeError("pinctrl is unavailable")
    if not service_outputs_disabled():
        raise RuntimeError("VERDE automation must report actuation_enabled=false")
    if not baseline_state(binary):
        raise RuntimeError(f"GPIO24 starting state changed: {pin_state(binary)}")
    lock = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(f"Starting GPIO24 state: {pin_state(binary)}", flush=True)
        if answer("Is circulation flowing now, and are you watching it? [yes/no/unsure] ") != "yes":
            raise RuntimeError("Physical observer required; no GPIO change made")
        high = test_level(binary, "dh", seconds)
        low = test_level(binary, "dl", seconds)
        print(f"Observed flow: HIGH={high}, LOW={low}")
        if {high, low} == {"yes", "no"}:
            print("GPIO24 flow level was observed. Retest before enabling automatic control.")
        else:
            print("Flow polarity remains unverified; leave automatic circulation disabled.")
    finally:
        try:
            restore(binary)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="perform supervised five-second states")
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    if not 0 < args.seconds <= 5:
        parser.error("seconds must be greater than 0 and at most 5")
    if not args.run:
        print("Read-only check: no GPIO changed. Add --run with an observer present.")
        return
    try:
        run(args.seconds)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"GPIO24 test stopped: {exc}\n")


if __name__ == "__main__":
    main()
