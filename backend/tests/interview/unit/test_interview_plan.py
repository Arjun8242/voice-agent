"""The plan's shape: stage budgets on every topic, stage order, and the preview line."""

from __future__ import annotations

from backend.interview.plan import (
    STAGES,
    intro_topic,
    live_stage,
    make_topic,
    order_plan,
    plan_preview,
)


def test_every_topic_carries_its_stages_budget():
    topic = make_topic("behavioral", "conflict", "a disagreement", "", "Tell me about a disagreement.")
    assert (topic["topic_id"], topic["min_q"], topic["max_q"], topic["max_level"]) == ("behavioral:conflict", 1, 2, 3)
    assert set(STAGES) == {"intro", "deep_dive", "technical", "behavioral", "achievement"}


def test_topics_are_put_in_stage_order_and_a_stage_without_topics_is_left_out():
    tech = make_topic("technical", "sql", "SQL", "", "How do indexes work?")
    deep = make_topic("deep_dive", "beacon", "Beacon", "", "What does Beacon do?")
    assert [t["kind"] for t in order_plan([tech, deep, intro_topic()])] == ["intro", "deep_dive", "technical"]


def test_the_preview_names_every_topic_after_the_intro():
    topics = [intro_topic(), make_topic("deep_dive", "acme", "your work at Acme", "", "Q?"),
              make_topic("technical", "java", "Java", "", "Q?"), make_topic("behavioral", "own", "teamwork", "", "Q?")]
    assert plan_preview(topics) == "We'll cover your work at Acme, Java and teamwork."


def test_the_live_stage_is_the_current_topics_stage_then_wrap_once_finished():
    topics = order_plan([intro_topic(), make_topic("technical", "sql", "SQL", "Postgres", "How do indexes work?")])
    assert live_stage(topics, 0, finished=False) == "intro"
    assert live_stage(topics, 1, finished=False) == "technical"
    assert live_stage(topics, 1, finished=True) == "wrap"
    assert live_stage([], 0, finished=False) is None  # no plan yet: nothing to show
