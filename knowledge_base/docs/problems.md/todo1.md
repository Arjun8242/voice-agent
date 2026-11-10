#TODO

think about this problem

The cancellable-task note

When a visitor interrupts, your code cancels the running turn task (an asyncio cancel). That stops the LLM stream and the TTS. Everything inside answer_turn gets stopped, because it all runs inside that one task.

The graph is more code running during a turn. The risk is how you start it:

If you call it in a detached task (asyncio.create_task, a thread, or a background worker), the cancel won’t reach it. After the visitor interrupts, the graph would keep running. It could make more LLM calls, show stale cards, or trigger a booking action the visitor already moved on from. A duplicate or unwanted booking is the worst case.
If you use a synchronous call (graph.invoke), it blocks the event loop, which freezes audio and can’t be cancelled at all.

So the rule is to run the graph inside answer_turn, using the async API, and not to spawn anything detached. A sketch (adapt the names to your code):

python
async def answer_turn(state_in):
    try:
        async for event in graph.astream(state_in, stream_mode=...):
            await handle(event)   # tokens to TTS, cards to UI
    except asyncio.CancelledError:
        # clean up: mark the turn as cancelled, drop pending cards
        raise                      # always re-raise

Two details for later (S12 and S15):

Always re-raise CancelledError after cleanup.
The booking execute step is the one place that should be protected from cancellation (your design doc calls it a shielded execute), so an interrupt can’t leave a half-finished booking.

Keeping answer_turn as the only place the graph is called means barge-in keeps working exactly as it does now.

since the answer_turn line is the Integration point of Langgraph graph