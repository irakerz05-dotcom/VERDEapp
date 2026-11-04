#!/usr/bin/env python3
"""Install a protected, disarmed gateway around VERDE's manual pump code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


SOURCE_CONTROLLER = Path("/home/verde/verde_manual_pumps.py")
SOURCE_GATEWAY = Path(__file__).with_name("pi_auto_pump_driver.py")
TARGET_DIRECTORY = Path("/usr/local/libexec")
TARGET_CONTROLLER = TARGET_DIRECTORY / "verde_manual_pumps.py"
TARGET_GATEWAY = TARGET_DIRECTORY / "verde_auto_pumps.py"
SUDOERS = Path("/etc/sudoers.d/verde-auto-pumps")
STATE_DIRECTORY = Path("/var/lib/verde")
ARM_DIRECTORY = Path("/etc/verde")
ARM_PATH = ARM_DIRECTORY / "pumps-armed"
REVIEWED_GATEWAY_HASHES = {
    "025c766b0a42f6e27fb59c76ac173e1b63e1e35c0eb9a0cdc1d4be5a72f713b8",  # 20 L
    "91c0bf7666e4eae87cd04afd869b7d84ea9ff453e1ea410b54bed679c3aacc0b",  # 12.5 L
    "40c8856817d90d2ab6435559812582927166bcbc39a1da9922ca57a75e00435b",  # 18 L at abe6b12
    "81df6018cd9e00b6c30c9910ac1bd46aafd2ab7876bd1b5e6ecde4a6195b3da7",  # current 18 L gateway
    "3b0a61bf59e4c78268e71ff881ff31ed30ce8c8289a6ea579e2753630d7ef94d",  # 18 L manual gateway
    "2bf947d789437e374ca7fb0fa186d386323ee1d6991bbb7ff13a5d9782e5bf16",  # supervised flow recovery
}
SUDOERS_TEXT = """# VERDE protected pump gateway. arm/disarm require interactive sudo.
verde ALL=(root) NOPASSWD: /usr/local/libexec/verde_auto_pumps.py status, /usr/local/libexec/verde_auto_pumps.py safe-off, /usr/local/libexec/verde_auto_pumps.py circulation *, /usr/local/libexec/verde_auto_pumps.py resume-flow, /usr/local/libexec/verde_auto_pumps.py dose *, /usr/local/libexec/verde_auto_pumps.py manual-dose *
"""


def validate_manual_source(source):
    tree = ast.parse(source, filename=str(SOURCE_CONTROLLER))
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    needed = {"set_level", "pin_state", "require_dosing_off", "lock_control",
              "dose", "dosing_off"}
    if not needed <= names:
        raise ValueError(f"Manual controller methods changed: {sorted(needed - names)}")
    anchors = (
        'DOSING_PINS = {"pump1": 27, "pump2": 22, "pump3": 23}',
        "CIRCULATION_PIN = 24", "MAX_SECONDS = 5.0",
        'set_level(pin, "dh")  # Return the selected relay to OFF even on error.',
        "require_dosing_off()",
    )
    for anchor in anchors:
        if source.count(anchor) < 1:
            raise ValueError(f"Manual controller safety anchor changed: {anchor}")
    compile(source, str(SOURCE_CONTROLLER), "exec")


def install_file(source_bytes, target, mode):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manual_source = SOURCE_CONTROLLER.read_text(encoding="utf-8")
    gateway_source = SOURCE_GATEWAY.read_text(encoding="utf-8")
    validate_manual_source(manual_source)
    compile(gateway_source, str(SOURCE_GATEWAY), "exec")
    if TARGET_GATEWAY.exists():
        installed_hash = hashlib.sha256(TARGET_GATEWAY.read_bytes()).hexdigest()
        current_hash = hashlib.sha256(gateway_source.encode()).hexdigest()
        if installed_hash not in REVIEWED_GATEWAY_HASHES | {current_hash}:
            parser.error("Installed pump gateway differs from reviewed versions")
    if args.check:
        print("Ready: reviewed manual GPIO mapping, five-second limit, "
              "protected gateway syntax; no files changed")
        return
    if os.geteuid() != 0:
        parser.error("--apply requires sudo")
    if shutil.which("visudo") is None:
        parser.error("visudo is unavailable; sudoers was not changed")
    if ARM_PATH.exists():
        parser.error("Pump gateway is armed; disarm it before updating protected files")
    TARGET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for directory in (TARGET_DIRECTORY, SUDOERS.parent):
        metadata = directory.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            parser.error(f"Protected installation directory is writable: {directory}")
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    ARM_DIRECTORY.mkdir(parents=True, exist_ok=True)
    os.chown(STATE_DIRECTORY, 0, 0)
    os.chmod(STATE_DIRECTORY, 0o700)
    os.chown(ARM_DIRECTORY, 0, 0)
    os.chmod(ARM_DIRECTORY, 0o700)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for target in (TARGET_CONTROLLER, TARGET_GATEWAY, SUDOERS):
        if target.exists():
            backup = target.with_name(f"{target.name}.before_auto_pumps_{stamp}")
            shutil.copy2(target, backup)
            print(f"Backup: {backup}")
    install_file(manual_source.encode(), TARGET_CONTROLLER, 0o755)
    install_file(gateway_source.encode(), TARGET_GATEWAY, 0o755)
    # Validate the exact candidate before it can become an active sudoers rule.
    descriptor, candidate = tempfile.mkstemp(prefix=".verde-auto-pumps.", dir=SUDOERS.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(SUDOERS_TEXT)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(candidate, 0, 0)
        os.chmod(candidate, 0o440)
        subprocess.run((shutil.which("visudo"), "-cf", candidate), check=True, timeout=10)
        os.replace(candidate, SUDOERS)
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)
    print(f"Installed protected manual copy: {TARGET_CONTROLLER}")
    print(f"Installed disarmed gateway: {TARGET_GATEWAY}")
    print(f"Installed scoped sudoers rule: {SUDOERS}")
    print("Controller remains DISARMED. No GPIO was switched and no dose was sent.")


if __name__ == "__main__":
    main()
