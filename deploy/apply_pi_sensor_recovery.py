#!/usr/bin/env python3
"""Guarded update for the Pi's untracked sensor owner; --check never writes.

The Pi retains a timestamped, recoverable copy before --apply replaces the
source. GPIO mappings, calibration constants, and automation are untouched.
"""

import argparse
import os
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path


TARGET = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
MARKER = "# VERDE-SENSOR-RECOVERY-v1"
UPGRADED_MARKER = "# VERDE-SENSOR-RECOVERY-v2"
FINAL_MARKER = "# VERDE-SENSOR-RECOVERY-v3"


REPLACEMENTS = [
    ("logging import", "import json\nimport math\n", "import json\nimport logging\nimport math\n"),
    ("logger", "from gpiozero import OutputDevice\n\n\nADS1115_ADDRESS", "from gpiozero import OutputDevice\n\n\nlog = logging.getLogger(__name__)\n\nADS1115_ADDRESS"),
    ("retry state", "        self.error_counts = Counter()\n        self.last_valid_ph = None", "        self.error_counts = Counter()\n        self.ds18b20_failures = 0\n        self.dht11_failures = 0\n        self.sensor_recovery_limit = 5\n        self.last_valid_ph = None"),
    ("startup 1-Wire discovery", '''        self.ds18b20_device = discover_ds18b20()
        try:
            self.dht11_device = open_dht11()
''', '''        try:
            self.ds18b20_device = discover_ds18b20()
        except OSError as exc:
            self.ds18b20_device = None
            self.error_counts["ds18b20_discovery"] += 1
            log.warning("DS18B20 startup discovery failed; will retry: %s: %s",
                        type(exc).__name__, exc)
        try:
            self.dht11_device = open_dht11()
'''),
    ("DHT raw capture", '''def read_dht11(device):
    humidity = device.humidity
    if (isinstance(humidity, bool) or not isinstance(humidity, (int, float))
            or not math.isfinite(humidity) or not 0 <= humidity <= 100):
        raise ValueError("no valid DHT11 humidity value")
    return float(humidity)
''', '''def read_dht11(device, raw_capture=None):
    humidity = device.humidity
    if raw_capture is not None:
        raw_capture.append(humidity)
    if (isinstance(humidity, bool) or not isinstance(humidity, (int, float))
            or not math.isfinite(humidity) or not 0 <= humidity <= 100):
        raise ValueError("no valid DHT11 humidity value")
    return float(humidity)
'''),
    ("1-Wire raw capture", '''def read_ds18b20(device):
    if device is None:
        raise RuntimeError("no valid 28-* DS18B20 device")
    lines = (device / "w1_slave").read_text(encoding="ascii").splitlines()
''', '''def read_ds18b20(device, raw_capture=None):
    if device is None:
        raise RuntimeError("no valid 28-* DS18B20 device")
    raw_text = (device / "w1_slave").read_text(encoding="ascii")
    if raw_capture is not None:
        raw_capture.append(raw_text)
    lines = raw_text.splitlines()
'''),
    ("retry methods", "    def _safe_analog(self, channel):\n", '''    # VERDE-SENSOR-RECOVERY-v1
    # VERDE-SENSOR-RECOVERY-v2
    # VERDE-SENSOR-RECOVERY-v3
    @staticmethod
    def _sensor_diagnostic(name, raw, parsed, status, error=None, attempt=1):
        log.info(
            "sensor_read name=%s raw=%r parsed=%r status=%s timestamp=%s read_error=%r attempt=%s",
            name, raw, parsed, status, timestamp_now(), error, attempt,
        )

    def _read_water_temperature(self):
        last_error = None
        for attempt in range(1, 3):
            raw = []
            try:
                # Rediscover on each attempt: a lost 1-Wire device may return.
                self.ds18b20_device = discover_ds18b20()
                value = read_ds18b20(self.ds18b20_device, raw)
                self.ds18b20_failures = 0
                status = f"OK: {self.ds18b20_device.name}; no software offset"
                self._sensor_diagnostic("water_temperature", raw[0] if raw else None,
                                        value, status, attempt=attempt)
                return {
                    "value_C": value, "unit": "C",
                    "classification": classify_water_temperature(value),
                    "status": status, "read_timestamp": timestamp_now(),
                    "read_error": None,
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._sensor_diagnostic("water_temperature", raw[0] if raw else None,
                                        None, "RETRYING" if attempt == 1 else "READ FAILED",
                                        last_error, attempt)
                if attempt == 1:
                    time.sleep(0.25)
        self.error_counts["ds18b20_read"] += 1
        self.ds18b20_failures += 1
        status = ("RECOVERING" if self.ds18b20_failures <= self.sensor_recovery_limit else "ERROR") + f": {last_error}"
        self._sensor_diagnostic("water_temperature", None, None, status, last_error, 2)
        return {
            "value_C": None, "unit": "C", "classification": "UNAVAILABLE",
            "status": status, "read_timestamp": timestamp_now(), "read_error": last_error,
        }

    def _read_humidity(self):
        last_error = None
        for attempt in range(1, 4):
            raw = []
            try:
                if self.dht11_device is None:
                    self.dht11_device = open_dht11()
                    self.dht11_setup_error = None
                value = read_dht11(self.dht11_device, raw)
                self.dht11_failures = 0
                status = "CONNECTED: DHT11 on BCM GPIO17"
                self._sensor_diagnostic("ambient_humidity", raw[0] if raw else None,
                                        value, status, attempt=attempt)
                return {
                    "value": value, "unit": "%", "classification": None,
                    "status": status, "read_timestamp": timestamp_now(),
                    "read_error": None,
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._sensor_diagnostic("ambient_humidity", raw[0] if raw else None,
                                        None, "RETRYING" if attempt < 3 else "READ FAILED",
                                        last_error, attempt)
                if attempt < 3:
                    # The DHT library caches reads closer than two seconds.
                    time.sleep(2.0)
        self.error_counts["dht11_read"] += 1
        self.dht11_failures += 1
        if self.dht11_device is not None:
            try:
                self.dht11_device.exit()
            except Exception:
                log.exception("DHT11 cleanup failed before reconnection")
            finally:
                self.dht11_device = None
        status = ("RECOVERING" if self.dht11_failures <= self.sensor_recovery_limit else "ERROR") + f": {last_error}"
        self._sensor_diagnostic("ambient_humidity", None, None, status, last_error, 3)
        return {
            "value": None, "unit": "%", "classification": None,
            "status": status, "read_timestamp": timestamp_now(), "read_error": last_error,
        }

    def _safe_analog(self, channel):
'''),
    ("water and humidity acquisition", '''        try:
            water_value = read_ds18b20(self.ds18b20_device)
            water_temperature = {
                "value_C": water_value, "unit": "C",
                "classification": classify_water_temperature(water_value),
                "status": f"OK: {self.ds18b20_device.name}; no software offset",
            }
        except Exception as exc:
            self.error_counts["ds18b20_read"] += 1
            water_temperature = {
                "value_C": None, "unit": "C", "classification": "UNAVAILABLE",
                "status": f"ERROR: {type(exc).__name__}: {exc}",
            }

        try:
            if self.dht11_device is None:
                raise RuntimeError(self.dht11_setup_error or "DHT11 unavailable")
            humidity_value = read_dht11(self.dht11_device)
            ambient_humidity = {
                "value": humidity_value, "unit": "%", "classification": None,
                "status": "CONNECTED: DHT11 on BCM GPIO17",
            }
        except Exception as exc:
            self.error_counts["dht11_read"] += 1
            ambient_humidity = {
                "value": None, "unit": "%", "classification": None,
                "status": f"ERROR: {type(exc).__name__}: {exc}",
            }
''', '''        water_temperature = self._read_water_temperature()
        ambient_humidity = self._read_humidity()
'''),
    ("completed-sample timestamp", "        self._write_csv(payload)\n        return payload\n", "        payload[\"timestamp\"] = timestamp_now()\n        self._write_csv(payload)\n        return payload\n"),
    ("fail-closed acquisition", '''            except Exception as exc:
                self.error_counts["acquisition_cycle"] += 1
                with self.lock:
                    self.latest["timestamp"] = timestamp_now()
                    self.latest["system"]["overall_status"] = "ERROR"
                    self.latest["system"]["last_error"] = f"{type(exc).__name__}: {exc}"
''', '''            except Exception as exc:
                self.error_counts["acquisition_cycle"] += 1
                log.exception("Integrated sensor acquisition cycle failed")
                error = f"{type(exc).__name__}: {exc}"
                with self.lock:
                    failed = copy.deepcopy(self.latest)
                    failed["timestamp"] = timestamp_now()
                    for sensor in failed["sensors"].values():
                        for field in ("value", "value_C", "value_uScm", "value_mScm", "value_ntu"):
                            if field in sensor:
                                sensor[field] = None
                        sensor["classification"] = "UNAVAILABLE"
                        sensor["status"] = f"ERROR: acquisition cycle failed: {error}"
                        sensor["read_error"] = error
                        sensor["read_timestamp"] = failed["timestamp"]
                    failed["system"]["overall_status"] = "ERROR"
                    failed["system"]["last_error"] = error
                    failed["system"]["sample"] = self.sample_number
                    failed["system"]["error_counts"] = dict(self.error_counts)
                    self.latest = failed
'''),
]


UPGRADE_REPLACEMENTS = [
    ("recovery version marker", f"    {MARKER}\n", f"    {MARKER}\n    {UPGRADED_MARKER}\n"),
    ("recovery failure limit", "        self.dht11_failures = 0\n        self.last_valid_ph = None", "        self.dht11_failures = 0\n        self.sensor_recovery_limit = 5\n        self.last_valid_ph = None"),
    ("water temperature validation", "                value = read_ds18b20(self.ds18b20_device, raw)\n                self.ds18b20_failures = 0", "                value = read_ds18b20(self.ds18b20_device, raw)\n                if not 0 <= value <= 45:\n                    raise ValueError(f\"implausible water temperature: {value!r} C\")\n                self.ds18b20_failures = 0"),
    ("water recovery duration", "        status = (\"RECOVERING\" if self.ds18b20_failures == 1 else \"ERROR\") + f\": {last_error}\"", "        status = (\"RECOVERING\" if self.ds18b20_failures <= self.sensor_recovery_limit else \"ERROR\") + f\": {last_error}\""),
    ("humidity recovery duration", "        status = (\"RECOVERING\" if self.dht11_failures == 1 else \"ERROR\") + f\": {last_error}\"", "        status = (\"RECOVERING\" if self.dht11_failures <= self.sensor_recovery_limit else \"ERROR\") + f\": {last_error}\""),
]


V2_UPGRADE_REPLACEMENTS = [
    ("recovery version marker", f"    {UPGRADED_MARKER}\n", f"    {UPGRADED_MARKER}\n    {FINAL_MARKER}\n"),
    ("remove water temperature limit", "                if not 0 <= value <= 45:\n                    raise ValueError(f\"implausible water temperature: {value!r} C\")\n", ""),
]


def build_updated_source(source):
    if MARKER in source:
        raise ValueError("Sensor recovery patch already appears to be installed")
    for label, old, new in REPLACEMENTS:
        count = source.count(old)
        if count != 1:
            raise ValueError(f"{label}: expected one exact match, found {count}; no file changed")
        source = source.replace(old, new, 1)
    compile(source, str(TARGET), "exec")
    return source


def apply_replacements(source, replacements):
    for label, old, new in replacements:
        count = source.count(old)
        if count != 1:
            raise ValueError(f"{label}: expected one exact match, found {count}; no file changed")
        source = source.replace(old, new, 1)
    return source


def upgrade_installed_source(source):
    version = installed_patch_version(source)
    if version == 0:
        raise ValueError("Sensor recovery patch is not installed")
    if version == 3:
        raise ValueError("Sensor recovery v3 patch already appears to be installed")
    if version == 1:
        source = apply_replacements(source, UPGRADE_REPLACEMENTS)
    source = apply_replacements(source, V2_UPGRADE_REPLACEMENTS)
    compile(source, str(TARGET), "exec")
    return source


def validate_installed_source(source):
    """Validate an already-patched source without attempting a second patch."""
    if MARKER not in source:
        return False
    compile(source, str(TARGET), "exec")
    return True


def installed_patch_version(source):
    if FINAL_MARKER in source:
        return 3
    if UPGRADED_MARKER in source:
        return 2
    if MARKER in source:
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="validate exact Pi source without writing")
    action.add_argument("--apply", action="store_true", help="back up and atomically update Pi source")
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args()
    target = args.target.resolve(strict=True)
    original = target.read_text(encoding="utf-8")
    version = installed_patch_version(original)
    if version == 3:
        compile(original, str(target), "exec")
        action = "check" if args.check else "apply"
        print(f"Already installed: {target}; sensor recovery v3 is valid; no files changed ({action})")
        return
    if version in (1, 2):
        updated = upgrade_installed_source(original)
        operation = "upgrade"
    else:
        updated = build_updated_source(original)
        operation = "install"
    if args.check:
        count = len(UPGRADE_REPLACEMENTS) if operation == "upgrade" else len(REPLACEMENTS)
        print(f"Ready: {target}; {operation} with {count} guarded edits; syntax valid; no files changed")
        return
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    backup = target.with_name(f"{target.name}.before_sensor_recovery_{stamp}")
    if backup.exists():
        raise FileExistsError(f"Backup already exists: {backup}")
    shutil.copy2(target, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".sensor-recovery-",
                                         suffix=".py", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(f"Updated: {target} ({operation})")
    print(f"Recovery backup: {backup}")
    print("Service was NOT restarted. Verify the diff and choose a safe restart time.")


if __name__ == "__main__":
    main()
