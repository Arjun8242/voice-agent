"""
test_barge_in.py — port of src/pipeline/bargeIn.test.ts.

Uses unittest.IsolatedAsyncioTestCase (stdlib, Python 3.8+) for async tests.
The TS tests used fake timers (t.mock.timers.enable); here we use a real but
tiny confirm_ms=10 ms so asyncio.call_later fires quickly without a fake-timer
library. Same 5 scenarios, same assertion order.
"""

import asyncio
import unittest


# ---------------------------------------------------------------------------
# Helper — reset shared state between tests
# ---------------------------------------------------------------------------
class BargeInTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # why: IsolatedAsyncioTestCase gives each test its own event loop;
        try:
            from pipeline.barge_in import BargeIn
        except (ImportError, ModuleNotFoundError):
            from backend.pipeline.barge_in import BargeIn

        self.answering = False
        self.speaking = False
        self.interrupted = 0  # call-count, mirrors `interrupted: number` in TS

        self.barge_in = BargeIn(
            is_answering=lambda: self.answering,
            is_speaking=lambda: self.speaking,
            interrupt=lambda: setattr(self, "interrupted", self.interrupted + 1),
            confirm_ms=50,  # small real delay; tests sleep 10 ms (before) and 100 ms (after)
        )

    # -----------------------------------------------------------------------
    # Test 1: not answering → interrupt never called
    # TS: it("(1) not answering → interrupt never called", ...)
    # -----------------------------------------------------------------------
    async def test_1_not_answering(self) -> None:
        self.answering = False
        self.barge_in.on_speech_start()
        await asyncio.sleep(0.15)  # wait well past confirm_ms=50 ms
        self.assertEqual(self.interrupted, 0)

    # -----------------------------------------------------------------------
    # Test 2: answering but not speaking → interrupt called immediately
    # TS: it("(2) answering but not speaking → interrupt called immediately", ...)
    # -----------------------------------------------------------------------
    async def test_2_answering_not_speaking(self) -> None:
        self.answering = True
        self.speaking = False
        self.barge_in.on_speech_start()
        # Interrupt is synchronous — no await needed
        self.assertEqual(self.interrupted, 1)
        await asyncio.sleep(0.05)   # no timer was set, count stays 1
        self.assertEqual(self.interrupted, 1)

    # -----------------------------------------------------------------------
    # Test 3: answering and speaking → interrupt only after confirm_ms
    # TS: it("(3) answering and speaking → interrupt called only after 300 ms", ...)
    # -----------------------------------------------------------------------
    async def test_3_answering_and_speaking(self) -> None:
        self.answering = True
        self.speaking = True
        self.barge_in.on_speech_start()
        self.assertEqual(self.interrupted, 0, "should not interrupt before timer fires")
        # Sleep less than confirm_ms (50 ms) — should still be 0
        await asyncio.sleep(0.010)
        self.assertEqual(self.interrupted, 0, "should not interrupt before 50 ms")
        # Sleep past confirm_ms
        await asyncio.sleep(0.100)
        self.assertEqual(self.interrupted, 1, "should interrupt after 50 ms elapses")

    # -----------------------------------------------------------------------
    # Test 4: speech ends before confirm_ms → interrupt never called
    # TS: it("(4) speech ends at 100 ms → interrupt never called", ...)
    # -----------------------------------------------------------------------
    async def test_4_speech_ends_early(self) -> None:
        self.answering = True
        self.speaking = True
        self.barge_in.on_speech_start()
        await asyncio.sleep(0.010)       # wait, then cancel before timer fires
        self.barge_in.on_speech_end()
        await asyncio.sleep(0.100)       # wait past what confirm_ms would have been
        self.assertEqual(self.interrupted, 0)

    # -----------------------------------------------------------------------
    # Test 5: answer finishes during wait → isAnswering() re-check prevents stale interrupt
    # TS: it("(5) answer finishes during 300 ms wait → interrupt not called", ...)
    # -----------------------------------------------------------------------
    async def test_5_answer_finishes_during_wait(self) -> None:
        self.answering = True
        self.speaking = True
        self.barge_in.on_speech_start()
        # Simulate turn finishing naturally before the timer fires
        self.answering = False
        await asyncio.sleep(0.100)      # wait past confirm_ms
        self.assertEqual(self.interrupted, 0, "isAnswering() re-check prevents stale interrupt")

    def tearDown(self) -> None:
        self.barge_in.dispose()


if __name__ == "__main__":
    unittest.main()
