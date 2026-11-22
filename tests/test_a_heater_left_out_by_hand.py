"""What the room page leaves out stays out of the thermostat, across a restart and a fresh discovery.

The climate entity composes these same calls; driving it needs a running core, which is not here.
"""

from __future__ import annotations

import json
import unittest

from _core import at
from core.rooms import Candidate, named_or_discovered, rooms
from core.thermostat import RoomThermostat

HEAT = "heat"


def found_in_the_living_room():
    return rooms(
        {"stue": []},
        [
            Candidate("switch.panel", "stue", frozenset({HEAT}), "shelly", device_id="panel"),
            Candidate("switch.oven", "stue", frozenset({HEAT}), "shelly", device_id="oven"),
            Candidate(
                "sensor.stue", "stue", frozenset({HEAT}), "zha", device_id="a",
                device_class="temperature",
            ),
            Candidate(
                "sensor.window_sill", "stue", frozenset({HEAT}), "zha", device_id="b",
                device_class="temperature",
            ),
        ],
        "adaptive_heating",
        HEAT,
        "adaptive_exclude",
    )["stue"]


def after_a_cut(before: RoomThermostat) -> RoomThermostat:
    written = json.loads(json.dumps(before.as_dict()))
    after = RoomThermostat(before.room_id, ["switch.panel", "switch.oven"])
    after.restore(written, at())
    return after


class LeftOutByHandTests(unittest.TestCase):
    def test_a_heater_and_a_sensor_left_out_stay_out_after_a_restart_and_a_new_discovery(self) -> None:
        thermostat = RoomThermostat("room_001", ["switch.panel", "switch.oven"])
        thermostat.set_regulation(left_out=["switch.oven", "sensor.window_sill"])

        regulation = after_a_cut(thermostat).regulation
        room = found_in_the_living_room()

        self.assertEqual(
            named_or_discovered(regulation.heaters, room.heaters, regulation.left_out),
            ["switch.panel"],
        )
        self.assertEqual(
            named_or_discovered(
                regulation.temperature_sensors, room.temperature_sensors, regulation.left_out
            ),
            ["sensor.stue"],
        )

    def test_a_call_naming_the_room_s_slots_clears_the_power_sensor_it_omits(self) -> None:
        thermostat = RoomThermostat("room_001", ["switch.panel"])
        thermostat.set_regulation(power_sensor="sensor.panel_power", heaters=["switch.panel"], left_out=[])

        thermostat.set_regulation(left_out=[], temperature_sensors=[])

        self.assertIsNone(thermostat.regulation.power_sensor)
        self.assertIsNone(thermostat.regulation.heaters)
        self.assertEqual(thermostat.regulation.temperature_sensors, ())


if __name__ == "__main__":
    unittest.main()
