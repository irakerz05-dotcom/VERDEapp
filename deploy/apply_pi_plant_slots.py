#!/usr/bin/env python3
"""Guardedly add NFT planting-date routes to the Pi's existing backend checkout.

Fetch VERDE-Software feature/planting-slots first. Run --check, then --apply.
No service restart, actuator change, or SMS is performed by this script.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_COMMIT = "a69d0d8"
DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")


def replace_once(source, old, new):
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one anchor, found {count}: {old[:75]!r}")
    return source.replace(old, new, 1)


def backend_module(root):
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{BACKEND_COMMIT}:app/plant_slots.py"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    compile(result.stdout, "app/plant_slots.py", "exec")
    return result.stdout


def patched_web(original):
    if "from app.plant_slots import PlantSlotStore" in original:
        raise ValueError("Plant-slot routes are already present; no changes made")
    result = replace_once(original, "import secrets\n", "import secrets\nimport sqlite3\n")
    result = replace_once(result,
        "from app.gsm_settings import public_settings, update_settings\n",
        "from app.gsm_settings import public_settings, update_settings\n"
        "from app.plant_slots import PlantSlotStore\n")
    result = replace_once(result,
        "    token = secrets.token_urlsafe(32)\n",
        "    token = secrets.token_urlsafe(32)\n"
        "    plant_slots = PlantSlotStore(service.database.path)\n")
    result = replace_once(result,
        '            if path == "/api/gsm/settings":\n'
        '                return self.reply(200, public_settings(service))\n',
        '            if path == "/api/gsm/settings":\n'
        '                return self.reply(200, public_settings(service))\n'
        '            if path == "/api/plant-slots":\n'
        '                try:\n'
        '                    return self.reply(200, plant_slots.list())\n'
        '                except (OSError, sqlite3.Error):\n'
        '                    return self.reply(503, {"error": "Planting records are unavailable"})\n')
    result = replace_once(result,
        '                if path == "/api/confirm":\n',
        '                if path == "/api/plant-slots":\n'
        '                    operation = body.get("operation")\n'
        '                    try:\n'
        '                        if operation == "set" and set(body) == {"operation", "slot", "planted_on"}:\n'
        '                            result = plant_slots.set_date(body["slot"], body["planted_on"])\n'
        '                        elif operation == "clear" and set(body) == {"operation", "slot"}:\n'
        '                            result = plant_slots.clear(body["slot"])\n'
        '                        elif operation == "swap" and set(body) == {"operation", "first", "second"}:\n'
        '                            result = plant_slots.swap(body["first"], body["second"])\n'
        '                        else:\n'
        '                            raise ValueError("Invalid plant-slot operation")\n'
        '                        return self.reply(200, result)\n'
        '                    except (OSError, sqlite3.Error):\n'
        '                        return self.reply(503, {"error": "Could not save planting records on the Pi"})\n'
        '                if path == "/api/confirm":\n')
    compile(result, "app/web/__init__.py", "exec")
    return result


def atomic_write(path, content):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                 prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    web = root / "app/web/__init__.py"
    module = root / "app/plant_slots.py"
    if not web.is_file() or module.exists():
        raise SystemExit("Expected existing web module and no existing app/plant_slots.py")
    module_text = backend_module(root)
    web_text = patched_web(web.read_text(encoding="utf-8"))
    if args.check:
        print(f"Ready: {root}; routes and module syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = web.with_name(f"__init__.py.before_plant_slots_{stamp}")
    shutil.copy2(web, backup)
    atomic_write(module, module_text)
    atomic_write(web, web_text)
    print(f"Updated {web} and {module}")
    print(f"Backup: {backup}")
    print("Service was NOT restarted; planting records are available after a safe restart.")


if __name__ == "__main__":
    main()
