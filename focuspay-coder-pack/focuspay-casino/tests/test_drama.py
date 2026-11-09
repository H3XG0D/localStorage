import asyncio
import unittest

from games import drama


class DramaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        drama.reset_state()
        drama.MIN_EDIT_INTERVAL = 0

    async def asyncTearDown(self):
        await drama.drain_drama()
        drama.MIN_EDIT_INTERVAL = 1.2

    async def test_run_beats_order_and_wait(self):
        seen: list[str] = []

        async def a():
            seen.append("a")

        async def b():
            seen.append("b")

        await drama.run_beats("k", [(a, 0, "one"), (b, 0, "two")])
        self.assertTrue(await drama.wait_drama("k", timeout=1))
        self.assertEqual(seen, ["a", "b"])
        self.assertTrue(drama.is_done("k"))
        self.assertEqual(drama.phase_of("k"), "two")
        self.assertFalse(drama.is_running("k"))

    async def test_skip_if_already_running(self):
        gate = asyncio.Event()
        runs = 0

        async def slow():
            nonlocal runs
            runs += 1
            await gate.wait()

        first = await drama.run_beats("slow", [(slow, 0)])
        await asyncio.sleep(0)
        second = await drama.run_beats("slow", [(slow, 0)])
        self.assertIs(first, second)
        self.assertEqual(runs, 1)
        gate.set()
        await drama.wait_drama("slow", timeout=1)

    async def test_wait_without_run_is_true(self):
        self.assertTrue(await drama.wait_drama("missing", timeout=0.1))

    async def test_drain_cancels(self):
        started = asyncio.Event()

        async def hang():
            started.set()
            await asyncio.Event().wait()

        await drama.run_beats("hang", [(hang, 0)])
        await started.wait()
        await drama.drain_drama()
        self.assertFalse(drama.is_running("hang"))
