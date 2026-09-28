"""Reaching the rules without dragging Home Assistant in.

The integration's package imports the platform, which is not installable on every machine. The
rules themselves import nothing from it, so the tests put the component's folder on the path and
import the `core` package straight off it.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "adaptive_heating"
)
if str(COMPONENT) not in sys.path:
    sys.path.insert(0, str(COMPONENT))

START = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)


def at(
    minutes: float = 0.0, hours: float = 0.0, days: float = 0.0, seconds: float = 0.0
) -> datetime:
    return START + timedelta(minutes=minutes, hours=hours, days=days, seconds=seconds)
