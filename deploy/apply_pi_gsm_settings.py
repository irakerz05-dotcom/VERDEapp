#!/usr/bin/env python3
"""Guardedly install the reviewed GSM settings API into the dirty Pi checkout.

Run --check first. This never edits config.local.json or restarts verde.service.
Fetch feature/gsm-recipient-settings in VERDE-Sensor-Integration before running.
"""

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_COMMIT = "40c3e2313ac1d735b3de2af478ba6629baaac52c"
DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")

CHANGES = {
    "run.py": [
        (
            "        server = make_server(service, args.port, web_root=web_root, trusted_origin=args.trusted_origin)",
            "        server = make_server(service, args.port, web_root=web_root,\n"
            "                             trusted_origin=args.trusted_origin, gsm_config_path=args.config)",
        ),
    ],
    "app/web/__init__.py": [
        (
            "from urllib.parse import urlsplit\n",
            "from urllib.parse import urlsplit\n\nfrom app.gsm_settings import public_settings, update_settings\n",
        ),
        (
            "def make_server(service, port=8000, web_root=None, trusted_origin=None):",
            "def make_server(service, port=8000, web_root=None, trusted_origin=None, gsm_config_path=None):",
        ),
        (
            '            if path == "/api/session":\n'
            '                return self.reply(200, {"token": token})',
            '            if path == "/api/session":\n'
            '                return self.reply(200, {"token": token})\n'
            '            if path == "/api/gsm/settings":\n'
            '                return self.reply(200, public_settings(service))',
        ),
        (
            '                if path == "/api/mode":\n'
            '                    return self.reply(200, service.set_mode(body.get("mode")))',
            '                if path == "/api/mode":\n'
            '                    return self.reply(200, service.set_mode(body.get("mode")))\n'
            '                if path == "/api/gsm/settings":\n'
            '                    try:\n'
            '                        return self.reply(200, update_settings(service, gsm_config_path, body))\n'
            '                    except OSError:\n'
            '                        return self.reply(503, {"error": "Could not save SMS settings on the Pi"})',
        ),
    ],
    "app/notifications/__init__.py": [
        (
            '    NOTIFIABLE = {\n'
            '        "water_quality:classification",\n'
            '        "vision:plant_condition",\n'
            '        "vision:pest",\n'
            '        "fusion:low_confidence",\n'
            '        "sensor:turbidity:critical",\n'
            '    }',
            '    # Thesis Chapter 1/3: confidence and routine humidity/temperature range\n'
            '    # warnings are descriptive; only the listed conditions dispatch SMS.\n'
            '    NOTIFIABLE = {"vision:harvest_ready", "vision:pest", "sensor:turbidity:critical"}',
        ),
        (
            '        return factory(port=self.port, baudrate=self.baudrate,\n'
            '                       timeout=self.timeout_seconds, write_timeout=self.timeout_seconds)\n',
            '        return factory(port=self.port, baudrate=self.baudrate,\n'
            '                       timeout=self.timeout_seconds, write_timeout=self.timeout_seconds)\n'
            '\n'
            '    def configure_alerts(self, enabled, recipient):\n'
            '        """Apply a saved recipient without replacing the modem or cooldown state."""\n'
            '        with self._lock:\n'
            '            self.enabled = enabled\n'
            '            self.recipient = recipient\n'
            '            # A new recipient must not inherit another number\'s cooldown.\n'
            '            self._last_message = None\n'
            '            self._last_sent_at = None\n',
        ),
        (
            '        if issue_key in self.NOTIFIABLE:\n'
            '            return True\n'
            '        return issue_key.startswith("sensor:") and issue_key.endswith(":status") and issue.get("severity") == "critical"',
            '        if issue_key in self.NOTIFIABLE:\n'
            '            return True\n'
            '        if issue.get("severity") != "critical":\n'
            '            return False\n'
            '        return (issue_key == "water_quality:classification"\n'
            '                or issue_key in {"vision:camera", "vision:plant_model", "vision:pest_model"}\n'
            '                or (issue_key.startswith("sensor:") and issue_key.endswith(":status")))',
        ),
    ],
    "app/service.py": [
        (
            '    if plant.value in ("Yellowing", "Wilting"):\n'
            '        add("vision:plant_condition", "vision", "warning",\n'
            '            f"Plant vision detected {plant.value}.")',
            '    if plant.value in ("Yellowing", "Wilting"):\n'
            '        add("vision:plant_condition", "vision", "warning",\n'
            '            f"Plant vision detected {plant.value}.")\n'
            '    if plant.value == "Harvest-Ready":\n'
            '        add("vision:harvest_ready", "vision", "warning",\n'
            '            "Plant vision detected Harvest-Ready lettuce; confirm the harvest schedule.")',
        ),
        (
            '    return issues\n\n\nclass VerdeService:',
            '    return issues\n\n\n'
            'def merge_live_sensor_issues(issues, live):\n'
            '    """Use the integrated Pi cache for SMS incidents, without changing actuation."""\n'
            '    sensors = live.get("sensors") if isinstance(live, dict) else None\n'
            '    if not isinstance(sensors, dict):\n'
            '        return issues\n'
            '    for name in ("ph", "ec", "water_temperature", "turbidity", "ambient_humidity"):\n'
            '        sensor = sensors.get(name)\n'
            '        if not isinstance(sensor, dict):\n'
            '            continue\n'
            '        key = f"sensor:{name}:status"\n'
            '        # Legacy adapters are intentionally disabled on Pi to avoid a second\n'
            '        # hardware owner. Their pending status must not become a GSM event.\n'
            '        issues.pop(key, None)\n'
            '        status = str(sensor.get("status") or "")\n'
            '        failures = sensor.get("consecutive_failures", 0)\n'
            '        persistent = (isinstance(failures, int) and not isinstance(failures, bool)\n'
            '                      and failures >= 2)\n'
            '        if status.startswith("ERROR") or (sensor.get("valid") is False and persistent):\n'
            '            issues[key] = {\n'
            '                "source": "sensor", "severity": "critical",\n'
            '                "message": f"{SENSOR_LABELS[name]} fault: {status}",\n'
            '            }\n'
            '    return issues\n\n\nclass VerdeService:',
        ),
        (
            '            issues = collect_issues(readings, water, plant, pest, fusion, automation, self.config["limits"])\n'
            '            opened, _ = self.record_issue_transitions(issues)',
            '            issues = collect_issues(readings, water, plant, pest, fusion, automation, self.config["limits"])\n'
            '            if camera["status"] == "FAULT / ERROR":\n'
            '                issues["vision:camera"] = {\n'
            '                    "source": "vision", "severity": "critical",\n'
            '                    "message": f"Camera fault: {camera.get(\'detail\') or \'image capture unavailable\'}",\n'
            '                }\n'
            '            integrated = getattr(self, "integrated_sensor_service", None)\n'
            '            if integrated is not None:\n'
            '                try:\n'
            '                    issues = merge_live_sensor_issues(issues, integrated.snapshot())\n'
            '                except Exception:\n'
            '                    log.exception("Integrated sensor incidents unavailable")\n'
            '            opened, _ = self.record_issue_transitions(issues)',
        ),
    ],
}


def source_module(root):
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{BACKEND_COMMIT}:app/gsm_settings.py"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    compile(result.stdout, "app/gsm_settings.py", "exec")
    return result.stdout


def prepare(root):
    module = source_module(root)
    planned = {}
    count = 0
    for name, replacements in CHANGES.items():
        path = root / name
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            if text.count(new) == 1:
                continue
            if text.count(old) == 1:
                text = text.replace(old, new, 1)
                count += 1
            else:
                raise ValueError(f"{name}: expected GSM patch anchor missing or ambiguous")
        compile(text, name, "exec")
        planned[path] = text
    module_path = root / "app/gsm_settings.py"
    if module_path.exists() and module_path.read_text(encoding="utf-8") != module:
        raise ValueError("app/gsm_settings.py exists with different content; do not overwrite it")
    if not module_path.exists():
        planned[module_path] = module
        count += 1
    return planned, count


def atomic_write(path, text):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    try:
        planned, count = prepare(root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"GSM patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {root}; {count} guarded edits; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    changed = []
    for path, content in planned.items():
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        if path.exists():
            backup = path.with_name(f"{path.name}.before_gsm_settings_{stamp}")
            shutil.copy2(path, backup)
            changed.append(f"{path} (backup: {backup})")
        else:
            changed.append(str(path))
        atomic_write(path, content)
    print(f"Updated {len(changed)} files. Service was NOT restarted; SMS was NOT enabled.")
    for item in changed:
        print(item)


if __name__ == "__main__":
    main()
