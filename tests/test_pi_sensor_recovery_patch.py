"""Offline guard tests for the Pi-only source updater."""
import unittest
import copy
import threading
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from deploy.apply_pi_sensor_recovery import MARKER, REPLACEMENTS, build_updated_source


class PiSensorRecoveryPatchTests(unittest.TestCase):
    @staticmethod
    def _reader(water_values, humidity_values):
        methods = next(new for label, _, new in REPLACEMENTS if label == "retry methods")
        diagnostics = []
        sleeps = []
        device = SimpleNamespace(name="28-00000048b3b1")
        device.exit = lambda: None
        water = iter(water_values)
        humidity = iter(humidity_values)

        def read_water(_device, raw):
            result = next(water)
            raw.append("crc=YES t=25000")
            if isinstance(result, Exception):
                raise result
            return result

        def read_humidity(_device, raw):
            result = next(humidity)
            raw.append(result if not isinstance(result, Exception) else None)
            if isinstance(result, Exception):
                raise result
            return result

        namespace = {
            "log": SimpleNamespace(info=lambda *args: diagnostics.append(args), exception=lambda *args: None),
            "timestamp_now": lambda: "2026-10-25T22:00:00+08:00",
            "discover_ds18b20": lambda: device,
            "read_ds18b20": read_water,
            "classify_water_temperature": lambda value: "OPTIMAL",
            "open_dht11": lambda: device,
            "read_dht11": read_humidity,
            "time": SimpleNamespace(sleep=lambda seconds: sleeps.append(seconds)),
        }
        exec("class Reader:\n" + methods + "        pass\n", namespace)
        reader = namespace["Reader"]()
        reader.error_counts = Counter()
        reader.ds18b20_failures = 0
        reader.dht11_failures = 0
        reader.dht11_device = None
        reader.dht11_setup_error = None
        return reader, diagnostics, sleeps

    def test_every_expected_old_block_is_replaced_once(self):
        fixture = "\n\n".join(old for _, old, _ in REPLACEMENTS)
        with patch("builtins.compile"):
            updated = build_updated_source(fixture)
        self.assertIn(MARKER, updated)
        for _, old, new in REPLACEMENTS:
            self.assertIn(new, updated)

    def test_unknown_or_partial_pi_source_is_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "logging import"):
            build_updated_source("unrelated source")
        with self.assertRaisesRegex(ValueError, "already appears"):
            build_updated_source(MARKER)

    def test_inserted_methods_and_exception_handler_are_valid_python(self):
        methods = next(new for label, _, new in REPLACEMENTS if label == "retry methods")
        compile("class Reader:\n" + methods + "        pass\n", "<retry methods>", "exec")
        handler = next(new for label, _, new in REPLACEMENTS if label == "fail-closed acquisition")
        compile("class Reader:\n    def run(self):\n        while True:\n            try:\n                pass\n" + handler,
                "<cycle handler>", "exec")

    def test_live_pi_retry_methods_recover_independently_and_never_reuse_values(self):
        reader, diagnostics, sleeps = self._reader(
            [ValueError("CRC"), 25.0, ValueError("CRC"), ValueError("CRC"),
             ValueError("CRC"), ValueError("CRC"), 25.5],
            [RuntimeError("full buffer")] * 3 + [72.0] + [RuntimeError("full buffer")] * 6 + [73.0],
        )
        water = reader._read_water_temperature()
        self.assertEqual((water["value_C"], water["status"]), (25.0, "OK: 28-00000048b3b1; no software offset"))
        self.assertEqual(reader.error_counts["ds18b20_read"], 0)
        humidity = reader._read_humidity()
        self.assertIsNone(humidity["value"])
        self.assertTrue(humidity["status"].startswith("RECOVERING"))
        self.assertEqual(reader.error_counts["dht11_read"], 1)
        self.assertEqual(reader._read_humidity()["value"], 72.0)

        self.assertTrue(reader._read_water_temperature()["status"].startswith("RECOVERING"))
        self.assertTrue(reader._read_water_temperature()["status"].startswith("ERROR"))
        self.assertEqual(reader._read_water_temperature()["value_C"], 25.5)
        self.assertEqual(reader.ds18b20_failures, 0)

        self.assertTrue(reader._read_humidity()["status"].startswith("RECOVERING"))
        self.assertTrue(reader._read_humidity()["status"].startswith("ERROR"))
        self.assertEqual(reader._read_humidity()["value"], 73.0)
        self.assertEqual(reader.dht11_failures, 0)
        self.assertIn(2.0, sleeps)
        self.assertIn(0.25, sleeps)
        self.assertTrue(any("sensor_read name=%s" in call[0] for call in diagnostics))

    def test_cycle_exception_clears_all_cached_numeric_values(self):
        handler = next(new for label, _, new in REPLACEMENTS if label == "fail-closed acquisition")
        namespace = {
            "copy": copy,
            "timestamp_now": lambda: "2026-10-25T22:00:00+08:00",
            "log": SimpleNamespace(exception=lambda *args: None),
        }
        exec("class Reader:\n    def run_once(self):\n        while True:\n"
             "            try:\n                raise RuntimeError('test-only cycle failure')\n"
             + handler + "            break\n", namespace)
        reader = namespace["Reader"]()
        reader.lock = threading.RLock()
        reader.error_counts = Counter()
        reader.sample_number = 9
        reader.latest = {
            "timestamp": "older",
            "sensors": {
                "water_temperature": {"value_C": 25.0, "status": "OK"},
                "ambient_humidity": {"value": 72.0, "status": "CONNECTED"},
                "ec": {"value_mScm": 1.2, "status": "OK"},
            },
            "system": {"overall_status": "OK", "sample": 8},
        }
        reader.run_once()
        self.assertEqual(reader.latest["system"]["overall_status"], "ERROR")
        self.assertEqual(reader.latest["system"]["sample"], 9)
        for sensor in reader.latest["sensors"].values():
            self.assertTrue(sensor["status"].startswith("ERROR"))
            self.assertIsNotNone(sensor["read_error"])
            for key in ("value", "value_C", "value_mScm"):
                if key in sensor:
                    self.assertIsNone(sensor[key])


if __name__ == "__main__":
    unittest.main()
