"""
Unit tests for small-talk routing in the RAG chat.

Run from backend/:  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.small_talk import small_talk_reply  # noqa: E402


@pytest.mark.parametrize("msg", ["halo", "Haiii!", "selamat pagi", "halo kak",
                                 "assalamualaikum", "hai semua"])
def test_indonesian_greetings_get_indonesian_reply(msg):
    reply = small_talk_reply(msg)
    assert reply and reply.startswith("Halo!")


@pytest.mark.parametrize("msg", ["hello", "heloo", "Hi there", "hey", "good morning everyone"])
def test_english_greetings_get_english_reply(msg):
    reply = small_talk_reply(msg)
    assert reply and reply.startswith("Hello!")


@pytest.mark.parametrize("msg,prefix", [("terima kasih", "Sama-sama"), ("makasih ya", "Sama-sama"),
                                        ("thanks!", "You're welcome"),
                                        ("thank you so much", "You're welcome")])
def test_thanks(msg, prefix):
    assert small_talk_reply(msg).startswith(prefix)


@pytest.mark.parametrize("msg,prefix", [("hello can u help me?", "Hello!"),
                                        ("what can you do?", "Hello!"),
                                        ("bisa bantu aku ga?", "Halo!"),
                                        ("kamu bisa apa?", "Halo!")])
def test_help_requests(msg, prefix):
    assert small_talk_reply(msg).startswith(prefix)


@pytest.mark.parametrize("msg", [
    "Apa isu di tiket MR-241?",
    "siapa yang bertanggung jawab?",       # help-like word + real question
    "what can we do about the flu",
    "halo, apa keputusan meeting ini?",   # greeting + real question goes to RAG
    "hello who fixes the login bug",
    "ok",                                  # filler only: not a greeting
    "",
    "Bagaimana resep rendang?",
])
def test_real_questions_are_not_small_talk(msg):
    assert small_talk_reply(msg) is None
