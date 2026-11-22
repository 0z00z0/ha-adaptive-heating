"""A Slow room's guards, each of which stands between the model and a cold room or a hot floor."""

from __future__ import annotations

import unittest
from datetime import timedelta

from _core import at
from core.loop import Stage, duty_for
from core.reasons import NotHeating
from core.regulation import Regulation
from core.sensors import NO_READING, SensorReading, read
from core.thermostat import RoomThermostat


def reading(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.air", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


def a_slow_room(learnt: bool = True, floor: bool = False) -> RoomThermostat:
    room = RoomThermostat("room_001", ["switch.cables"])
    fields: dict[str, object] = {"room_type": "slow"}
    if learnt:
        fields.update(
            slow_model="learnt",
            dead_time=timedelta(hours=3),
            lag=timedelta(hours=6),
            full_output_rise=33.0,
        )
    if floor:
        fields.update(floor_sensor="sensor.floor", floor_limit=28.0, floor_rise_per_degree=0.2)
    room.set_regulation(**fields)
    return room


class ASlowRoomTests(unittest.TestCase):
    def test_before_its_figures_are_learnt_it_switches_on_the_widest_band(self) -> None:
        room = a_slow_room(learnt=False)
        room.set_target(20.0, at())
        inside = room.evaluate(at(), reading(19.6), 0.0)
        self.assertIs(inside.stage, Stage.BAND)
        self.assertFalse(inside.heating)
        below = room.evaluate(at(minutes=1), reading(19.5, 1), 0.0)
        self.assertTrue(below.heating)

    def test_without_its_air_reading_it_heats_at_the_share_the_outdoor_temperature_needs(self) -> None:
        room = a_slow_room()
        room.set_target(15.0, at())
        blind = room.evaluate(at(), NO_READING, -10.0)
        self.assertIs(blind.stage, Stage.FEED_FORWARD)
        # (15 - -10) / 33: never the remembered share and never a third.
        self.assertAlmostEqual(blind.duty, 25.0 / 33.0)

    def test_a_learnt_room_s_stuck_window_stretches_to_its_response_time(self) -> None:
        def flat_for(hours: float) -> list[SensorReading]:
            return [SensorReading("sensor.air", 12.0, at(hours=hours), at())]

        learnt = a_slow_room().regulation.sensor_rules
        self.assertIsNone(read(flat_for(8), at(hours=8), Regulation()).temperature)
        self.assertEqual(read(flat_for(8), at(hours=8), learnt).temperature, 12.0)
        # Dead time three hours and lag six: flat for longer than nine is still stuck.
        self.assertIsNone(read(flat_for(10), at(hours=10), learnt).temperature)

    def test_the_floor_asked_for_never_passes_the_floor_limit(self) -> None:
        room = a_slow_room(floor=True)
        room.set_target(21.0, at())
        cold = room.evaluate(at(), reading(10.0), 0.0, floor=27.4)
        self.assertAlmostEqual(cold.duty, duty_for(27.4, 28.0, 0.0, room.regulation)[0])
        self.assertLess(cold.duty, 1.0)

    def test_the_floor_at_its_limit_opens_the_relay_whatever_the_air_needs(self) -> None:
        room = a_slow_room(floor=True)
        room.set_target(21.0, at())
        cut = room.evaluate(at(), reading(10.0), 0.0, floor=27.5)
        self.assertFalse(cut.heating)
        self.assertIs(cut.reason, NotHeating.FLOOR_AT_ITS_LIMIT)

    def test_with_its_floor_sensor_lost_it_holds_no_more_than_the_floor_can_stand(self) -> None:
        room = a_slow_room(floor=True)
        room.set_target(21.0, at())
        lost = room.evaluate(at(), reading(10.0), 0.0, floor=None)
        # Settled floor = outdoor + share x 33 x (1 + 0.2), held under 28 - 0.5.
        self.assertAlmostEqual(lost.duty, 27.5 / (33.0 * 1.2))
        self.assertTrue(lost.reports_a_problem)


if __name__ == "__main__":
    unittest.main()
