"""A room over a thermostat whose sensors go quiet repeats its holding duty, as a room over a switch.

The duty is the share of time the device said it was heating while the room held its target. Blind,
the room writes the device's top in the on-phase and the frost protection in the off-phase, so the
device's own control follows the cycle.
"""

from __future__ import annotations

import unittest

from _core import at
from core import card
from core.defaults import STANDARD
from core.loop import Stage
from core.regulation import Regulation
from core.sensors import NO_READING, SensorReading, read
from core.setpoint import observe
from core.thermostat import Decision, RoomThermostat

THERMOSTAT = "climate.panel"
WARM_OUTSIDE = 25.0
TARGET = 20.0


class AThermostatThatSaysWhenItHeats:
    """Publishes `hvac_action`; heats while told to, from minute zero to `heats_for` of each hour."""

    def __init__(self, minimum: float = 2.0, heats_for: int = 30, says: bool = True) -> None:
        self.minimum = minimum
        self.heats_for = heats_for
        self.says = says
        self.setpoint = 10.0
        self.minute = 0

    def publishes(self) -> tuple[str, dict[str, object]]:
        heating = self.minute % 60 < self.heats_for
        published: dict[str, object] = {
            "min_temp": self.minimum,
            "max_temp": 30,
            "target_temp_step": 0.5,
            "current_temperature": TARGET,
            "temperature": self.setpoint,
        }
        if self.says:
            published["hvac_action"] = "heating" if heating else "idle"
        return "heat", published

    def take(self, decision: Decision) -> None:
        for command in decision.commands:
            if command.closed and command.setpoint is not None:
                self.setpoint = command.setpoint


def a_pass(
    room: RoomThermostat, device: AThermostatThatSaysWhenItHeats, minute: int, reading: float | None
) -> Decision:
    device.minute = minute
    when = at(minutes=minute)
    seen = NO_READING if reading is None else read(
        [SensorReading("sensor.room", reading, when, when)], when
    )
    decision = room.evaluate(when, seen, WARM_OUTSIDE, relays={THERMOSTAT: observe(*device.publishes())})
    device.take(decision)
    return decision


def a_room_that_held_its_target(
    device: AThermostatThatSaysWhenItHeats, reading: float = TARGET
) -> RoomThermostat:
    """One hour at `reading`, the device heating for `heats_for` minutes of it."""
    room = RoomThermostat("stue", [THERMOSTAT])
    room.set_target(TARGET, at())
    for minute in range(61):
        a_pass(room, device, minute, reading)
    return room


def blind_for(
    room: RoomThermostat, device: AThermostatThatSaysWhenItHeats, start: int, minutes: int
) -> list[Decision]:
    return [a_pass(room, device, minute, None) for minute in range(start, start + minutes)]


def share_on(decisions: list[Decision]) -> float:
    return sum(decision.heating for decision in decisions) / len(decisions)


class TheRememberedDutyTests(unittest.TestCase):
    def test_a_room_that_loses_its_reading_keeps_the_duty_it_held(self) -> None:
        device = AThermostatThatSaysWhenItHeats(heats_for=30)
        room = a_room_that_held_its_target(device)

        blind = blind_for(room, device, 61, 3 * 60)

        self.assertTrue(all(d.stage is Stage.REPEATING_THE_HOLDING_DUTY for d in blind))
        self.assertAlmostEqual(blind[-1].duty, 0.5)
        # Twelve cycles of fifteen minutes, half of each with the device given its top.
        self.assertAlmostEqual(share_on(blind), 0.5, delta=0.05)
        self.assertEqual(
            {device_setpoint(d) for d in blind if d.heating} - {None}, {30.0}
        )
        self.assertEqual(card.attributes(
            "room_001", "stue", "0.1.0", 1, room, blind[-1], room.reading, WARM_OUTSIDE, False
        )["stage"], "repeating_the_holding_duty")

    def test_a_remembered_duty_stays_inside_the_band_a_relay_can_deliver(self) -> None:
        device = AThermostatThatSaysWhenItHeats(heats_for=58)
        room = a_room_that_held_its_target(device)

        blind = blind_for(room, device, 61, 60)

        regulation = Regulation()
        self.assertLessEqual(blind[-1].delivered, regulation.deliverable_ceiling)
        self.assertLess(share_on(blind), 0.7)

    def test_the_off_phase_never_goes_below_the_frost_protection(self) -> None:
        device = AThermostatThatSaysWhenItHeats(minimum=2.0, heats_for=30)
        room = a_room_that_held_its_target(device)

        written = [device_setpoint(d) for d in blind_for(room, device, 61, 60)]

        self.assertEqual(min(s for s in written if s is not None), STANDARD.frost_protection)

    def test_only_a_share_measured_holding_the_target_is_remembered(self) -> None:
        # Flat out; far below the target, as the relay's full-output stage; a device that never says.
        for device, reading in (
            (AThermostatThatSaysWhenItHeats(heats_for=60), TARGET),
            (AThermostatThatSaysWhenItHeats(heats_for=30), TARGET - 2.0),
            (AThermostatThatSaysWhenItHeats(heats_for=30, says=False), TARGET),
        ):
            room = a_room_that_held_its_target(device, reading)

            blind = blind_for(room, device, 61, 1)

            self.assertAlmostEqual(blind[0].duty, STANDARD.blind_last_resort_fraction)


class TheRoomsFrostTemperatureTests(unittest.TestCase):
    """The off-phase writes the frost temperature the add-on sent, not the house default."""

    def off_phase(self, minimum: float = 2.0, **regulation: object) -> float:
        device = AThermostatThatSaysWhenItHeats(minimum=minimum, heats_for=30)
        room = a_room_that_held_its_target(device)
        room.set_regulation(**regulation)
        written = [device_setpoint(d) for d in blind_for(room, device, 61, 60)]
        return min(s for s in written if s is not None)

    def test_the_room_s_own_frost_temperature_is_what_the_off_phase_writes(self) -> None:
        self.assertEqual(self.off_phase(frost_temperature=8.0), 8.0)

    def test_no_frost_limit_writes_the_device_s_own_minimum(self) -> None:
        self.assertEqual(self.off_phase(minimum=3.0, frost_temperature=8.0, frost_limit="off"), 3.0)

    def test_a_frost_temperature_below_the_device_s_minimum_writes_that_minimum(self) -> None:
        self.assertEqual(self.off_phase(minimum=7.0, frost_temperature=-10.0), 7.0)

    def test_the_frost_temperature_survives_a_restart(self) -> None:
        room = RoomThermostat("stue", [THERMOSTAT])
        room.set_regulation(frost_temperature=-4.0, frost_limit="off")

        back = Regulation.from_dict(room.regulation.as_dict())

        self.assertEqual((back.frost_temperature, back.frost_limit), (-4.0, False))


class HowLongTheDutyIsKeptTests(unittest.TestCase):
    def test_past_the_longest_blind_spell_it_falls_to_the_last_resort_a_switch_room_runs(self) -> None:
        device = AThermostatThatSaysWhenItHeats(heats_for=30)
        room = a_room_that_held_its_target(device)
        switch_room = RoomThermostat("kjokken", ["switch.panel"])
        switch_room.set_target(TARGET, at())

        a_pass(room, device, 61, None)
        hours = int(STANDARD.longest_blind_spell.total_seconds() // 60)
        inside = a_pass(room, device, 61 + hours - 60, None)
        past = a_pass(room, device, 61 + hours + 1, None)
        switch_past = switch_room.evaluate(at(minutes=61 + hours + 1), NO_READING, WARM_OUTSIDE)

        self.assertAlmostEqual(inside.duty, 0.5)
        self.assertAlmostEqual(past.duty, STANDARD.blind_last_resort_fraction)
        self.assertAlmostEqual(past.duty, switch_past.duty)
        self.assertAlmostEqual(past.delivered, switch_past.delivered)

    def test_the_room_holds_a_setpoint_again_once_its_reading_returns(self) -> None:
        device = AThermostatThatSaysWhenItHeats(heats_for=30)
        room = a_room_that_held_its_target(device)
        blind_for(room, device, 61, 20)

        back = a_pass(room, device, 81, 19.0)

        self.assertIs(back.stage, Stage.HOLDING_A_SETPOINT)
        # The target, shifted by the device reading one degree warmer than the room.
        self.assertEqual(device_setpoint(back), 21.0)
        self.assertFalse(back.has_a_duty)


def device_setpoint(decision: Decision) -> float | None:
    return next((c.setpoint for c in decision.commands if c.closed), None)


if __name__ == "__main__":
    unittest.main()
