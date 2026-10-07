"""
Small-talk detection for the RAG chat.

Greetings, thanks, and requests for help ("halo", "heloo", "thanks",
"hello can u help me?", "kamu bisa apa?") are not questions about the
meeting, so retrieval would always abstain on them. They are answered here
with a fixed, friendly reply instead: no retrieval, no LLM call.

A message counts as small talk only when every word is a greeting, thanks,
help, or filler word, so "halo, apa keputusan meeting ini?" still goes to RAG.
"""
from __future__ import annotations

import re
from typing import Optional

# Words are compared after collapsing repeated letters ("heloo" -> "helo",
# "haiii" -> "hai"); the vocabularies are collapsed the same way below.
_GREETINGS = {
    "hello", "hi", "hai", "halo", "hei", "hey", "hy", "hola", "yo",
    "pagi", "siang", "sore", "malam", "morning", "afternoon", "evening",
    "assalamualaikum", "salam", "selamat", "good",
}
_THANKS = {
    "thanks", "thank", "thx", "makasih", "terimakasih", "terima", "kasih",
    "tq", "ty", "nuhun",
}
# Asking for help or what the bot can do, without naming a topic.
_HELP = {
    "help", "assist", "bantu", "bantuin", "tolong", "siapa", "who",
}
_FILLER = {
    "can", "could", "would", "will", "u", "me", "i", "please", "pls", "plz",
    "what", "do", "are", "is", "this", "need", "want", "question", "ask",
    "bisa", "dong", "saya", "aku", "kamu", "anda", "mau", "boleh", "apa", "ini",
    "nanya", "tanya", "gak", "ga", "nggak", "nih",
    "you", "so", "much", "ya", "yah", "kak", "min", "bot", "banyak", "sekali",
    "semua", "all", "there", "everyone", "oke", "ok", "okay", "sip", "mantap",
    "wkwk", "hehe", "haha",
}
_MAX_WORDS = 8

_EXAMPLES_ID = (
    "Contoh pertanyaan:\n"
    "- Apa keputusan utama di meeting ini?\n"
    "- Siapa yang bertanggung jawab atas tindak lanjutnya?\n"
    "- Apa saja action item dan tenggatnya?"
)
_EXAMPLES_EN = (
    "Example questions:\n"
    "- What were the main decisions in this meeting?\n"
    "- Who is responsible for the follow-ups?\n"
    "- What are the action items and deadlines?"
)
_ENGLISH_HINTS = {"hello", "hi", "hey", "hy", "hola", "yo", "morning", "afternoon",
                  "evening", "good", "thanks", "thank", "thx", "ty", "you", "so", "much",
                  "all", "there", "everyone", "okay", "help", "assist", "who", "can",
                  "could", "would", "will", "u", "me", "i", "please", "pls", "plz",
                  "what", "do", "are", "is", "this", "need", "want", "question", "ask"}


def _collapse(word: str) -> str:
    return re.sub(r"(.)\1+", r"\1", word)


_GREETINGS, _THANKS, _HELP, _FILLER, _ENGLISH_HINTS = (
    {_collapse(w) for w in vocab}
    for vocab in (_GREETINGS, _THANKS, _HELP, _FILLER, _ENGLISH_HINTS)
)
# "what can you do", "kamu bisa apa": asking about the bot, no help word needed.
_CAPABILITY = re.compile(r"\bwhat can (you|u) do\b|\bbisa apa\b|\bapa yang bisa\b")


def small_talk_reply(query: str) -> Optional[str]:
    """Return a canned reply when `query` is only a greeting, thanks, or help request, else None."""
    words = [_collapse(w) for w in re.findall(r"[a-z]+", query.lower())]
    if not words or len(words) > _MAX_WORDS:
        return None
    known = _GREETINGS | _THANKS | _HELP | _FILLER
    if any(w not in known for w in words):
        return None
    is_thanks = any(w in _THANKS for w in words)
    is_greeting = (any(w in _GREETINGS | _HELP for w in words)
                   or bool(_CAPABILITY.search(" ".join(words))))
    if not (is_thanks or is_greeting):
        return None  # only filler, e.g. "ok"
    english = all(w in _ENGLISH_HINTS for w in words)

    if is_thanks:
        if english:
            return "You're welcome! Feel free to ask anything else about this meeting."
        return "Sama-sama! Silakan tanyakan hal lain tentang isi meeting ini."
    if english:
        return ("Hello! I answer questions based on this meeting's transcript. "
                + _EXAMPLES_EN)
    return ("Halo! Saya menjawab pertanyaan berdasarkan transkrip meeting ini. "
            + _EXAMPLES_ID)
