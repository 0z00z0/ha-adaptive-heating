"""What `set_regulation` carries, and what each field changes once it lands.

The four sensor settings replace the standing figures a room judges its own sensors by. The six
entity fields replace what the registries found. The settings survive a restart and the entity
fields deliberately do not.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from _core import at
from core.reasons import NotHeating, Refused
from core.regulation import Regulation
from core.sensors import SensorExclusion, SensorReading, read
from core.setup import heater_already_claimed
from core.thermostat import RoomThermostat


def sensor(name: str, temperature: float, reported: float = 0.0, moved: float = 0.0):
    return SensorReading(name, temperature, at(minutes=reported), at(minutes=moved))


class TheFourSensorSettingsTests(unittest.TestCase):
    def test_a_shorter_freshness_leaves_a_sensor_out_that_the_standing_figure_keeps(self) -> None:
        readings = [sensor("sensor.stue", 20.0, reported=-30, moved=-30)]

        self.assertEqual(read(readings, at()).temperature, 20.0)
        sent = Regulation(sensor_freshness=timedelta(minutes=10))
        self.assertIsNone(read(readings, at(), sent).temperature)

    def test_a_wider_spread_keeps_a_disagreeing_pair_the_standing_figure_throws_out(self) -> None:
        readings = [
            sensor("sensor.a", 18.0, reported=-1, moved=-1),
            sensor("sensor.b", 21.0, reported=-1, moved=-1),
        ]
        standing = read(readings, at())

        self.assertIsNone(standing.temperature)
        self.assertEqual(
            {verdict.excluded for verdict in standing.verdicts},
            {SensorExclusion.BOTH_OF_A_DISAGREEING_PAIR},
        )

        sent = read(readings, at(), Regulation(sensor_spread=4.0))
        self.assertEqual(sent.temperature, 19.5)

    def test_a_shorter_stuck_window_leaves_a_flat_reading_out(self) -> None:
        readings = [
            sensor("sensor.flat", 19.0, reported=-1, moved=-120),
            sensor("sensor.live", 20.0, reported=-1, moved=-5),
        ]

        self.assertEqual(read(readings, at()).resting_on, 2)
        sent = Regulation(stuck_reading=timedelta(hours=1))
        self.assertEqual(read(readings, at(), sent).temperature, 20.0)

    def test_the_four_settings_survive_a_restart_and_a_named_slot_does_not(self) -> None:
        """A restart drives what it discovers until the add-on names a slot again."""
        room = RoomThermostat("stue", ["switch.stue"])
        room.set_regulation(
            sensor_freshness=timedelta(minutes=20),
            stuck_reading=timedelta(hours=2),
            sensor_spread=3.0,
            freshness_record_retention=timedelta(days=2),
            heaters=["switch.loft"],
            window_sensor="binary_sensor.stue_vindu",
        )

        after = RoomThermostat("stue", ["switch.stue"])
        after.restore(room.as_dict(), at())

        self.assertEqual(after.regulation.sensor_freshness, timedelta(minutes=20))
        self.assertEqual(after.regulation.stuck_reading, timedelta(hours=2))
        self.assertEqual(after.regulation.sensor_spread, 3.0)
        self.assertEqual(after.regulation.freshness_record_retention, timedelta(days=2))
        self.assertIsNone(after.regulation.heaters)
        self.assertIsNone(after.regulation.window_sensor)


class TheSixEntityFieldsTests(unittest.TestCase):
    def test_each_field_lands_on_the_regulation_the_room_then_reads(self) -> None:
        room = RoomThermostat("stue", ["switch.stue"])
        room.set_regulation(
            window_sensor="binary_sensor.stue_vindu",
            power_sensor="sensor.stue_effekt",
            neighbour="bad",
            heaters=["switch.loft"],
            temperature_sensors=["sensor.loft"],
            outdoor_sensor="sensor.ute",
        )

        self.assertEqual(room.regulation.window_sensor, "binary_sensor.stue_vindu")
        self.assertEqual(room.regulation.power_sensor, "sensor.stue_effekt")
        self.assertEqual(room.regulation.neighbour, "bad")
        self.assertEqual(room.regulation.heaters, ("switch.loft",))
        self.assertEqual(room.regulation.temperature_sensors, ("sensor.loft",))
        self.assertEqual(room.regulation.outdoor_sensor, "sensor.ute")

    def test_naming_one_unlabelled_heater_makes_the_room_drive_that_heater_alone(self) -> None:
        room = RoomThermostat("stue", ["switch.stue", "switch.oven"])
        room.set_target(20.0, at())
        room.set_regulation(heaters=["switch.loft"])
        room.drive(list(room.regulation.heaters or ()))

        self.assertEqual([loop.heater_id for loop in room.loops], ["switch.loft"])
        decision = room.evaluate(at(), read([sensor("sensor.stue", 15.0)], at()))
        self.assertEqual({command.heater_id for command in decision.commands}, {"switch.loft"})

    def test_a_heater_that_stays_keeps_its_loop_rather_than_starting_a_fresh_cycle(self) -> None:
        """A rebuilt loop hands the relay guard a clean slate, which defeats it."""
        room = RoomThermostat("stue", ["switch.stue", "switch.oven"])
        standing = room.loops[0]
        room.drive(["switch.stue", "switch.loft"])

        self.assertIs(room.loops[0], standing)


class AHeaterBelongsToOneRoomTests(unittest.TestCase):
    def test_a_heater_named_in_two_rooms_named_sets_is_refused(self) -> None:
        """Two loops over one relay send 384 commands a day against 192, each counting only its own."""
        claimed = heater_already_claimed(["switch.panel"], {"bad": ["switch.panel"]})

        self.assertEqual(claimed, ("switch.panel", "bad"))
        refusal = Refused(NotHeating.THE_HEATER_BELONGS_TO_ANOTHER_ROOM)
        self.assertEqual(refusal.reason, NotHeating.THE_HEATER_BELONGS_TO_ANOTHER_ROOM)
        self.assertIn("another room", str(refusal).lower())


if __name__ == "__main__":
    unittest.main()
