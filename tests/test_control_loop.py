"""The loop between the room's reading and the relay, where a mistake is a cold room."""

from __future__ import annotations

import unittest
from datetime import timedelta

from _core import at
from core.defaults import STANDARD
from core.loop import HeaterLoop, Stage, duty_for
from core.reasons import NotHeating
from core.regulation import BandLearning, HoldingBehaviour, Regulation
from core.sensors import SensorReading, read
from core.thermostat import RoomThermostat


def room(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.room", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


class TwoStageLawTests(unittest.TestCase):
    def test_a_room_far_below_its_target_runs_at_full_output(self) -> None:
        duty, stage = duty_for(15.0, 21.0, 0.0, Regulation())
        self.assertEqual(duty, 1.0)
        self.assertIs(stage, Stage.FULL_OUTPUT)

    def test_inside_the_handover_the_room_paces_and_the_cold_outside_raises_the_duty(self) -> None:
        mild, stage = duty_for(20.5, 21.0, 10.0, Regulation())
        self.assertIs(stage, Stage.PACING)
        cold, _ = duty_for(20.5, 21.0, -15.0, Regulation())
        self.assertGreater(cold, mild)

        # A third of the handover distance, plus half a per cent for each of the eleven degrees
        # the target sits above the outdoor temperature.
        self.assertAlmostEqual(mild, 0.5 / 1.5 + 0.005 * 11.0)

    def test_a_room_at_its_target_still_fires_against_the_loss_to_outside(self) -> None:
        duty, _ = duty_for(21.0, 21.0, -9.0, Regulation())
        self.assertAlmostEqual(duty, 0.15)


class FallbackTests(unittest.TestCase):
    def test_losing_the_reading_repeats_what_a_holding_cycle_delivered(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()
        holding = loop.evaluate(at(), 20.5, 21.0, -15.0, regulation)
        self.assertIs(holding.stage, Stage.PACING)

        blind = loop.evaluate(at(minutes=20), None, 21.0, -15.0, regulation)
        self.assertIs(blind.stage, Stage.REPEATING_THE_HOLDING_DUTY)
        self.assertAlmostEqual(blind.duty, holding.delivered)

    def test_losing_the_reading_at_full_output_repeats_no_part_of_it(self) -> None:
        """A room entering the fallback from the law's own full-output stage, which is the case a
        fallback test entering from the paced stage cannot reach."""
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()
        flat_out = loop.evaluate(at(), 18.0, 21.0, -15.0, regulation)
        self.assertIs(flat_out.stage, Stage.FULL_OUTPUT)
        self.assertEqual(flat_out.delivered, 1.0)

        blind = loop.evaluate(at(minutes=20), None, 21.0, -15.0, regulation)
        self.assertIs(blind.stage, Stage.REPEATING_THE_HOLDING_DUTY)
        self.assertLess(blind.duty, 1.0)
        self.assertLessEqual(blind.delivered, regulation.deliverable_ceiling)

    def test_a_room_that_never_had_a_reading_at_that_temperature_still_heats(self) -> None:
        loop = HeaterLoop("switch.panel")
        blind = loop.evaluate(at(), None, 21.0, -15.0, Regulation())
        self.assertGreater(blind.duty, 0.0)
        self.assertGreater(blind.delivered, 0.0)


class RelayGuardTests(unittest.TestCase):
    def test_a_change_inside_the_shortest_time_is_held_and_taken_once_it_has_passed(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation(behaviour=HoldingBehaviour.BAND, band=0.5)

        closing = loop.evaluate(at(), 20.0, 21.0, 0.0, regulation)
        self.assertTrue(closing.relay_closed)

        held = loop.evaluate(at(minutes=2), 22.0, 21.0, 0.0, regulation)
        self.assertTrue(held.relay_closed)
        self.assertTrue(held.held_by_the_relay_guard)
        self.assertFalse(held.changed)

        let_go = loop.evaluate(at(minutes=6), 22.0, 21.0, 0.0, regulation)
        self.assertFalse(let_go.relay_closed)
        self.assertTrue(let_go.changed)


class DutyInsideTheCycleTests(unittest.TestCase):
    """A person setting a temperature has to see something happen, cycle or no cycle.

    Both directions were measured at the cabin on 2026-09-24: a target raised waited twelve
    minutes for heat, and a target lowered left the relay closed for five more minutes with the
    published duty reading zero and the room 3.8 degrees above its target.
    """

    def test_raising_the_target_inside_a_cycle_brings_heat_without_waiting_for_the_roll_over(
        self,
    ) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        # A room sitting at its target with nothing to do starts a cycle at no duty at all.
        settled = loop.evaluate(at(), 21.0, 21.0, 21.0, regulation)
        self.assertFalse(settled.relay_closed)
        self.assertEqual(settled.duty, 0.0)

        # Two minutes in, four degrees are asked for. That is full output, and the relay has not
        # changed yet, so nothing but the cycle could hold it.
        raised = loop.evaluate(at(minutes=2), 21.0, 25.0, 21.0, regulation)
        self.assertEqual(raised.duty, 1.0)
        self.assertTrue(raised.relay_closed)
        self.assertTrue(raised.changed)

    def test_lowering_the_target_inside_a_cycle_stops_the_heat_once_the_relay_guard_allows(
        self,
    ) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        closing = loop.evaluate(at(), 19.0, 21.0, 21.0, regulation)
        self.assertTrue(closing.relay_closed)

        # The target drops below the room. The duty the loop publishes falls to nothing, and the
        # relay is held by the shortest time between changes rather than by the cycle.
        held = loop.evaluate(at(minutes=1), 19.0, 17.0, 21.0, regulation)
        self.assertEqual(held.duty, 0.0)
        self.assertTrue(held.relay_closed)
        self.assertTrue(held.held_by_the_relay_guard)

        let_go = loop.evaluate(at(minutes=6), 19.0, 17.0, 21.0, regulation)
        self.assertEqual(let_go.duty, 0.0)
        self.assertFalse(let_go.relay_closed)
        self.assertTrue(let_go.changed)


class ReasonWhileNotHeatingTests(unittest.TestCase):
    def test_a_room_resting_in_its_cycle_is_not_reported_as_being_at_its_temperature(self) -> None:
        thermostat = RoomThermostat("toalett", ["switch.panel"])
        thermostat.set_target(21.0, at())

        # Two thirds of the cycle at a degree below target, so the rest of it is the off-phase.
        heating = thermostat.evaluate(at(), room(20.0), 21.0)
        self.assertTrue(heating.heating)

        resting = thermostat.evaluate(at(minutes=12), room(20.0, 12), 21.0)
        self.assertFalse(resting.heating)
        self.assertGreater(resting.duty, 0.0)
        self.assertLess(20.0, resting.target)
        self.assertIsNot(resting.reason, NotHeating.AT_TEMPERATURE)
        self.assertIs(resting.reason, NotHeating.PACING_THE_CYCLE)

    def test_a_settled_room_asking_for_less_than_it_can_deliver_is_at_its_temperature(
        self,
    ) -> None:
        thermostat = RoomThermostat("toalett", ["switch.panel"])
        thermostat.set_target(21.0, at())

        # The outdoor term keeps the request above nothing in a room sitting exactly at its target,
        # and a tenth of a cycle is shorter than the guard, so the cycle delivers nothing. That room
        # is at its temperature, and the pacing word must not take the phrase over.
        settled = thermostat.evaluate(at(), room(21.0), 0.0)
        self.assertFalse(settled.heating)
        self.assertGreater(settled.duty, 0.0)
        self.assertEqual(settled.delivered, 0.0)
        self.assertIs(settled.reason, NotHeating.AT_TEMPERATURE)

        resting = thermostat.evaluate(at(minutes=6), room(21.0, 6), 0.0)
        self.assertFalse(resting.heating)
        self.assertIs(resting.reason, NotHeating.AT_TEMPERATURE)

    def test_a_room_inside_its_band_is_still_reported_as_being_at_its_temperature(self) -> None:
        thermostat = RoomThermostat("toalett", ["switch.panel"])
        thermostat.set_target(21.0, at())
        thermostat.set_regulation(behaviour="band", band=0.5)

        # A band room has no off-phase to rest in, so the pacing word must not reach it even
        # where the duty underneath is above nothing.
        resting = thermostat.evaluate(at(), room(20.9), 21.0)
        self.assertFalse(resting.heating)
        self.assertGreater(resting.duty, 0.0)
        self.assertIs(resting.reason, NotHeating.AT_TEMPERATURE)


class BandLearningTests(unittest.TestCase):
    def test_the_band_narrows_on_one_measurement_and_widens_only_after_five_agree(self) -> None:
        learning = BandLearning()
        self.assertEqual(learning.band, 0.5)

        learning.observe(0.15)
        self.assertAlmostEqual(learning.band, 0.3)

        for _ in range(STANDARD.agreements_before_relaxing - 1):
            learning.observe(0.4)
            self.assertAlmostEqual(learning.band, 0.3)
        learning.observe(0.4)
        self.assertAlmostEqual(learning.band, 0.8)

    def test_the_band_never_widens_past_its_ceiling(self) -> None:
        learning = BandLearning()
        for _ in range(50):
            learning.observe(5.0)
        self.assertLessEqual(learning.band, STANDARD.band_ceiling)

    def test_clearing_a_set_band_hands_back_what_was_measured_underneath(self) -> None:
        learning = BandLearning()
        learning.set(0.9)
        learning.observe(0.2)
        self.assertEqual(learning.in_force, 0.9)

        learning.clear()
        self.assertAlmostEqual(learning.in_force, 0.4)

        learning.reset()
        self.assertEqual(learning.in_force, STANDARD.band_starting_value)
        self.assertEqual(learning.measurements, 0)


class StaggerTests(unittest.TestCase):
    def test_two_heaters_in_one_room_do_not_start_together(self) -> None:
        regulation = Regulation()
        first = HeaterLoop("switch.one", timedelta(0))
        second = HeaterLoop("switch.two", regulation.cycle_length / 2)

        # Half a degree below target, so the duty sits inside the deliverable band and the stagger
        # has something to stagger. A duty the cycle cannot deliver leaves both relays open.
        one = first.evaluate(at(), 20.5, 21.0, 10.0, regulation)
        two = second.evaluate(at(), 20.5, 21.0, 10.0, regulation)
        self.assertNotEqual(one.relay_closed, two.relay_closed)


if __name__ == "__main__":
    unittest.main()
