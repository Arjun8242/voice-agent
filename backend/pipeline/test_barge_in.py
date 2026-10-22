"""
test_barge_in.py — port of src/pipeline/bargeIn.test.ts.

Uses unittest.IsolatedAsyncioTestCase (stdlib, Python 3.8+) for async tests.
"""

import asyncio
import unittest
try:
    from pipeline.barge_in import BargeIn
except (ImportError, ModuleNotFoundError):
    from backend.pipeline.barge_in import BargeIn


class BargeInTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.answering = False
        self.speaking = False
        self.interrupted = 0

        self.barge_in = BargeIn(
            is_answering=lambda: self.answering,
            is_speaking=lambda: self.speaking,
            interrupt=lambda: setattr(self, "interrupted", self.interrupted + 1),
            confirm_ms=50,
        )

    async def test_1_not_answering(self) -> None:
        self.answering = False
        self.barge_in.on_speech_start()
        await asyncio.sleep(0.15)
        self.assertEqual(self.interrupted, 0)

    async def test_2_answering_not_speaking(self) -> None:
        self.answering = True
        self.speaking = False
        self.barge_in.on_speech_start()
        self.assertEqual(self.interrupted, 1)
        await asyncio.sleep(0.05)
        self.assertEqual(self.interrupted, 1)

    async def test_3_answering_and_speaking(self) -> None:
        self.answering = True
        self.speaking = True
        self.barge_in.on_speech_start()
        self.assertEqual(self.interrupted, 0, "should not interrupt before timer fires")
        await asyncio.sleep(0.010)
        self.assertEqual(self.interrupted, 0, "should not interrupt before 50 ms")
        await asyncio.sleep(0.100)
        self.assertEqual(self.interrupted, 1, "should interrupt after 50 ms elapses")

    async def test_4_speech_ends_early(self) -> None:
        self.answering = True
        self.speaking = True
        self.barge_in.on_speech_start()
        await asyncio.sleep(0.010)
        self.barge_in.on_speech_end()
        await asyncio.sleep(0.100)
        self.assertEqual(self.interrupted, 0)

    async def test_5_answer_finishes_during_wait(self) -> None:
        self.answering = True
        self.speaking = True
        self.barge_in.on_speech_start()
        self.answering = False
        await asyncio.sleep(0.100)
        self.assertEqual(self.interrupted, 0, "isAnswering() re-check prevents stale interrupt")

    def tearDown(self) -> None:
        self.barge_in.dispose()


if __name__ == "__main__":
    unittest.main()
