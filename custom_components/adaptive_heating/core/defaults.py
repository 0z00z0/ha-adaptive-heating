"""Every number the integration chooses rather than derives, in one place.

The figures shared with the planner are mirrored from `PlannerDefaults` in
`addon/src/AdaptiveHeating.Planner/`. The two copies drift, and a change to one is carried to the
other by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class Defaults:
    """Values shared with the planner."""

    sensor_freshness: timedelta = timedelta(hours=1)
    stuck_reading: timedelta = timedelta(hours=6)
    sensor_spread: float = 2.0
    band_starting_value: float = 0.5
    band_ceiling: float = 1.0
    agreements_before_relaxing: int = 5
    warm_up_planning_fraction: float = 0.8
    outdoor_term_per_degree: float = 0.005

    # Everything below is chosen here rather than stated in the specification.
    cycle_length: timedelta = timedelta(minutes=15)
    full_output_below: float = 1.5
    shortest_time_between_relay_changes: timedelta = timedelta(minutes=5)
    window_delay_to_stop: timedelta = timedelta(minutes=2)
    window_delay_to_resume: timedelta = timedelta(minutes=2)
    freshness_record_retention: timedelta = timedelta(days=7)
    coldest_outdoor_window: timedelta = timedelta(days=1)

    # Applied while no outdoor reading has ever been seen. Cold, so the room fires harder than it
    # needs rather than settling below its target.
    outdoor_never_seen: float = -10.0

    minimum_temperature: float = 2.0
    maximum_temperature: float = 30.0
    temperature_step: float = 0.5

    # The warming rate a room starts on, and reports as not measured until a rise has been seen.
    warming_rate_by_hand: float = 0.5

    remembered_holding_duties: int = 24

    # What a room drives at while every sensor in it is quiet, and for how long a remembered
    # fraction
    # may stand. Both are the specification's: the fraction is what a room with no history runs, and
    # the window is the stretch the fraction is measured over, so a fraction repeated longer than
    # that
    # window has stopped describing the room.
    blind_last_resort_fraction: float = 0.15
    longest_blind_spell: timedelta = timedelta(hours=24)

    # What a heater's meter has to read before the heater counts as having run, and how long each fault
    # waits. The draw and the ordinary window are stated; the long one, for a room with no reading, is
    # chosen here because a satisfied dial and a heater switched off at the wall look alike.
    power_that_counts_as_running: float = 10.0
    drew_nothing_window: timedelta = timedelta(minutes=15)
    drew_nothing_window_without_a_reading: timedelta = timedelta(hours=6)
    stuck_relay_window: timedelta = timedelta(minutes=15)


STANDARD = Defaults()
