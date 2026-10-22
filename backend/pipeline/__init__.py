"""Pipeline package."""
from .sentence import extract_next_sentence, extract_sentences
from .barge_in import BargeIn
from .answer_turn import answer_turn, speak_sentence

__all__ = [
    "extract_next_sentence",
    "extract_sentences",
    "BargeIn",
    "answer_turn",
    "speak_sentence",
]
