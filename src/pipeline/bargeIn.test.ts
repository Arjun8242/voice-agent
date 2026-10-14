import { describe, it, mock, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createBargeIn } from "./bargeIn.js";

describe("createBargeIn", () => {
    // Each test gets fresh mocks
    let answering: boolean;
    let speaking: boolean;
    let interrupted: number;      // call count
    let bargeIn: ReturnType<typeof createBargeIn>;

    beforeEach(() => {
        answering = false;
        speaking = false;
        interrupted = 0;
        bargeIn = createBargeIn({
            isAnswering: () => answering,
            isSpeaking:  () => speaking,
            interrupt:   () => { interrupted++; },
            confirmMs: 300,
        });
    });

    it("(1) not answering → interrupt never called", (t) => {
        t.mock.timers.enable({ apis: ["setTimeout"] });

        answering = false;
        bargeIn.onSpeechStart();
        t.mock.timers.tick(400);

        assert.equal(interrupted, 0);
    });

    it("(2) answering but not speaking → interrupt called immediately", (t) => {
        t.mock.timers.enable({ apis: ["setTimeout"] });

        answering = true;
        speaking  = false;
        bargeIn.onSpeechStart();

        assert.equal(interrupted, 1);
        t.mock.timers.tick(400);     // no extra calls from a timer
        assert.equal(interrupted, 1);
    });

    it("(3) answering and speaking → interrupt called only after 300 ms", (t) => {
        t.mock.timers.enable({ apis: ["setTimeout"] });

        answering = true;
        speaking  = true;
        bargeIn.onSpeechStart();

        assert.equal(interrupted, 0, "should not interrupt before timer fires");
        t.mock.timers.tick(299);
        assert.equal(interrupted, 0, "should not interrupt at 299 ms");
        t.mock.timers.tick(1);       // now at 300 ms
        assert.equal(interrupted, 1, "should interrupt at 300 ms");
    });

    it("(4) speech ends at 100 ms → interrupt never called", (t) => {
        t.mock.timers.enable({ apis: ["setTimeout"] });

        answering = true;
        speaking  = true;
        bargeIn.onSpeechStart();
        t.mock.timers.tick(100);
        bargeIn.onSpeechEnd();       // cancels the timer
        t.mock.timers.tick(300);     // timer would have fired here

        assert.equal(interrupted, 0);
    });

    it("(5) answer finishes during 300 ms wait → interrupt not called", (t) => {
        t.mock.timers.enable({ apis: ["setTimeout"] });

        answering = true;
        speaking  = true;
        bargeIn.onSpeechStart();

        // Simulate the turn finishing naturally before the timer fires
        answering = false;
        t.mock.timers.tick(300);

        assert.equal(interrupted, 0, "isAnswering() re-check prevents stale interrupt");
    });
});
