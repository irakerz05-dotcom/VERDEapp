#!/usr/bin/env python3
"""Measure A1 and A2 with GPIO25 in each relay state, then restore VERDE.

Run --check first with the backend virtualenv Python. --run needs sudo. This
tool does not edit calibration, backend code, or recorded sensor history.
"""

import argparse
import subprocess
import time
from pathlib import Path


SOURCE = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
SERVICE = "verde.service"


def preflight():
    source = SOURCE.read_text(encoding="utf-8")
    anchors = (
        "EC_RELAY_BCM_PIN = 25",
        "EC_RELAY_ACTIVE_HIGH = False",
        'AnalogIn(self.ads, ADS.P1)',
        'AnalogIn(self.ads, ADS.P2)',
        "self.ec_relay.on()\n            time.sleep(PH_SETTLE_SECONDS)",
        "if not self._relay_off():",
    )
    missing = [anchor for anchor in anchors if anchor not in source]
    if missing:
        raise ValueError(f"Installed sensor service differs from reviewed relay code: {missing}")
    import board  # noqa: F401
    import busio  # noqa: F401
    import adafruit_ads1x15.ads1115  # noqa: F401
    from adafruit_ads1x15.analog_in import AnalogIn  # noqa: F401
    from gpiozero import OutputDevice  # noqa: F401
    print("Ready: A1/A2, active-low GPIO25, and backend Python imports verified")


def voltages(ph, ec):
    # Read each channel twice after ADS1115 multiplexer switching; use the
    # second conversion to avoid carrying a preceding channel into the result.
    _ = ph.voltage
    ph_v = ph.voltage
    _ = ec.voltage
    ec_v = ec.voltage
    return ph_v, ec_v


def sample(label, relay, ph, ec, seconds, interval=4):
    deadline = time.monotonic() + seconds
    start = time.monotonic()
    while True:
        ph_v, ec_v = voltages(ph, ec)
        gpio_level = "LOW" if relay.is_active else "HIGH"
        print(f"{label} t={time.monotonic()-start:.1f}s GPIO25={gpio_level} "
              f"A1_pH={ph_v:.6f}V A2_EC={ec_v:.6f}V", flush=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))


def run_diagnostic(recovery_seconds):
    from gpiozero import OutputDevice
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn

    relay = None
    i2c = None
    was_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE], check=False
    ).returncode == 0
    if not was_active:
        raise RuntimeError("VERDE service is not active; diagnostic did not change it")
    # Keep Python in the verde user's environment, where Blinka is installed.
    # Authenticate sudo before the service is stopped so cleanup can restart it.
    subprocess.run(["sudo", "-v"], check=True)
    print("Stopping verde.service for an exclusive, read-only ADC check", flush=True)
    subprocess.run(["sudo", "systemctl", "stop", SERVICE], check=True)
    try:
        relay = OutputDevice(25, active_high=False, initial_value=False)
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c, address=0x48)
        ads.gain = 1
        ph, ec = AnalogIn(ads, ADS.P1), AnalogIn(ads, ADS.P2)

        # off() is physical GPIO HIGH; on() is physical GPIO LOW. The EC
        # board's actual power state is deliberately inferred from A2 below.
        relay.off()
        sample("relay.off", relay, ph, ec, 8)
        relay.on()
        sample("relay.on", relay, ph, ec, recovery_seconds)
        relay.off()
        sample("relay.off_again", relay, ph, ec, 8)
    finally:
        try:
            if relay is not None:
                try:
                    relay.off()  # Restore the service's existing idle GPIO level.
                finally:
                    relay.close()
            if i2c is not None:
                i2c.deinit()
        finally:
            print("Starting verde.service", flush=True)
            subprocess.run(["sudo", "systemctl", "start", SERVICE], check=True)
            subprocess.run(["systemctl", "is-active", SERVICE], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--recovery-seconds", type=int, default=32)
    args = parser.parse_args()
    if not 16 <= args.recovery_seconds <= 180:
        parser.error("--recovery-seconds must be between 16 and 180")
    preflight()
    if args.run:
        run_diagnostic(args.recovery_seconds)


if __name__ == "__main__":
    main()
