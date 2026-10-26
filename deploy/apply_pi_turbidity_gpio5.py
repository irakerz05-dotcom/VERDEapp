#!/usr/bin/env python3
"""Prepare the Pi service to read GPIO5 as a digital turbidity threshold.

Run --check before --apply. --apply backs up the source and does not restart
the service. The DFRobot D output must be verified 3.3 V compatible before
restarting: Raspberry Pi GPIO inputs are not 5 V tolerant.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


TARGET = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
REPLACEMENTS = (
    ("GPIO input import", "from gpiozero import OutputDevice\n",
     "from gpiozero import InputDevice, OutputDevice\n"),
    ("remove unrelated A0 read", '''            self.turbidity_channel = RollingAnalogChannel(
                "turbidity", AnalogIn(self.ads, ADS.P0)
            )''',
     "            self.turbidity_channel = None"),
    ("GPIO5 initialization", '            self.ads_setup_error = f"{type(exc).__name__}: {exc}"\n',
     '''            self.ads_setup_error = f"{type(exc).__name__}: {exc}"
        self.turbidity_digital_device = None
        self.turbidity_digital_error = None
        try:
            # An external circuit must supply a safe, defined 3.3 V logic level.
            self.turbidity_digital_device = InputDevice(5, pull_up=None, active_state=True)
        except Exception as exc:
            self.turbidity_digital_error = f"{type(exc).__name__}: {exc}"
            self.error_counts["turbidity_gpio5_setup"] += 1
'''),
    ("stop A0 acquisition", "        turb_reading, turb_read_status = self._safe_analog(self.turbidity_channel)\n",
     '''        turb_reading = None
        turb_read_status = "UNAVAILABLE: turbidity is not connected to ADS1115"
'''),
    ("digital state", "        available = [\n", '''        # GPIO5 is a one-bit threshold signal. Its polarity and threshold
        # have not been verified; it cannot produce a numeric NTU reading.
        turbidity = {
            "value": None, "value_ntu": None, "unit": None,
            "classification": "UNAVAILABLE", "digital_level": None,
            "status": "UNAVAILABLE: GPIO5 digital input",
            "measurement_type": "DIGITAL_THRESHOLD_ONLY",
        }
        if self.turbidity_digital_device is not None:
            try:
                level = int(self.turbidity_digital_device.value)
                if level not in (0, 1):
                    raise ValueError("GPIO5 returned a non-binary state")
                turbidity.update(digital_level=level, status="DIGITAL_THRESHOLD")
            except Exception as exc:
                self.error_counts["turbidity_gpio5_read"] += 1
                turbidity["status"] = f"ERROR: GPIO5 digital read: {type(exc).__name__}: {exc}"
        elif self.turbidity_digital_error:
            turbidity["status"] = f"ERROR: GPIO5 setup: {self.turbidity_digital_error}"

        available = [
'''),
    ("GPIO cleanup", "            if self.dht11_device is not None:\n", '''            if self.turbidity_digital_device is not None:
                self.turbidity_digital_device.close()
            if self.dht11_device is not None:
'''),
)


def transform(source):
    if "DIGITAL_THRESHOLD_ONLY" in source:
        raise ValueError("GPIO5 digital threshold integration is already present")
    for description, old, new in REPLACEMENTS:
        if source.count(old) != 1:
            raise ValueError(f"Expected exactly one source anchor for {description}")
        source = source.replace(old, new, 1)
    compile(source, str(TARGET), "exec")
    return source


def apply(path=TARGET):
    updated = transform(path.read_text(encoding="utf-8"))
    backup = path.with_name(f"{path.name}.before_turbidity_gpio5_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
    shutil.copy2(path, backup)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(updated)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--signal-3v3-verified", action="store_true",
                        help="Confirm GPIO5's HIGH signal has been made safe for 3.3 V input")
    args = parser.parse_args()
    if args.check:
        transform(TARGET.read_text(encoding="utf-8"))
        print("Ready: guarded GPIO5 digital threshold edits; syntax valid; no files changed")
    else:
        if not args.signal_3v3_verified:
            parser.error("--apply requires --signal-3v3-verified; do not activate an unverified 5 V signal")
        backup = apply()
        print(f"Updated {TARGET}; backup: {backup}")
        print("Service was NOT restarted. No numeric NTU or safety override was enabled.")


if __name__ == "__main__":
    main()
