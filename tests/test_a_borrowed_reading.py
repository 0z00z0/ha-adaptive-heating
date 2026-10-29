"""A room with no sensor of its own heats on a neighbour's reading, and on nothing else.

The safe state is the point: a neighbour with no reading lends none, so the borrowing room stops
rather than heating on a figure nobody measured.
"""

from __future__ import annotations

import unittest

import _core  # noqa: F401 - puts the component's folder on the path
from core.sensors import NO_READING, RoomReading, borrow


class ABorrowedReadingTests(unittest.TestCase):
    def test_the_neighbour_s_temperature_is_lent_and_says_where_it_came_from(self) -> None:
        lent = borrow(RoomReading(19.5, 2, 2, ()), "climate.stue")

        self.assertEqual(lent.temperature, 19.5)
        self.assertEqual(lent.borrowed_from, "climate.stue")

    def test_a_neighbour_with_no_reading_lends_nothing(self) -> None:
        self.assertIs(borrow(RoomReading(None, 0, 2, ()), "climate.stue"), NO_READING)

    def test_a_borrowed_reading_is_never_lent_onward(self) -> None:
        onward = RoomReading(19.5, 2, 2, (), borrowed_from="climate.loft")

        self.assertIs(borrow(onward, "climate.stue"), NO_READING)


if __name__ == "__main__":
    unittest.main()
