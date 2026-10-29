"""A room keeps its identity when it changes area: the area is the room's attribute, not its key.

What only a running Home Assistant settles (the device registry moving the device, the action reaching
the entity) is in `test_against_home_assistant`.
"""

from __future__ import annotations

import unittest

from _core import COMPONENT  # noqa: F401 - puts the component on the path
from core import actions as table
from core.identity import (
    A_ROOM_HAS_AN_AREA,
    ANOTHER_ROOM_IS_THERE,
    NO_SUCH_AREA,
    DeviceMove,
    RoomIdentity,
    follow_the_device,
    identify,
    moved,
    refuse_move,
    room_id,
)


class FindingTheRoomsThroughTheLinkTests(unittest.TestCase):
    def test_a_first_discovery_numbers_each_room_and_writes_the_link(self) -> None:
        found, links, highest = identify(["stue", "bad"], {}, 0)

        self.assertEqual(found, {"room_001": "bad", "room_002": "stue"})
        self.assertEqual(links, found)
        self.assertEqual(highest, 2)

    def test_a_room_moved_to_another_area_is_found_there_under_its_own_id(self) -> None:
        links = moved({"room_001": "stue"}, "room_001", "garasje")

        found, _, _ = identify(["garasje"], links, 1)

        self.assertEqual(found, {"room_001": "garasje"})

    def test_an_area_with_no_room_gets_the_next_number(self) -> None:
        found, links, highest = identify(["stue", "kontor"], {"room_001": "stue"}, 1)

        self.assertEqual(found["room_002"], "kontor")
        self.assertEqual(links["room_002"], "kontor")
        self.assertEqual(highest, 2)

    def test_a_removed_room_s_number_is_never_issued_again(self) -> None:
        # room_001's link is gone: room_002 moved into its area. The next room is room_003.
        links = moved({"room_001": "garasje", "room_002": "stue"}, "room_002", "garasje")

        found, links, highest = identify(["garasje", "stue"], links, 2)

        self.assertEqual(found, {"room_002": "garasje", "room_003": "stue"})
        self.assertEqual(highest, 3)

    def test_the_number_has_three_digits_and_grows_past_them(self) -> None:
        self.assertEqual(
            (room_id(1), room_id(999), room_id(1000)), ("room_001", "room_999", "room_1000")
        )

    def test_a_room_s_unique_id_store_and_device_never_change_with_its_area(self) -> None:
        before, links, highest = identify(["stue"], {}, 0)
        after, _, _ = identify(["garasje"], moved(links, "room_001", "garasje"), highest)

        (was,) = before
        (now,) = after
        self.assertEqual(RoomIdentity(now), RoomIdentity(was))
        self.assertEqual(RoomIdentity(now).unique_id, "room_001")
        self.assertEqual(RoomIdentity(now).store_key, "adaptive_heating.room_001")
        self.assertEqual(RoomIdentity(now).device_identifier, ("adaptive_heating", "room_001"))


class MovingARoomTests(unittest.TestCase):
    AREAS = ("stue", "bad", "garasje")

    def test_an_area_another_room_is_in_is_refused(self) -> None:
        present = {"stue": "stue", "bad": "bad"}

        self.assertEqual(refuse_move("stue", "bad", present, self.AREAS), ANOTHER_ROOM_IS_THERE)

    def test_an_area_home_assistant_does_not_have_is_refused(self) -> None:
        self.assertEqual(refuse_move("stue", "loft", {"stue": "stue"}, self.AREAS), NO_SUCH_AREA)

    def test_a_free_area_is_taken(self) -> None:
        self.assertIsNone(refuse_move("stue", "garasje", {"stue": "stue", "bad": "bad"}, self.AREAS))

    def test_the_link_of_a_room_no_longer_present_gives_way_to_the_room_moving_in(self) -> None:
        self.assertEqual(
            moved({"stue": "stue", "loft": "garasje"}, "stue", "garasje"), {"stue": "garasje"}
        )

    def test_the_action_takes_one_area_and_never_an_empty_one(self) -> None:
        action = table.BY_NAME[table.MOVE_TO_AREA]
        (area,) = action.fields_for_the_schema().values()

        self.assertEqual(area("garasje"), "garasje")
        with self.assertRaises(Exception):
            area("  ")


class FollowingADeviceMovedByHandTests(unittest.TestCase):
    AREAS = ("stue", "bad", "garasje")
    LINKS = {"stue": "stue", "bad": "bad"}
    PRESENT = {"stue": "stue", "bad": "bad"}

    def follow(self, area: str | None) -> tuple[DeviceMove, str | None]:
        return follow_the_device("stue", area, self.LINKS, self.PRESENT, self.AREAS)

    def test_a_device_moved_to_a_free_area_takes_the_room_there_under_its_own_id(self) -> None:
        self.assertEqual(self.follow("garasje"), (DeviceMove.FOLLOW, None))

        found, _, _ = identify(["garasje", "bad"], moved(self.LINKS, "stue", "garasje"), 2)

        self.assertEqual(found["stue"], "garasje")

    def test_a_device_moved_where_another_room_is_goes_back(self) -> None:
        self.assertEqual(self.follow("bad"), (DeviceMove.PUT_BACK, ANOTHER_ROOM_IS_THERE))

    def test_a_device_taken_out_of_every_area_goes_back(self) -> None:
        self.assertEqual(self.follow(None), (DeviceMove.PUT_BACK, A_ROOM_HAS_AN_AREA))

    def test_a_device_already_where_its_link_says_moves_nothing(self) -> None:
        # The device's own event after `move_to_area` or a put-back must not start another move.
        self.assertEqual(self.follow("stue"), (DeviceMove.NOTHING, None))


if __name__ == "__main__":
    unittest.main()
