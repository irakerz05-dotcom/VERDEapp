#!/usr/bin/env python3
"""Guardedly notify for camera Harvest-Ready detections in fixed zones P1-P6."""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
HELPER = Path(__file__).with_name("pi_vision_harvest_alerts.py")


def replace_once(source, old, new, label):
    if source.count(new) == 1:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: installed source differs from reviewed version")
    return source.replace(old, new, 1)


def patch_policy(source):
    source = replace_once(source, "import math\n", "import math\n\nfrom app.notifications.vision_harvest_alerts import harvest_ready_slots\n", "policy import")
    source = replace_once(source,
        "def enrich_issues(issues, live_snapshot=None, fusion_by_slot=None):",
        "def enrich_issues(issues, live_snapshot=None, fusion_by_slot=None, vision_report=None):",
        "policy signature")
    start = '    if isinstance(fusion_by_slot, list):\n        issues.pop("vision:harvest_ready", None)\n'
    if start in source:
        prefix, remainder = source.split(start, 1)
        old, ending = remainder.split("    return issues\n", 1)
        if ('if condition == "Harvest-Ready"' not in old
                or 'elif "vision:harvest_ready" in issues:' not in old):
            raise ValueError("policy harvest block differs from reviewed version")
        source = (prefix + '    issues.pop("vision:harvest_ready", None)\n'
                  '    for slot in harvest_ready_slots(vision_report):\n'
                  '        issues[f"vision:slot:{slot}:harvest_ready"] = {\n'
                  '            "source": "vision", "severity": "notice",\n'
                  '            "message": f"Camera detected Harvest-Ready plant P{slot}. Check the plant.",\n'
                  '        }\n'
                  '    return issues\n' + ending)
    elif 'for slot in harvest_ready_slots(vision_report):' not in source:
        raise ValueError("policy harvest block is missing")
    compile(source, "app/notifications/alert_policy.py", "exec")
    return source


def patch_service(source):
    old = '            issues = enrich_issues(issues, live_snapshot, locals().get("fusion_by_slot"))\n'
    new = ('            vision_report = None\n'
           '            store = getattr(self, "vision_store", None)\n'
           '            capture_version = camera.get("ai_capture_version")\n'
           '            if store is not None and plant.status == "READY" and capture_version:\n'
           '                try:\n'
           '                    candidate = store.read()\n'
           '                    reported = candidate.get("plant_condition")\n'
           '                    if (candidate.get("generated_at") == capture_version\n'
           '                            and isinstance(reported, dict)\n'
           '                            and reported.get("status") == plant.status\n'
           '                            and reported.get("value") == plant.value):\n'
           '                        vision_report = candidate\n'
           '                except (OSError, ValueError, TypeError, KeyError, TimeoutError):\n'
           '                    pass\n'
           '            issues = enrich_issues(issues, live_snapshot, locals().get("fusion_by_slot"), vision_report)\n')
    source = replace_once(source, old, new, "service vision alert")
    compile(source, "app/service.py", "exec")
    return source


def patch_sms(source):
    source = replace_once(source,
        'message = f"Plant {number} is now Harvest-Ready. Check the harvest schedule."',
        'message = f"Camera detected Harvest-Ready plant P{number}. Check the plant."',
        "SMS text")
    compile(source, "app/notifications/sms_text.py", "exec")
    return source


def plan(root=BACKEND):
    targets = {
        root / "app/notifications/vision_harvest_alerts.py": HELPER.read_text(encoding="utf-8"),
        root / "app/notifications/alert_policy.py": patch_policy((root / "app/notifications/alert_policy.py").read_text(encoding="utf-8")),
        root / "app/notifications/sms_text.py": patch_sms((root / "app/notifications/sms_text.py").read_text(encoding="utf-8")),
        root / "app/service.py": patch_service((root / "app/service.py").read_text(encoding="utf-8")),
    }
    for path, contents in targets.items():
        compile(contents, str(path), "exec")
    return [(path, contents) for path, contents in targets.items()
            if not path.exists() or path.read_text(encoding="utf-8") != contents]


def atomic_write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    try:
        changes = plan(args.target)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Vision harvest SMS update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded vision/SMS files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        if path.exists():
            backup = path.with_name(f"{path.name}.before_vision_harvest_sms_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
    for path, contents in changes:
        atomic_write(path, contents)
        print(f"Updated: {path}")
    print("Service was NOT restarted. No SMS or pump command was issued by this installer.")


if __name__ == "__main__":
    main()
