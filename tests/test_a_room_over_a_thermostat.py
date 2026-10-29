"""A room whose heater is a thermostat: given a number every pass, on the card a switch room has."""

from __future__ import annotations

import unittest
from datetime import datetime

from _core import at
from core import card
from core.reasons import NotHeating
from core.sensors import NO_READING, SensorReading, read
from core.setpoint import observe
from core.thermostat import Decision, RoomThermostat

THERMOSTAT = "climate.panel"
SWITCH = "switch.panel"
# Above every target used here, so the outdoor term is nothing and each number is the shift alone.
WARM_OUTSIDE = 25.0


class AHeatOnlyThermostat:
    """What a heat-only thermostat publishes, as measured on a real one, and nothing more.

    After a power cut it comes back on its lowest preset: the case the write every pass is for.
    """

    def __init__(self, reading: float | None = 22.0) -> None:
        self.state = "heat"
        self.setpoint = 10.0
        self.reading = reading

    def publishes(self) -> tuple[str, dict[str, object]]:
        if self.state == "unavailable":
            return self.state, {}
        return self.state, {
            "hvac_modes": ["off", "heat"],
            "min_temp": 10,
            "max_temp": 30,
            "target_temp_step": 0.5,
            "current_temperature": self.reading,
            "temperature": self.setpoint,
        }

    def take(self, decision: Decision) -> None:
        for command in decision.commands:
            if command.heater_id != THERMOSTAT:
                continue
            self.state = "heat" if command.closed else "off"
            if command.setpoint is not None:
                self.setpoint = command.setpoint

    def power_cut(self) -> None:
        self.setpoint = 10.0


def a_reading(temperature: float, when: datetime):
    return read([SensorReading("sensor.room", temperature, when, when)], when)


def a_room(heater: str, target: float = 20.0) -> RoomThermostat:
    room = RoomThermostat("stue", [heater])
    room.set_target(target, at())
    return room


def a_pass(
    room: RoomThermostat, device: AHeatOnlyThermostat, when: datetime, temperature: float | None
) -> Decision:
    reading = NO_READING if temperature is None else a_reading(temperature, when)
    decision = room.evaluate(
        when, reading, WARM_OUTSIDE, relays={THERMOSTAT: observe(*device.publishes())}
    )
    device.take(decision)
    return decision


def written(decision: Decision) -> float | None:
    setpoints = [c.setpoint for c in decision.commands if c.heater_id == THERMOSTAT and c.closed]
    return setpoints[0] if setpoints else None


def the_card(room: RoomThermostat, decision: Decision) -> dict[str, object]:
    return card.attributes("room_001", "stue", "0.1.0", 1, room, decision, room.reading, WARM_OUTSIDE, False)


class TheTwoKindsOfRoomLookTheSameTests(unittest.TestCase):
    def test_every_attribute_name_and_every_reason_is_the_same_for_both(self) -> None:
        # Below the target, at it, with no reading, and switched off: one fresh pair each.
        situations = ((18.0, False), (21.0, False), (None, False), (18.0, True))
        for temperature, switched_off in situations:
            over_a_switch = a_room(SWITCH)
            over_a_thermostat = a_room(THERMOSTAT)
            if switched_off:
                over_a_switch.switch_off(at())
                over_a_thermostat.switch_off(at())
            reading = NO_READING if temperature is None else a_reading(temperature, at())

            switch_decision = over_a_switch.evaluate(at(), reading, WARM_OUTSIDE)
            switch_card = the_card(over_a_switch, switch_decision)
            device = AHeatOnlyThermostat()
            thermostat_decision = a_pass(over_a_thermostat, device, at(), temperature)
            thermostat_card = the_card(over_a_thermostat, thermostat_decision)

            self.assertEqual(list(switch_card), list(thermostat_card))
            # A blind switch room may be in its on-phase, so only a room with a reading compares.
            if temperature is not None:
                self.assertIs(switch_decision.reason, thermostat_decision.reason)
            # The relay's own figures have a defined value and no meaning here, until both kinds
            # run the same fallback blind.
            if temperature is None and not switched_off:
                self.assertEqual(thermostat_card["duty"], switch_card["duty"])
                self.assertEqual(thermostat_card["duty_asked_for"], switch_card["duty_asked_for"])
            else:
                self.assertIsNone(thermostat_card["duty"])
                self.assertIsNone(thermostat_card["duty_asked_for"])
            self.assertIs(thermostat_card["relay_guard_is_holding"], False)

    def test_nothing_the_thermostat_underneath_offers_reaches_the_card(self) -> None:
        device = AHeatOnlyThermostat()
        over_a_thermostat = a_room(THERMOSTAT)
        decision = a_pass(over_a_thermostat, device, at(), 18.0)
        thermostat_card = the_card(over_a_thermostat, decision)

        self.assertFalse(set(device.publishes()[1]) & set(thermostat_card))
        # The room's own range and controls, never the device's ten to thirty.
        self.assertEqual(card.offered(over_a_thermostat), card.offered(a_room(SWITCH)))
        self.assertEqual(
            card.offered(over_a_thermostat),
            card.Offered(
                ("heat", "off"),
                ("TARGET_TEMPERATURE", "PRESET_MODE", "TURN_ON", "TURN_OFF"),
                2.0,
                30.0,
                0.5,
            ),
        )

    def test_a_thermostat_that_does_not_answer_is_the_one_extra_reason(self) -> None:
        device = AHeatOnlyThermostat()
        room = a_room(THERMOSTAT)
        a_pass(room, device, at(), 18.0)

        device.state = "unavailable"
        gone = a_pass(room, device, at(minutes=1), 18.0)
        self.assertEqual(gone.commands, ())
        self.assertIs(gone.reason, NotHeating.THE_HEATER_IS_NOT_ANSWERING)
        # The reason is the room's own enum sensor now, and the card carries none of it.
        self.assertNotIn("not_heating_because", the_card(room, gone))
        self.assertTrue(gone.reports_a_problem)

        device.state = "off"
        back = a_pass(room, device, at(minutes=2), 18.0)
        self.assertEqual(written(back), 24.0)
        self.assertEqual(device.state, "heat")


class TheNumberWrittenTests(unittest.TestCase):
    def test_a_thermostat_reading_4_degrees_warm_is_given_4_degrees_more(self) -> None:
        device = AHeatOnlyThermostat(reading=22.0)
        decision = a_pass(a_room(THERMOSTAT, 20.0), device, at(), 18.0)
        self.assertEqual(written(decision), 24.0)

    def test_a_thermostat_with_no_reading_of_its_own_is_given_the_target(self) -> None:
        device = AHeatOnlyThermostat(reading=None)
        self.assertEqual(written(a_pass(a_room(THERMOSTAT, 20.0), device, at(), 18.0)), 20.0)

    def test_the_number_stays_inside_the_device_s_range_and_on_its_step(self) -> None:
        # Target, the device's own reading, the room's reading, and what is written.
        for target, device_reads, room_reads, expected in (
            (28.0, 32.0, 28.0, 30.0),
            (12.0, 8.0, 12.0, 10.0),
            (20.0, 22.3, 18.0, 24.5),
        ):
            device = AHeatOnlyThermostat(device_reads)
            decision = a_pass(a_room(THERMOSTAT, target), device, at(), room_reads)
            self.assertEqual(written(decision), expected)


class TheRoomHasTheLastWordTests(unittest.TestCase):
    def test_a_setpoint_the_device_forgot_is_written_again_on_the_next_pass(self) -> None:
        device = AHeatOnlyThermostat()
        room = a_room(THERMOSTAT)
        a_pass(room, device, at(), 18.0)

        device.power_cut()
        self.assertEqual(written(a_pass(room, device, at(seconds=5), 18.0)), 24.0)
        self.assertEqual(device.setpoint, 24.0)

    def test_a_change_by_hand_at_the_device_is_overruled_on_the_next_pass(self) -> None:
        device = AHeatOnlyThermostat()
        room = a_room(THERMOSTAT)
        a_pass(room, device, at(), 18.0)

        device.setpoint = 28.0
        device.state = "off"
        a_pass(room, device, at(seconds=5), 18.0)
        self.assertEqual((device.state, device.setpoint), ("heat", 24.0))


if __name__ == "__main__":
    unittest.main()
