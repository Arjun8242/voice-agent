"""The end-of-interview report (C4): what the evaluator model is sent, how its JSON is checked, and how
quotes not found in the notes are dropped. A scripted evaluator, no network.

Plan scenarios T18-T20 (a confidently wrong answer, an incomplete one, a KB without the detail) need the
real model and are eval cases; here the code around the model is tested.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.graph.interview.state import Answer
from backend.interview.evaluate import (
    EVALUATOR_MAX_TOKENS,
    build_evaluator_message,
    evaluate_interview,
    in_notes,
    load_evaluator_prompt,
    parse_model_report,
)
from backend.interview.plan import Topic
from backend.observability.usage import LlmUsage
from backend.rag import llm
from backend.tests.test_agent import FakeGroq, chunk

TOPICS = [
    Topic(topic_id="beacon", title="Beacon", text="The scheduler takes a **Postgres advisory lock** before it schedules checks."),
    Topic(topic_id="fitai", title="FitAI", text="FitAI plans workouts with an LLM and stores logs in MongoDB."),
]
ANSWERS = [
    Answer(topic_id="beacon", question="How does Beacon avoid double scheduling?", text="It uses a Kafka lock, I think."),
    Answer(topic_id="beacon", question="What happens to the lock on a crash?", text="Postgres releases it."),
    Answer(topic_id="fitai", question="What does FitAI do?", text="It plans workouts."),
]


def review(index: int, score: int = 3, **lists) -> dict:
    return {"index": index, "score": score, **lists}


def reply(reviews: list[dict], tips: list[str] | None = None) -> str:
    return json.dumps({"answers": reviews, "tips": tips if tips is not None else ["a", "b", "c"]})


def all_reviews(**first) -> list[dict]:
    return [review(1, **first), review(2), review(3)]


class FakeEvaluator:
    """Each call takes the next reply: a string (streamed in two pieces, then a usage piece) or an exception."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt: str, system_instruction: str):
        self.calls.append((prompt, system_instruction))
        reply_ = self.replies.pop(0)

        async def gen():
            if isinstance(reply_, Exception):
                raise reply_
            yield reply_[:20]
            yield reply_[20:]
            yield LlmUsage(input_tokens=1, output_tokens=1, cached_tokens=0, reasoning_tokens=0)
        return gen()


def evaluate(fake: FakeEvaluator, answers: list[Answer] = ANSWERS):
    return asyncio.run(evaluate_interview(answers, TOPICS, fake))


# --- what the model is sent -----------------------------------------------------------------

def test_each_topics_notes_are_sent_once_then_the_numbered_answers():
    message = build_evaluator_message(ANSWERS, {t["topic_id"]: t for t in TOPICS})
    assert message.count("Postgres advisory lock") == 1  # two Beacon answers, one copy of its notes
    assert message.index("## Topic: Beacon") < message.index("## Topic: FitAI") < message.index("## Answers")
    assert "1. Topic: Beacon\nQuestion: How does Beacon avoid double scheduling?\nAnswer: It uses a Kafka lock, I think." in message
    assert "3. Topic: FitAI\nQuestion: What does FitAI do?" in message


def test_the_model_gets_the_evaluator_rules_as_its_system_prompt():
    fake = FakeEvaluator(reply(all_reviews()))
    evaluate(fake)
    system = fake.calls[0][1]
    assert system == load_evaluator_prompt()
    for rule in ("never incorrect", "word for word", "exactly 3 tips", '"answers"'):
        assert rule in system, rule


def test_no_answers_means_an_empty_report_and_no_model_call():
    fake = FakeEvaluator()
    report = evaluate(fake, answers=[])
    assert (report.reviews, report.tips, report.average_score, fake.calls) == ([], [], None, [])


# --- the report -----------------------------------------------------------------------------------

def test_the_report_uses_our_record_of_each_answer_and_the_models_judgement():
    wrong = {"claim": "You said Beacon uses a Kafka lock.", "quote": "takes a Postgres advisory lock"}
    report = evaluate(FakeEvaluator(reply(all_reviews(score=1, incorrect_claims=[wrong]))))
    first = report.reviews[0]
    assert (first.topic, first.question, first.answer, first.score) == ("Beacon", ANSWERS[0]["question"], ANSWERS[0]["text"], 1)
    assert [c.claim for c in first.incorrect_claims] == [wrong["claim"]]  # T18's shape: the wrong claim, quoted
    assert report.average_score == round((1 + 3 + 3) / 3, 1) and report.tips == ["a", "b", "c"]


def test_a_point_whose_quote_is_not_in_the_notes_is_dropped_and_counted():
    real = {"point": "You named the lock.", "quote": "Postgres advisory lock"}
    invented = {"point": "You missed the retry budget.", "quote": "retries three times with backoff"}
    report = evaluate(FakeEvaluator(reply(all_reviews(correct_points=[real], missing_points=[invented]))))
    assert [p.point for p in report.reviews[0].correct_points] == ["You named the lock."]
    assert report.reviews[0].missing_points == [] and report.dropped_quotes == 1


def test_a_quote_from_another_topics_notes_does_not_count():
    other_topic = {"point": "You missed the database.", "quote": "stores logs in MongoDB"}
    report = evaluate(FakeEvaluator(reply(all_reviews(missing_points=[other_topic]))))
    assert report.reviews[0].missing_points == [] and report.dropped_quotes == 1


@pytest.mark.parametrize("quote", ["Postgres advisory lock", "postgres ADVISORY lock.", "**Postgres advisory lock**"])
def test_quotes_match_the_notes_whatever_the_case_punctuation_or_markdown(quote):
    assert in_notes(quote, TOPICS[0]["text"])


@pytest.mark.parametrize("quote", ["", "  ", "Redis advisory lock", "lock advisory Postgres"])
def test_empty_reworded_or_reordered_quotes_do_not_match(quote):
    assert not in_notes(quote, TOPICS[0]["text"])


def test_unverifiable_claims_are_kept_without_a_quote():
    report = evaluate(FakeEvaluator(reply(all_reviews(unverifiable_claims=["You said it runs on Kubernetes."]))))
    assert report.reviews[0].unverifiable_claims == ["You said it runs on Kubernetes."]


def test_tips_are_capped_at_three_and_blank_ones_dropped():
    report = evaluate(FakeEvaluator(reply(all_reviews(), tips=["one", " ", "two", "three", "four"])))
    assert report.tips == ["one", "two", "three"]


# --- checking the model's JSON ---------------------------------------------------------------------

def test_a_reply_wrapped_in_a_markdown_fence_is_still_read():
    fake = FakeEvaluator("```json\n" + reply(all_reviews()) + "\n```")
    assert evaluate(fake) is not None and len(fake.calls) == 1


@pytest.mark.parametrize("bad", [
    "not json at all",
    reply([review(1), review(2)]),  # one answer not reviewed
    reply([review(1), review(1), review(3)]),  # an answer reviewed twice
    reply(all_reviews(score=6)),
    reply(all_reviews(correct_points=[{"point": "no quote"}])),
])
def test_an_invalid_reply_is_rejected(bad):
    assert parse_model_report(bad, answer_count=3) is None


def test_an_invalid_reply_gets_one_more_try():
    fake = FakeEvaluator("oops", reply(all_reviews()))
    assert evaluate(fake) is not None and len(fake.calls) == 2


def test_a_failed_model_call_gets_one_more_try():
    fake = FakeEvaluator(RuntimeError("groq is down"), reply(all_reviews()))
    assert evaluate(fake) is not None and len(fake.calls) == 2


def test_two_bad_replies_give_no_report():
    fake = FakeEvaluator("oops", "still not json")
    assert evaluate(fake) is None and len(fake.calls) == 2


# --- the model call's size --------------------------------------------------------------------------

def test_the_evaluator_can_ask_groq_for_a_longer_reply_than_a_spoken_turn():
    fake = llm._client = FakeGroq(chunk("{}"))
    try:
        async def go():
            return [p async for p in llm.stream_text("p", "s", max_tokens=EVALUATOR_MAX_TOKENS)]
        asyncio.run(go())
        assert fake.request["max_completion_tokens"] == EVALUATOR_MAX_TOKENS
        asyncio.run(anext(llm.stream_text("p", "s")))
        assert fake.request["max_completion_tokens"] == llm.MAX_OUTPUT_TOKENS
    finally:
        llm._client = None
