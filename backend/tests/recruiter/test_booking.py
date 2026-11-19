"""Booking a meeting (S13 to S15), from the free slots to an event existing exactly once.

Three sections: the slot rules, the checkAvailability tool the model calls, and the booking flow
itself (card clicks through the real graph and gate, then the executor against the fake calendar).
The host calendar is in Asia/Kolkata; FRIDAY_NOON is Friday 2026-11-06, so the first slot is
Monday 10:00 IST (04:30 UTC).
"""

import asyncio
from datetime import datetime, timedelta
from functools import partial

import pytest

from backend.booking.availability import compute_slots
from backend.booking.execute import REPLIES as RESULT
from backend.gcal import FakeCalendar
from backend.gcal.adapter import Interval
from backend.graph.graph import build_graph
from backend.graph.nodes.agent import build_prompt
from backend.graph.nodes.booking_gate import REPLIES, VISITOR_ERRORS
from backend.graph.runner import run_turn, stream_turn
from backend.server.session import new_conversation
from backend.tests.helpers import (DESCRIPTIONS, FIRST_SLOT, FRIDAY_NOON, UTC, FakeGraph, Flow, ScriptedModel, call,
                                   make_kb, no_retrieval, sched, vt)
from backend.tools.cancel_booking import cancel_booking
from backend.tools.check_availability import check_availability
from backend.tools.registry import Tool, ToolRegistry, build_registry
from backend.tools.schemas import CancelBookingArgs, CheckAvailabilityArgs

START = datetime(2026, 11, 9, 4, 30, tzinfo=UTC)
LONDON = {"session_id": "s1", "visitor_timezone": "Europe/London"}


def ids(slots):
    return [s.id for s in slots]


# --- the slot rules -----------------------------------------------------------------

def test_slots_start_after_the_notice_skip_the_weekend_and_stop_at_the_horizon():
    slots = compute_slots(sched(), [], FRIDAY_NOON, "Asia/Kolkata")
    assert slots[0].id == FIRST_SLOT  # Friday's slots are inside the 12 hours; the weekend is skipped
    monday = [s for s in slots if s.id.startswith("2026-11-09")]
    assert len(monday) == 14 and monday[-1].id == "2026-11-09T11:00Z"  # every 30 minutes; 16:30 IST is the last start
    assert slots[-1].start <= FRIDAY_NOON + timedelta(days=14)
    monday_morning = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)  # 08:30 IST; 12 hours later is 20:30 IST
    assert compute_slots(sched(), [], monday_morning, "Asia/Kolkata")[0].id == "2026-11-10T04:30Z"


def test_the_buffer_is_kept_free_after_a_busy_time_not_before():
    busy = [Interval(datetime(2026, 11, 9, 6, 30, tzinfo=UTC), datetime(2026, 11, 9, 7, 0, tzinfo=UTC))]  # 12:00-12:30 IST
    got = ids(compute_slots(sched(), busy, FRIDAY_NOON, "Asia/Kolkata"))
    assert "2026-11-09T06:00Z" in got  # ends exactly when the busy time starts: nothing is kept free before it
    assert not {"2026-11-09T06:30Z", "2026-11-09T07:00Z"} & set(got)  # the busy time, then 30 minutes after it
    assert "2026-11-09T07:30Z" in got  # starts exactly when the buffer ends


def test_the_same_slots_read_in_each_visitors_timezone_including_summer_time():
    by_zone = {z: compute_slots(sched(), [], FRIDAY_NOON, z)[0] for z in ("Asia/Kolkata", "Europe/London", "America/New_York")}
    assert len({s.id for s in by_zone.values()}) == 1
    assert by_zone["Asia/Kolkata"].label == "Mon 09 Nov, 10:00 IST"
    assert by_zone["Europe/London"].label == "Mon 09 Nov, 04:30 GMT"
    assert by_zone["America/New_York"].label == "Sun 08 Nov, 23:30 EST"  # the day before, for this visitor
    summer_saturday = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    assert compute_slots(sched(), [], summer_saturday, "Europe/London")[0].label == "Mon 13 Jul, 05:30 BST"


def test_a_rule_left_empty_in_scheduling_yaml_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="min_notice_hours"):
        compute_slots(sched(min_notice_hours=None), [], FRIDAY_NOON, "UTC")


# --- checkAvailability, the tool the model calls ---------------------------------------

def availability(calendar=None):
    return partial(check_availability, cal=calendar or FakeCalendar(), sched=sched(), clock=lambda: FRIDAY_NOON)


def check(args, ctx=LONDON, calendar=None):
    """Through the registry, as the model calls it: a bad argument comes back as an error record."""
    registry = ToolRegistry([Tool("checkAvailability", "d", CheckAvailabilityArgs, availability(calendar))])
    return asyncio.run(registry.execute("checkAvailability", args, ctx))


def test_three_slots_in_the_visitors_timezone_spread_over_days_with_one_card():
    one_day = check({"date_from": "2026-11-09", "date_to": "2026-11-09"})
    assert [s["slot_id"] for s in one_day["result"]["slots"]] == [FIRST_SLOT, "2026-11-09T05:00Z", "2026-11-09T05:30Z"]
    assert one_day["result"]["slots"][0]["label"] == "Mon 09 Nov, 04:30 GMT"
    assert [c["type"] for c in one_day["cards"]] == ["slots"]
    assert "Only 3 of 14 matching times" in one_day["result"]["note"]  # the model must not read three as every free time
    week = check({})
    assert [s["slot_id"] for s in week["result"]["slots"]] == [FIRST_SLOT, "2026-11-10T04:30Z", "2026-11-11T04:30Z"]


def test_a_day_and_a_time_of_day_use_the_visitors_own_clock():
    kolkata = {"session_id": "s1", "visitor_timezone": "Asia/Kolkata"}
    afternoon = check({"date_from": "2026-11-10", "date_to": "2026-11-10", "time_from": "12:00", "time_to": "17:00"}, kolkata)
    assert [s["label"] for s in afternoon["result"]["slots"]] == ["Tue 10 Nov, 12:00 IST", "Tue 10 Nov, 12:30 IST", "Tue 10 Nov, 13:00 IST"]
    new_york = {"session_id": "s1", "visitor_timezone": "America/New_York"}
    tuesday = check({"date_from": "2026-11-10", "date_to": "2026-11-10"}, new_york)
    assert tuesday["result"]["slots"][0]["slot_id"] == "2026-11-10T05:00Z"  # 04:30 UTC is still Monday evening in New York


def test_no_match_says_so_and_bad_arguments_or_a_calendar_failure_are_errors_the_model_can_handle():
    late = check({"date_from": "2026-11-10", "date_to": "2026-11-10", "time_from": "20:00"})
    assert late["result"]["slots"] == [] and late["cards"] == [] and "another day or time" in late["result"]["note"]
    assert check({"date_from": "next week"})["result"]["error"] == "invalid_date"
    assert check({"time_from": "afternoon"})["result"]["error"] == "invalid_time"
    down = FakeCalendar()
    down.fail_next("free_busy")
    assert check({}, calendar=down)["result"]["error"] == "calendar_unavailable"


def test_the_offered_times_and_todays_date_reach_the_next_turns_prompt():
    registry = build_registry(make_kb(), {**DESCRIPTIONS, "checkAvailability": "d"}, calendar=FakeCalendar(), scheduling=sched())
    model = ScriptedModel([call("checkAvailability")], ["I have three times."], ["Booking that."])
    graph = build_graph(no_retrieval, model, aliases={}, registry=registry)

    async def say(text):
        async for _ in stream_turn(graph, session_id="s5", text=text, visitor_timezone="Asia/Kolkata"):
            pass

    asyncio.run(say("Can we meet next week?"))
    asyncio.run(say("The first one please"))
    offered = graph.get_state({"configurable": {"thread_id": "s5"}}).values["offered_slots"]
    prompt = model.calls[-1]["prompt"]
    assert len(offered) == 3 and f"{offered[0]['slot_id']} = {offered[0]['label']}" in prompt  # the model can pass the id
    assert "the visitor's timezone is Asia/Kolkata" in prompt and "Today is" in prompt  # needed to turn 'Monday' into a date
    assert "timezone" not in build_prompt({"query": "hi"})  # no timezone, no guessed date


# --- the booking flow -------------------------------------------------------------------

@pytest.fixture
def flow(tmp_path):
    return Flow(tmp_path)


def test_pick_fill_confirm_makes_one_event_and_the_history_never_keeps_the_form(flow):
    out = flow.pick()
    assert out["reply"] == REPLIES["form"] and [c["type"] for c in out["cards"]] == ["booking_form"]
    out = flow.to_summary()
    summary = out["cards"][0]["data"]
    assert out["reply"] == REPLIES["summary"] and out["cards"][0]["type"] == "booking_summary"
    assert (summary["name"], summary["email"], summary["title"], summary["duration_minutes"]) == ("Priya Shah", "priya@example.com", "Intro", 30)

    update = flow.click("confirm", booking_id=flow.booking_id)["update"]
    event = flow.calendar.events[flow.booking_id]
    assert len(flow.calendar.events) == 1 and flow.status() == "confirmed" and flow.model.calls == []
    assert (event.start, event.end, event.summary, event.attendee_email) == (START, START + timedelta(minutes=30), "Intro", "priya@example.com")
    assert update["outcome"] == "confirmed" and update["card"]["type"] == "booking_confirmed"
    assert update["text"] == "You're booked for Mon 09 Nov, 04:30 UTC. The invite is on its way to priya@example.com."

    texts = [m.content for m in flow.graph.get_state({"configurable": {"thread_id": "s1"}}).values["messages"]]
    assert "(The visitor clicked submit_details on the booking card.)" in texts
    assert not any("priya@example.com" in t or "Priya Shah" in t for t in texts)


def test_a_double_click_on_confirm_still_makes_one_event(flow):
    flow.book()
    again = flow.click("confirm", booking_id=flow.booking_id)
    assert again["reply"] == REPLIES["already"] and again["update"] is None and len(flow.calendar.events) == 1


def test_two_hand_offs_at_the_same_moment_make_one_event(flow):
    # a second confirm arriving while the first calendar call is still running
    flow.to_summary()
    asyncio.run(run_turn(flow.graph, session_id="s1", text="", ui_action={"action": "confirm", "payload": {"booking_id": flow.booking_id}}))

    async def both():
        return await asyncio.gather(flow.executor.run(flow.booking_id, "create"), flow.executor.run(flow.booking_id, "create"))

    results = asyncio.run(both())
    assert sorted(r is None for r in results) == [False, True] and len(flow.calendar.events) == 1


@pytest.mark.parametrize("failures,outcome,events,status", [
    ([("create_event", True)], "confirmed", 1, "confirmed"),  # Google created it but the reply timed out
    ([("create_event", False)], "confirmed", 1, "confirmed"),  # one timeout before the create is retried once
    ([("create_event", False), ("create_event", False)], "calendar_failed", 0, "failed"),  # fails honestly
])
def test_calendar_timeouts_never_double_book_or_claim_a_false_booking(flow, failures, outcome, events, status):
    for method, after_effect in failures:
        flow.calendar.fail_next(method, after_effect=after_effect)
    update = flow.book()["update"]
    assert update["outcome"] == outcome and len(flow.calendar.events) == events and flow.status() == status
    if outcome == "calendar_failed":
        assert update["text"] == RESULT["calendar_failed"]


def test_a_slot_taken_after_the_summary_is_not_booked_and_another_can_be_picked(flow):
    flow.to_summary()
    flow.calendar.busy.append(Interval(START, START + timedelta(minutes=30)))  # someone else took it
    update = flow.click("confirm", booking_id=flow.booking_id)["update"]
    assert update["outcome"] == "slot_taken" and flow.calendar.events == {} and flow.status() == "failed"
    assert flow.store.for_session("s1") is None  # nothing live: the visitor can pick another time


def test_a_taken_or_made_up_slot_is_refused_in_plain_words(flow):
    flow.calendar.busy.append(Interval(START, START + timedelta(minutes=30)))
    assert flow.pick()["reply"] == VISITOR_ERRORS["slot_unavailable"] and flow.booking_id is None
    assert flow.pick("2026-11-09T05:15Z")["reply"] == VISITOR_ERRORS["slot_unavailable"]  # off the grid: the model made it up


def test_a_bad_email_is_refused_and_the_form_stays_open(flow):
    flow.pick()
    out = flow.click("submit_details", booking_id=flow.booking_id, name="Priya", email="priya at example")
    assert "email" in out["reply"] and flow.status() == "awaiting_details"


def test_an_old_card_or_another_sessions_booking_id_changes_nothing(flow):
    flow.to_summary()
    assert flow.click("confirm", booking_id="0" * 32)["reply"] == REPLIES["stale"]
    assert flow.click("confirm", session="s2", booking_id=flow.booking_id)["reply"] == REPLIES["stale"]
    assert flow.status() == "awaiting_confirmation"


def test_picking_again_replaces_the_pending_booking_but_a_booked_visitor_must_cancel_first(flow):
    flow.pick()
    first = flow.booking_id
    flow.pick("2026-11-09T05:00Z")
    assert flow.store.get(first) is None and flow.booking_id != first
    flow.click("submit_details", booking_id=flow.booking_id, name="Priya Shah", email="priya@example.com")
    flow.click("confirm", booking_id=flow.booking_id)
    assert flow.click("select_slot", slot_id="2026-11-09T07:00Z")["reply"] == VISITOR_ERRORS["already_booked"]


def test_cancel_before_confirm_just_drops_the_booking(flow):
    flow.to_summary()
    assert flow.click("cancel", booking_id=flow.booking_id)["reply"] == REPLIES["dropped"]
    assert flow.store.for_session("s1") is None and flow.calendar.events == {}


def test_cancelling_a_meeting_asks_first_can_be_kept_and_deletes_only_after_confirming(flow):
    flow.book()
    result, cards = cancel_booking(CancelBookingArgs(), LONDON, flow.store)  # what the model's cancelBooking call does
    assert result["status"] == "awaiting_cancel_confirmation" and [c["type"] for c in cards] == ["cancel_confirm"]
    assert flow.booking_id in flow.calendar.events  # asking deletes nothing

    assert flow.click("keep_booking", booking_id=flow.booking_id)["reply"] == REPLIES["kept"] and flow.status() == "confirmed"

    cancel_booking(CancelBookingArgs(), LONDON, flow.store)
    update = flow.click("confirm_cancel", booking_id=flow.booking_id)["update"]
    assert update["outcome"] == "cancelled" and flow.calendar.events == {} and flow.status() == "cancelled"


def test_a_failed_delete_leaves_the_meeting_booked_and_the_question_open(flow):
    flow.book()
    cancel_booking(CancelBookingArgs(), LONDON, flow.store)
    flow.calendar.fail_next("delete_event")
    update = flow.click("confirm_cancel", booking_id=flow.booking_id)["update"]
    assert update["outcome"] == "cancel_failed" and flow.booking_id in flow.calendar.events
    assert flow.status() == "awaiting_cancel_confirmation"


def test_cancel_only_ever_touches_this_sessions_booking(flow):
    flow.book()
    registry = ToolRegistry([Tool("cancelBooking", "d", CancelBookingArgs, partial(cancel_booking, store=flow.store))])
    other = asyncio.run(registry.execute("cancelBooking", {}, {"session_id": "s2", "visitor_timezone": "Europe/London"}))
    assert other["result"]["error"] == "no_booking" and flow.status() == "confirmed"


def test_the_voice_turn_passes_the_confirm_hand_off_to_the_connection():
    handoffs = []

    async def send(*_):
        pass

    graph = FakeGraph([("custom", {"type": "booking_execute", "booking_id": "b" * 32, "kind": "create"})])
    asyncio.run(vt.voice_turn("", new_conversation(), send, asyncio.Event(), None, graph, "s1", on_booking_execute=handoffs.append))
    assert handoffs == [{"type": "booking_execute", "booking_id": "b" * 32, "kind": "create"}]
