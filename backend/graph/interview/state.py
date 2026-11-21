"""state.py: the per-session state of the interview graph (v2 design, "System flow").

Persisted per session by the checkpointer (thread_id = session_id):
    topics, profile_summary, glossary, messages, persona, topic_index, level, followups_used, last_question, started_at, finished, answers
Reset at the start of every turn by the interview ingest node:
    intent, mode, route, decisions, pending_answer, final_text, decision, tag_ok, errors, interrupted_reply,
    nudge, nudge_index, corrections

The topics are stored here, not in the graph: each candidate gets their own plan, so one compiled
graph serves every session. The server sends them as an input with every turn.

Only messages has a reducer (add_messages), as in graph/state.py: every other field is replaced
by what a node returns, so ingest's empty values really reset it.
"""

from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from backend.interview.plan import Topic


class Answer(TypedDict):
    """One graded candidate answer: the evaluator (C4) reads these. Clarifications are never stored."""

    topic_id: str
    question: str  # the interviewer's question as it was asked
    text: str  # the candidate's answer, after glossary normalisation
    corrections: NotRequired[dict[str, str]]  # heard -> glossary term, only when code corrected a term


class InterviewState(TypedDict, total=False):
    query: str  # input: the candidate's committed turn; "" asks for the opening question
    interrupted_reply: str  # input: heard part of the interviewer's last turn after a barge-in
    ui_action: dict | None  # input: sent by the shared runner; cards do not exist in interviews, so it is ignored
    visitor_timezone: str  # input: sent by the shared runner; unused by the interview
    nudge: int | None  # input: the candidate stayed silent; which nudge to say (interview/personas.py)
    persona: str  # input on the first turn: "neutral" or "strict" (interview/personas.py); persisted
    topics: list[Topic]  # input with every turn: this session's plan, in order; persisted
    profile_summary: str  # input: a short summary of the candidate's resume; persisted
    glossary: list[str]  # input: every tech name from the resume and JD, for mis-heard terms; persisted
    messages: Annotated[list[AnyMessage], add_messages]
    topic_index: int  # which topic of the plan is being discussed
    level: int  # rung of the current topic's follow-up ladder, 1 up to its max_level (prompt.py LADDERS)
    followups_used: int  # follow-up questions asked on the current topic; its seed question is not one
    started_at: float  # clock time of the first turn, for the time cap
    finished: bool  # the closing line was spoken; every later turn gets it again
    answers: list[Answer]  # every answer so far, recorded only when its turn completes
    last_question: str  # the interviewer's last spoken turn, replayed on "repeat that" without the LLM
    intent: str  # this turn: answer, repeat, hint, rephrase, skip, end, "start" for the opening, or "nudge"; an answer becomes hint when the model labels it hint_request
    nudge_index: int | None  # this turn's nudge, copied from the input so the input can be cleared
    mode: str  # what the interviewer model does: answer, hint or rephrase (prompt.py)
    route: str  # the steer node's choice: interviewer, move, repeat, close or nudge; "steer" when the interviewer hands a hint request back
    decisions: list[str]  # what the model may choose after this answer (pacing.py); set by steer
    corrections: dict[str, str]  # this turn's glossary corrections, heard -> term (interview/glossary.py)
    pending_answer: Answer | None  # this turn's answer, moved into answers once the turn completes
    final_text: str  # what the interviewer said this turn (tag removed)
    decision: str  # the model's control-tag decision this turn; "next" when the tag was missing
    tag_ok: bool  # the model wrote a valid control tag this turn (an eval metric)
    errors: list[str]
