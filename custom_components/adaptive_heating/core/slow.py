"""A Slow room: the air held on a model of the room, judged one dead time ahead."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from .defaults import STANDARD, Defaults
from .loop import duty_for
from .regulation import Regulation

DECISION_INTERVAL = timedelta(minutes=5)
BLOCK = timedelta(minutes=15)
BLOCKS_KEPT = 8
# A block with less than this covered is dropped rather than published short.
BLOCK_COVERED = timedelta(minutes=14)
# A longer gap between two evaluations is Home Assistant away, never a reading held.
LONGEST_STEP = timedelta(minutes=5)
SAMPLE_SPACING = timedelta(minutes=1)
WARM_UP_ARRIVED = 0.05
FLOOR_CUT_BELOW_LIMIT = 0.5
# Assumed where the add-on has sent none: the floor as far above the air as the air above outdoors.
FLOOR_RISE_UNKNOWN = 1.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def _hours(span: timedelta) -> float:
    return span.total_seconds() / 3600.0


class Predictor:
    """The heater's part of the air in the model: now, and as the sensor will see it one dead time later."""

    def __init__(self) -> None:
        self.at: datetime | None = None
        self.rise_now = 0.0
        self.samples: deque[tuple[datetime, float]] = deque()

    def seed(self, at: datetime, share: float, rise: float) -> None:
        """Settled at a share: the heat in flight equals the heat arriving, so the prediction is the reading."""
        self.at = at
        self.rise_now = share * rise
        self.samples = deque([(at, self.rise_now)])

    def advance(self, now: datetime, share: float, regulation: Regulation) -> None:
        if self.at is None or now <= self.at:
            return
        rise = regulation.full_output_rise or 0.0
        lag = regulation.lag.total_seconds()  # type: ignore[union-attr]
        goal = share * rise
        elapsed = (now - self.at).total_seconds()
        self.rise_now = goal + (self.rise_now - goal) * math.exp(-elapsed / lag)
        self.at = now
        if now - self.samples[-1][0] >= SAMPLE_SPACING:
            self.samples.append((now, self.rise_now))
        # One sample at or before the oldest moment still looked up stays, for the interpolation.
        oldest = now - regulation.dead_time - SAMPLE_SPACING  # type: ignore[operator]
        while len(self.samples) > 1 and self.samples[1][0] <= oldest:
            self.samples.popleft()

    def rise_at(self, moment: datetime) -> float:
        first = self.samples[0]
        if moment <= first[0]:
            return first[1]
        for (t0, v0), (t1, v1) in zip(self.samples, list(self.samples)[1:], strict=False):
            if moment <= t1:
                return v0 + (v1 - v0) * (moment - t0).total_seconds() / (t1 - t0).total_seconds()
        return self.rise_now

    def ahead(self, air: float, regulation: Regulation) -> float:
        assert self.at is not None
        return air + self.rise_now - self.rise_at(self.at - regulation.dead_time)  # type: ignore[operator]

    def as_dict(self) -> dict[str, object]:
        if self.at is None:
            return {}
        return {
            "at": self.at.isoformat(),
            "rise_now": self.rise_now,
            "samples": [[(t - self.at).total_seconds(), v] for t, v in self.samples],
        }

    @classmethod
    def from_dict(cls, stored: object) -> Predictor:
        predictor = cls()
        if not isinstance(stored, dict) or not stored:
            return predictor
        try:
            at = datetime.fromisoformat(str(stored["at"]))
            samples = deque(
                (at + timedelta(seconds=float(s[0])), float(s[1])) for s in stored["samples"]
            )
            rise_now = float(stored["rise_now"])
        except (KeyError, IndexError, TypeError, ValueError):
            return predictor
        if samples:
            predictor.at, predictor.rise_now, predictor.samples = at, rise_now, samples
        return predictor


@dataclass(slots=True)
class Block:
    """One quarter hour of what the add-on fits a Slow room's model from."""

    start: datetime
    covered: float = 0.0
    closed: float = 0.0
    air: float = 0.0
    air_covered: float = 0.0
    outdoor: float = 0.0
    outdoor_covered: float = 0.0
    floor: float = 0.0
    floor_covered: float = 0.0

    def add(
        self, seconds: float, share: float, air: float | None, outdoor: float | None,
        floor: float | None,
    ) -> None:
        self.covered += seconds
        self.closed += share * seconds
        if air is not None:
            self.air += air * seconds
            self.air_covered += seconds
        if outdoor is not None:
            self.outdoor += outdoor * seconds
            self.outdoor_covered += seconds
        if floor is not None:
            self.floor += floor * seconds
            self.floor_covered += seconds

    def published(self) -> dict[str, object]:
        def mean(total: float, seconds: float) -> float | None:
            return None if seconds <= 0.0 else round(total / seconds, 3)

        return {
            "start": self.start.isoformat(),
            "air": mean(self.air, self.air_covered),
            "outdoor": mean(self.outdoor, self.outdoor_covered),
            "floor": mean(self.floor, self.floor_covered),
            "closed": round(self.closed / self.covered, 4),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(),
            "sums": [
                self.covered, self.closed, self.air, self.air_covered, self.outdoor,
                self.outdoor_covered, self.floor, self.floor_covered,
            ],
        }

    @classmethod
    def from_dict(cls, stored: object) -> Block | None:
        if not isinstance(stored, dict):
            return None
        try:
            return cls(
                datetime.fromisoformat(str(stored["start"])),
                *(float(v) for v in stored["sums"]),  # type: ignore[union-attr]
            )
        except (KeyError, TypeError, ValueError):
            return None


def _block_start(moment: datetime) -> datetime:
    minutes = moment.minute - moment.minute % 15
    return moment.replace(minute=minutes, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class SlowShare:
    share: float
    predicted: float | None
    full_output: bool
    blind: bool


class SlowRoom:
    """The model, the two slow PIs, the carried remainder and the quarter-hour record of one room."""

    def __init__(self, defaults: Defaults = STANDARD) -> None:
        self._defaults = defaults
        self.predictor = Predictor()
        self.seeded_for: tuple[float, float, float] | None = None
        self.integral = 0.0
        self.floor_integral = 0.0
        self.owed = 0.0
        self.share = 0.0
        self.decided_at: datetime | None = None
        self.full_output = False
        self.predicted: float | None = None
        # The deadline of the warm-up whose start a decision has taken; its start no longer moves.
        self.warm_up_started_for: datetime | None = None
        self.noted_at: datetime | None = None
        self.last_air: float | None = None
        self.last_outdoor: float | None = None
        self.last_floor: float | None = None
        self.block: Block | None = None
        self.blocks: deque[dict[str, object]] = deque(maxlen=BLOCKS_KEPT)

    # ----- what happened since the last evaluation ----------------------------------------------

    def note(
        self,
        now: datetime,
        share: float,
        air: float | None,
        outdoor: float | None,
        floor: float | None,
        regulation: Regulation,
    ) -> None:
        """The relays held `share` since the last evaluation; the readings are this evaluation's."""
        if self.noted_at is not None and now > self.noted_at:
            if now - self.noted_at <= LONGEST_STEP:
                self._record(self.noted_at, now, share)
            self._advance(now, share, regulation)
        elif regulation.model_learnt:
            self._advance(now, share, regulation)
        self.noted_at = now
        self.last_air, self.last_outdoor, self.last_floor = air, outdoor, floor

    def _advance(self, now: datetime, share: float, regulation: Regulation) -> None:
        if not regulation.model_learnt:
            self.seeded_for = None
            self.predicted = None
            return
        figures = (
            regulation.dead_time.total_seconds(),  # type: ignore[union-attr]
            regulation.lag.total_seconds(),  # type: ignore[union-attr]
            float(regulation.full_output_rise),  # type: ignore[arg-type]
        )
        if self.seeded_for != figures or self.predictor.at is None:
            # A new model starts settled at what the relays held lately, as if nothing were in flight.
            self.predictor.seed(now, self.recent_share(share), figures[2])
            self.seeded_for = figures
            self.integral = 0.0
            self.floor_integral = 0.0
            return
        self.predictor.advance(now, share, regulation)

    def recent_share(self, fallback: float) -> float:
        shares = [float(b["closed"]) for b in self.blocks]  # type: ignore[arg-type]
        return fallback if not shares else sum(shares) / len(shares)

    def _record(self, start: datetime, end: datetime, share: float) -> None:
        moment = start
        while moment < end:
            block_start = _block_start(moment)
            if self.block is None or self.block.start != block_start:
                self._finish_block()
                self.block = Block(block_start)
            until = min(end, block_start + BLOCK)
            self.block.add(
                (until - moment).total_seconds(), share, self.last_air, self.last_outdoor,
                self.last_floor,
            )
            moment = until
        if self.block is not None and end >= self.block.start + BLOCK:
            self._finish_block()

    def _finish_block(self) -> None:
        if self.block is not None and self.block.covered >= BLOCK_COVERED.total_seconds():
            self.blocks.append(self.block.published())
        self.block = None

    # ----- the decision -------------------------------------------------------------------------

    def due(self, now: datetime) -> bool:
        return self.decided_at is None or now - self.decided_at >= DECISION_INTERVAL

    def ahead(self, air: float | None, regulation: Regulation) -> float | None:
        if air is None or not regulation.model_learnt or self.predictor.at is None:
            return None
        return self.predictor.ahead(air, regulation)

    def decide(
        self,
        now: datetime,
        air: float | None,
        floor: float | None,
        outdoor: float,
        target: float,
        warming: bool,
        regulation: Regulation,
    ) -> SlowShare:
        """Every five minutes; the share then stands until the next decision."""
        self.predicted = self.ahead(air, regulation)
        if not self.due(now):
            return SlowShare(self.share, self.predicted, self.full_output, air is None)
        self.decided_at = now
        step_h = _hours(DECISION_INTERVAL)
        rise = float(regulation.full_output_rise)  # type: ignore[arg-type]
        lag_h = _hours(regulation.lag)  # type: ignore[arg-type]
        kp = 1.0 / rise
        feed = (target - outdoor) / rise
        self.full_output = False

        if regulation.floor_limited and floor is not None:
            wanted = self._cascade(air, floor, outdoor, target, regulation)
        elif air is None:
            # Blind: the feed-forward and the correction as last learnt, which stops moving.
            wanted = _clamp(feed + kp * self.integral)
        elif warming and self.predicted < target - WARM_UP_ARRIVED:  # type: ignore[operator]
            wanted = 1.0
            self.full_output = True
        else:
            error = target - self.predicted  # type: ignore[operator]
            u = feed + kp * (error + self.integral)
            # Conditional integration: nothing is added while the output is pinned.
            if 0.0 < u < 1.0:
                self.integral += error * step_h / lag_h
            wanted = _clamp(u)

        if regulation.floor_limited and floor is None:
            wanted = min(wanted, self.floor_safe_share(outdoor, regulation))

        command = _clamp(wanted + self.owed)
        delivered = regulation.deliverable(command)
        self.owed = _clamp(
            self.owed + (wanted - delivered) * DECISION_INTERVAL / regulation.cycle_length,
            -1.0, 1.0,
        )
        self.share = command
        return SlowShare(command, self.predicted, self.full_output, air is None)

    def _cascade(
        self, air: float | None, floor: float, outdoor: float, target: float, regulation: Regulation
    ) -> float:
        """The air sets a floor temperature between the air target and the limit; the paced law holds the floor."""
        lag_h = _hours(regulation.lag)  # type: ignore[arg-type]
        dead_h = _hours(regulation.dead_time)  # type: ignore[arg-type]
        # Floor to air: the slab's own lag taken out, the inner loop's lag counted as delay.
        tau = max(lag_h * 0.35, 0.5)
        theta = max(dead_h, 1.0)
        kc, ti = tau / (2.0 * theta), min(tau, 8.0 * theta)
        rise_per_degree = regulation.floor_rise_per_degree or 0.0
        feed = target + rise_per_degree * max(target - outdoor, 0.0)
        error = 0.0 if air is None else target - air
        goal = feed + kc * (error + self.floor_integral)
        low, high = target, float(regulation.floor_limit)  # type: ignore[arg-type]
        if low < goal < high:
            self.floor_integral += error * _hours(DECISION_INTERVAL) / ti
        goal = _clamp(goal, low, high)
        return duty_for(floor, goal, outdoor, regulation, self._defaults)[0]

    @staticmethod
    def floor_safe_share(outdoor: float, regulation: Regulation) -> float:
        """The share whose settled floor stays under the cut: floor = outdoor + share x rise x (1 + r)."""
        rise = float(regulation.full_output_rise)  # type: ignore[arg-type]
        r = regulation.floor_rise_per_degree
        r = FLOOR_RISE_UNKNOWN if r is None else r
        room = float(regulation.floor_limit) - FLOOR_CUT_BELOW_LIMIT - outdoor  # type: ignore[arg-type]
        return _clamp(room / (rise * (1.0 + r)))

    def cut(self) -> None:
        """The floor at its limit: nothing owed is paid back into it."""
        self.owed = 0.0
        self.share = 0.0

    # ----- a warm-up on the model ---------------------------------------------------------------

    def warm_up_start(
        self,
        temperature: float,
        deadline: datetime,
        now: datetime,
        predicted: float | None,
        outdoor: float,
        regulation: Regulation,
    ) -> tuple[datetime, float | None, float | None]:
        """When full output has to start, and what the room reaches where it cannot make it."""
        if predicted is None or predicted >= temperature:
            return deadline, temperature, None
        rise = float(regulation.full_output_rise)  # type: ignore[arg-type]
        ceiling = outdoor + rise
        dead, lag = regulation.dead_time, regulation.lag
        if temperature < ceiling:
            needed = dead + lag * math.log((ceiling - predicted) / (ceiling - temperature))  # type: ignore[operator]
            if deadline - needed > now:
                return deadline - needed, temperature, None
        heating = max(0.0, (deadline - now - dead).total_seconds())  # type: ignore[operator]
        reaches = ceiling - (ceiling - predicted) * math.exp(-heating / lag.total_seconds())  # type: ignore[union-attr]
        short_by = None if reaches >= temperature else round(temperature - reaches, 3)
        return now, round(reaches, 3), short_by

    # ----- what survives a restart ----------------------------------------------------------------

    def as_dict(self) -> dict[str, object]:
        return {
            "predictor": self.predictor.as_dict(),
            "seeded_for": None if self.seeded_for is None else list(self.seeded_for),
            "integral": self.integral,
            "floor_integral": self.floor_integral,
            "owed": self.owed,
            "share": self.share,
            "decided_at": None if self.decided_at is None else self.decided_at.isoformat(),
            "warm_up_started_for": None if self.warm_up_started_for is None
            else self.warm_up_started_for.isoformat(),
            "block": None if self.block is None else self.block.as_dict(),
            "blocks": list(self.blocks),
        }

    @classmethod
    def from_dict(cls, stored: object, defaults: Defaults = STANDARD) -> SlowRoom:
        room = cls(defaults)
        if not isinstance(stored, dict):
            return room
        try:
            room.predictor = Predictor.from_dict(stored.get("predictor"))
            seeded = stored.get("seeded_for")
            room.seeded_for = None if seeded is None else tuple(float(v) for v in seeded)  # type: ignore[assignment]
            room.integral = float(stored.get("integral", 0.0))
            room.floor_integral = float(stored.get("floor_integral", 0.0))
            room.owed = float(stored.get("owed", 0.0))
            room.share = float(stored.get("share", 0.0))
            decided = stored.get("decided_at")
            room.decided_at = None if decided is None else datetime.fromisoformat(str(decided))
            started = stored.get("warm_up_started_for")
            room.warm_up_started_for = (
                None if started is None else datetime.fromisoformat(str(started))
            )
            room.block = Block.from_dict(stored.get("block"))
            for block in stored.get("blocks") or []:
                if isinstance(block, dict):
                    room.blocks.append(block)
        except (TypeError, ValueError):
            return cls(defaults)
        # The predictor resumes where it was written down; the time away is filled by the next note.
        room.noted_at = room.predictor.at
        return room
