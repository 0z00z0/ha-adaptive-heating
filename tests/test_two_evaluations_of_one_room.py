"""Two evaluations of one room, and what happens to a change that arrives during one.

The heaters a room commands are in the list it watches, so a relay closing raises a state change
that lands back on the room that closed it. That change arrives while the evaluation which caused
it is still awaiting the command, so these tests drive exactly that overlap.
"""

from __future__ import annotations

import asyncio
import unittest

from _core import at  # noqa: F401 - keeps the component folder on the path
from core.serialisation import OneAtATime


class TwoEvaluationsOfOneRoomTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_second_evaluation_does_not_interleave_with_the_first(self) -> None:
        inside = 0
        most_at_once = 0
        the_first_is_inside = asyncio.Event()
        let_it_finish = asyncio.Event()

        async def evaluate() -> None:
            nonlocal inside, most_at_once
            inside += 1
            most_at_once = max(most_at_once, inside)
            the_first_is_inside.set()
            await let_it_finish.wait()
            inside -= 1

        gate = OneAtATime(evaluate)
        first = asyncio.create_task(gate.after_a_change())
        await the_first_is_inside.wait()

        second = asyncio.create_task(gate.after_a_change())
        await asyncio.sleep(0)

        let_it_finish.set()
        await asyncio.gather(first, second)

        self.assertEqual(most_at_once, 1)
        self.assertEqual(inside, 0)

    async def test_a_change_arriving_during_an_evaluation_is_not_lost(self) -> None:
        what_the_sensor_says = 18.0
        what_each_pass_read: list[float] = []
        the_first_is_inside = asyncio.Event()
        let_it_finish = asyncio.Event()

        async def evaluate() -> None:
            what_each_pass_read.append(what_the_sensor_says)
            if len(what_each_pass_read) == 1:
                the_first_is_inside.set()
                await let_it_finish.wait()

        gate = OneAtATime(evaluate)
        first = asyncio.create_task(gate.after_a_change())
        await the_first_is_inside.wait()

        # The room warms while the first pass is still awaiting its heater command, so that pass
        # read 18.0 and can never see 19.5.
        what_the_sensor_says = 19.5
        await gate.after_a_change()
        self.assertTrue(gate.another_pass_is_wanted)

        let_it_finish.set()
        await first

        self.assertEqual(what_each_pass_read, [18.0, 19.5])

    async def test_several_changes_during_one_evaluation_collapse_into_a_single_pass(self) -> None:
        passes = 0
        the_first_is_inside = asyncio.Event()
        let_it_finish = asyncio.Event()

        async def evaluate() -> None:
            nonlocal passes
            passes += 1
            if passes == 1:
                the_first_is_inside.set()
                await let_it_finish.wait()

        gate = OneAtATime(evaluate)
        first = asyncio.create_task(gate.after_a_change())
        await the_first_is_inside.wait()

        for _ in range(5):
            await gate.after_a_change()

        let_it_finish.set()
        await first

        self.assertEqual(passes, 2)

    async def test_a_persons_action_waits_its_turn_rather_than_collapsing(self) -> None:
        """A coalesced action would defer the store write that records what a person set."""
        the_action_ran = False
        the_first_is_inside = asyncio.Event()
        let_it_finish = asyncio.Event()

        async def evaluate() -> None:
            the_first_is_inside.set()
            await let_it_finish.wait()

        async def set_a_temperature() -> None:
            nonlocal the_action_ran
            the_action_ran = True

        gate = OneAtATime(evaluate)
        first = asyncio.create_task(gate.after_a_change())
        await the_first_is_inside.wait()

        action = asyncio.create_task(gate.at_once(set_a_temperature))
        await asyncio.sleep(0)
        self.assertFalse(the_action_ran)

        let_it_finish.set()
        await asyncio.gather(first, action)

        self.assertTrue(the_action_ran)

    async def test_a_room_going_away_starts_no_further_pass(self) -> None:
        passes = 0

        async def evaluate() -> None:
            nonlocal passes
            passes += 1

        gate = OneAtATime(evaluate)
        await gate.after_a_change()
        gate.close()

        await gate.after_a_change()
        await gate.at_once(evaluate)

        self.assertEqual(passes, 1)


if __name__ == "__main__":
    unittest.main()
