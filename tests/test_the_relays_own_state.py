"""What the relay says about itself, read into the decision.

The loop compared what it wanted against its own model and never against the switch, so a command
accepted and ignored left model and reality disagreeing with nothing re-sent, and a command is sent
only on a change — which during a warm-up at full output means hours between commands. The guard's
clock was the loop's own stored time, so a person flipping a wall switch was invisible to it.
"""

from __future__ import annotations

import unittest

from _core import at
from core.loop import HeaterLoop, RelayObservation
from core.regulation import HoldingBehaviour, Regulation
from core.sensors import SensorReading, read
from core.thermostat import Command, RoomThermostat


def a_reading(temperature: float, minutes: float = 0.0):
    return read(
        [SensorReading("sensor.room", temperature, at(minutes=minutes), at(minutes=minutes))],
        at(minutes=minutes),
    )


class TheRelayStateReachesTheDecisionTests(unittest.TestCase):
    def test_a_relay_that_did_not_take_the_command_is_commanded_again(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        closing = loop.evaluate(at(), 18.0, 21.0, -10.0, regulation)
        self.assertTrue(closing.relay_closed)
        self.assertTrue(closing.changed)

        # The switch reports itself open a full guard later: the command was accepted and ignored.
        again = loop.evaluate(
            at(minutes=6),
            18.0,
            21.0,
            -10.0,
            regulation,
            observed=RelayObservation(False, at(minutes=1)),
        )

        self.assertTrue(again.relay_closed)
        self.assertTrue(again.changed)

    def test_a_switch_whose_state_is_unknown_is_never_fought(self) -> None:
        """Upstream's first guard: an unavailable relay is left alone rather than corrected."""
        loop = HeaterLoop("switch.panel")
        regulation = Regulation()

        loop.evaluate(at(), 18.0, 21.0, -10.0, regulation)

        quiet = loop.evaluate(
            at(minutes=6),
            18.0,
            21.0,
            -10.0,
            regulation,
            observed=RelayObservation(None, None),
        )

        self.assertTrue(quiet.relay_closed)
        self.assertFalse(quiet.changed)

    def test_a_heater_found_on_in_a_room_that_heats_nothing_is_switched_off(self) -> None:
        thermostat = RoomThermostat("stue", ["switch.stue"])
        thermostat.set_target(21.0, at())
        thermostat.switch_off(at())

        stopped = thermostat.evaluate(
            at(),
            a_reading(18.0),
            outdoor=-10.0,
            relays={"switch.stue": RelayObservation(True, at(minutes=-30))},
        )

        self.assertFalse(stopped.heating)
        self.assertEqual(stopped.commands, (Command("switch.stue", False),))


class TheGuardsClockComesFromTheSwitchTests(unittest.TestCase):
    def test_a_wall_switch_flipped_by_hand_holds_the_guard(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation(behaviour=HoldingBehaviour.BAND, band=0.5)

        # Nothing this loop did: the switch moved a minute ago and the loop has never commanded it.
        held = loop.evaluate(
            at(),
            22.0,
            21.0,
            0.0,
            regulation,
            observed=RelayObservation(True, at(minutes=-1)),
        )

        self.assertTrue(held.relay_closed)
        self.assertTrue(held.held_by_the_relay_guard)
        self.assertFalse(held.changed)

    def test_the_guard_lets_go_once_the_switchs_own_stamp_has_passed(self) -> None:
        loop = HeaterLoop("switch.panel")
        regulation = Regulation(behaviour=HoldingBehaviour.BAND, band=0.5)

        let_go = loop.evaluate(
            at(),
            22.0,
            21.0,
            0.0,
            regulation,
            observed=RelayObservation(True, at(minutes=-6)),
        )

        self.assertFalse(let_go.relay_closed)
        self.assertTrue(let_go.changed)


if __name__ == "__main__":
    unittest.main()
