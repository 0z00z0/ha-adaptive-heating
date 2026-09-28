"""What a heater's meter can confirm, and what it cannot.

A smart relay closing says nothing about whether the heater ran: a switch on the heater itself can be
off, or the heater can be unplugged, and the relay closes just the same. A room with a meter therefore
gets two faults a room without one cannot have, and a room without one is ordinary rather than
misconfigured.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .defaults import STANDARD, Defaults
from .reasons import Fault


class PowerWatch:
    """One room's meter, watched against what its relay was told to do."""

    def __init__(self, defaults: Defaults = STANDARD) -> None:
        self._defaults = defaults
        self.fault: Fault | None = None
        self.watts: float | None = None
        self._drew_nothing_since: datetime | None = None
        self._drew_power_since: datetime | None = None

    def observe(
        self,
        now: datetime,
        relay_closed: bool,
        below_target: bool | None,
        watts: float | None,
    ) -> Fault | None:
        """One pass. `below_target` is None in a room with no reading, where that clause cannot be asked."""
        self.watts = watts

        # An unreadable meter is never evidence that a heater is off. A room whose meter has gone quiet
        # heats exactly as a room with no meter does, and neither fault is raised while it is quiet.
        if watts is None:
            self._drew_nothing_since = None
            self._drew_power_since = None
            self.fault = None
            return None

        drawing = watts >= self._defaults.power_that_counts_as_running

        if relay_closed:
            self._drew_power_since = None
            # The room being below its target is part of the test on purpose: a heater with a thermostat
            # of its own draws nothing once that thermostat is satisfied.
            if drawing or below_target is False:
                self._drew_nothing_since = None
            else:
                self._drew_nothing_since = self._drew_nothing_since or now
        else:
            self._drew_nothing_since = None
            self._drew_power_since = (self._drew_power_since or now) if drawing else None

        self.fault = self._verdict(now, below_target)
        return self.fault

    def _verdict(self, now: datetime, below_target: bool | None) -> Fault | None:
        if self._drew_nothing_since is not None and now - self._drew_nothing_since >= self._window(below_target):
            return Fault.HEATER_DREW_NOTHING

        if self._drew_power_since is not None and now - self._drew_power_since >= self._defaults.stuck_relay_window:
            return Fault.RELAY_STUCK_CLOSED

        return None

    def _window(self, below_target: bool | None) -> timedelta:
        # A dial-controlled heater draws nothing whenever its own dial is satisfied, which looks exactly
        # like a heater switched off at the wall. Without a room temperature there is no way to tell the
        # two apart quickly, so the answer waits.
        return (
            self._defaults.drew_nothing_window
            if below_target is not None
            else self._defaults.drew_nothing_window_without_a_reading
        )
