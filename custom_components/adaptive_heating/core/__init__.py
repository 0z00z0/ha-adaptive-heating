"""The rules, with no Home Assistant type anywhere in them.

Everything in this package takes numbers and times as parameters and returns decisions. Nothing
reads a clock, opens a file or imports the platform, which is what lets the rules be exercised on
their own.
"""

from __future__ import annotations
