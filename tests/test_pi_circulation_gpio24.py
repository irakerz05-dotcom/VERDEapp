"""Verify the supervised circulation probe restores GPIO24 after a failure."""

import unittest
from unittest.mock import patch

from deploy import verify_pi_circulation_gpio24 as diagnostic


class CirculationProbeTests(unittest.TestCase):
    def test_gpio24_restored_after_observation_failure(self):
        commands = []
        state = {"mode": "no", "level": None}

        def pinctrl(_binary, *args):
            commands.append(args)
            if args[:2] == ("set", "24"):
                state["mode"] = args[2]
                state["level"] = args[3]
            return ""

        def pin_state(_binary):
            if state["mode"] == "no":
                return "24: no    pd | -- // GPIO24 = none"
            return f"24: op {state['level']} pd | lo // GPIO24 = output"

        with (patch.object(diagnostic, "pinctrl", side_effect=pinctrl),
              patch.object(diagnostic, "pin_state", side_effect=pin_state),
              patch.object(diagnostic.time, "sleep", side_effect=RuntimeError("interrupted"))):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                diagnostic.test_level("pinctrl", "dl", 5)

        self.assertEqual(commands[-1], ("set", "24", "no", "pd"))
        self.assertEqual(state["mode"], "no")


if __name__ == "__main__":
    unittest.main()
