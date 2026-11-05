"""
Deterministic guardrails: quote verification, owner/deadline ambiguity,
prompt-injection flags in transcript text, and input checks.
None of these call an LLM.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# Normalisation

_SPEAKER_PREFIX = re.compile(r"(?m)^\s*[^:\n]{1,40}:\s+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    return " ".join(_NON_WORD.sub(" ", (text or "").lower()).split())


def strip_speakers(chunk_text: str) -> str:
    """Remove the 'Speaker N: ' prefix that chunking adds to every line."""
    return _SPEAKER_PREFIX.sub("", chunk_text or "")


# Quote verification

MIN_QUOTE_WORDS = 3


def _squash_repeats(normalized: str) -> str:
    """'and and and do' -> 'and do': ASR keeps stutters that people and models drop when quoting."""
    out: List[str] = []
    for word in normalized.split():
        if not out or word != out[-1]:
            out.append(word)
    return " ".join(out)


def quote_in_text(quote: str, text: str) -> bool:
    """True when the quote (at least MIN_QUOTE_WORDS words) occurs in text, ignoring case,
    punctuation and immediately repeated words."""
    q = _squash_repeats(normalize(quote))
    if len(q.split()) < MIN_QUOTE_WORDS:
        return False
    return f" {q} " in f" {_squash_repeats(normalize(strip_speakers(text)))} "


MIN_SNAP_WORDS = 4
SNAP_THRESHOLD = 0.8


def _tok(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def _collapse(tokens: Sequence[str]) -> List[str]:
    """Drop empty tokens and immediate repeats ('I I I'll' -> 'I'll'), the usual ASR stutter."""
    out: List[str] = []
    for t in tokens:
        if t and (not out or t != out[-1]):
            out.append(t)
    return out


def snap_quote(quote: str, text: str) -> Optional[str]:
    """
    Models tidy spoken language: they drop stutters ("I I I'll" -> "I'll") or
    expand contractions. The exact-substring check then rejects a real
    commitment. This finds the transcript span that matches the quote after
    ignoring repeated words and punctuation (similarity >= SNAP_THRESHOLD, same
    first and last words region) and returns that span verbatim, so what the
    report shows is always the speaker's own words. None when nothing matches.
    """
    from difflib import SequenceMatcher

    q = _collapse(_tok(w) for w in (quote or "").split())
    if len(q) < MIN_SNAP_WORDS:
        return None
    words = strip_speakers(text).split()
    toks = [_tok(w) for w in words]
    best_ratio, best_span = 0.0, None
    for size in range(max(len(q) - 1, MIN_SNAP_WORDS), len(q) + 6):
        for start in range(0, len(words) - size + 1):
            window = _collapse(toks[start:start + size])
            if not window or window[0] not in q[:3] or window[-1] not in q[-3:]:
                continue
            ratio = SequenceMatcher(None, q, window, autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio, best_span = ratio, (start, size)
    if best_span is None or best_ratio < SNAP_THRESHOLD:
        return None
    start, size = best_span
    return " ".join(words[start:start + size])


def find_segment(quote: str, segments: Sequence, start: float, end: float):
    """
    The transcript segment inside [start, end] where the quote begins, for a
    precise timestamp and speaker. Returns None when not found (the caller
    falls back to the chunk span).
    """
    q_words = normalize(quote).split()
    if not q_words:
        return None
    head = " ".join(q_words[: min(4, len(q_words))])
    window = [s for s in segments if s.end_time >= start - 0.01 and s.start_time <= end + 0.01]
    for seg in window:
        if f" {head} " in f" {normalize(seg.text)} ":
            return seg
    # Quote may start in one segment and continue in the next.
    for a, b in zip(window, window[1:]):
        if f" {head} " in f" {normalize(a.text + ' ' + b.text)} ":
            return a
    return None


# Owner and deadline ambiguity

_GROUP_WORDS = {
    "kita", "kami", "tim", "semua", "semuanya", "bersama", "kalian", "mereka", "seseorang",
    "we", "us", "team", "everyone", "everybody", "all", "someone", "they", "somebody",
}
_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[/.-]\d{1,2}([/.-]\d{2,4})?\b"
    r"|\b\d{1,2}\s+(jan|feb|mar|apr|mei|may|jun|jul|agu|aug|sep|okt|oct|nov|des|dec)[a-z]*\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(st|nd|rd|th)?\b",
    re.IGNORECASE,
)


# First-person commitment ("I will", "saya akan"). Only then is the speaker who
# said it the owner; someone who proposes or asks is not automatically the one doing it.
_SELF_COMMIT = re.compile(
    r"\b(i will|i'll|i am going to|i'm going to|let me|i can|i'll be"
    r"|saya akan|aku akan|saya yang|biar saya|nanti saya|saya siap)\b",
    re.IGNORECASE,
)
_GROUP_COMMIT = re.compile(r"\b(let's|let us|we will|we'll|kita akan|mari kita|ayo kita|kita harus)\b",
                           re.IGNORECASE)


def owner_status(owner: str, chunk_text: str, speakers: Iterable[str],
                 quote: str = "", quote_speaker: str = "") -> str:
    """
    'jelas' when the owner is
      - a name that appears in the cited chunk (e.g. addressed: "Jason, can you ..."), or
      - the speaker label of the person who made a first-person commitment in the quote.
    'ambigu' for empty, group words ("kita", "team"), several people, names not in
    the chunk, group commitments ("let's ..."), or a speaker label that only proposed
    or asked for something.
    """
    o = (owner or "").strip()
    if not o:
        return "ambigu"
    if re.search(r",|/|&|\bdan\b|\band\b|\batau\b|\bor\b", o, re.IGNORECASE):
        return "ambigu"
    if normalize(o) in _GROUP_WORDS:
        return "ambigu"
    if o in set(speakers):
        if quote and (o != quote_speaker or _GROUP_COMMIT.search(quote) or not _SELF_COMMIT.search(quote)):
            return "ambigu"
        return "jelas"
    return "jelas" if f" {normalize(o)} " in f" {normalize(chunk_text)} " else "ambigu"


def deadline_status(deadline: str, chunk_text: str) -> str:
    """'tidak_disebut', 'tidak_terverifikasi' (not in the chunk), 'jelas' (explicit date) or 'relatif'."""
    d = (deadline or "").strip()
    if not d:
        return "tidak_disebut"
    if f" {normalize(d)} " not in f" {normalize(chunk_text)} ":
        return "tidak_terverifikasi"
    return "jelas" if _DATE_RE.search(d) else "relatif"


# Prompt injection flags in transcript text

_INJECTION_RE = re.compile(
    r"ignore (all |the )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (all |the )?(previous|prior|above)"
    r"|abaikan (semua |seluruh )?(instruksi|perintah|aturan)"
    r"|(you are|kamu adalah|anda adalah) (now )?(an? )?(ai|assistant|asisten|chatgpt)"
    r"|system prompt|prompt sistem"
    r"|(kirim|send|forward|teruskan)\b.{0,40}(email|e-mail|surel)\b.{0,40}\bke\b"
    r"|(send|forward)\b.{0,40}\bto\b.{0,40}@"
    r"|[\w.+-]+@[\w-]+\.[\w.]+"
    r"|<\s*/?\s*(system|assistant|tool|transkrip_data)\s*>",
    re.IGNORECASE,
)


def injection_flags(text: str) -> List[str]:
    return [m.group(0)[:80] for m in _INJECTION_RE.finditer(text or "")]


# Final answer check

# A quotation never spans a line break or a table cell border; without that, the text between the
# closing quote of one table cell and the opening quote of the next was mistaken for a quote.
_QUOTED = re.compile(r"[\"“]([^\"“”\n|]{12,400})[\"”]")


def is_name_not_quote(passage: str, names: Sequence[str]) -> bool:
    """True when a quoted passage is a name the system knows (the meeting title, or a file named after it), not
    something said in the meeting. Such names are not in the transcript and must not be checked against it."""
    p = normalize(passage)
    return any(n and (p == n or p.startswith(n + " ")) for n in (normalize(x) for x in names))


def quoted_passages(answer: str, names: Sequence[str] = ()) -> List[str]:
    """Passages the answer puts in quotation marks (long enough to be a quote, not a short term, not a known name)."""
    return [m.group(1) for m in _QUOTED.finditer(answer or "")
            if len(normalize(m.group(1)).split()) >= MIN_QUOTE_WORDS and not is_name_not_quote(m.group(1), names)]


# Quote location and attribution: where a quote really is in the transcript, and whether the "(Speaker, mm:ss)" the
# model wrote after it matches. Pure functions over the transcript segments; the model's attribution is never trusted.

MAX_QUOTE_SPAN = 6        # a quote may run over at most this many consecutive segments
TIME_TOLERANCE_S = 5.0    # claimed time may be this far outside the real segment and still count as right
_ATTR = re.compile(r"[ \t]*\(([^()\n]{2,80})\)")
_TS = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def locate_quote(quote: str, segments: Sequence) -> List[Dict]:
    """Every place the quote occurs: the shortest run of consecutive segments containing it, starting in the first
    segment. Each hit: {speakers (in order), start, end}. Same matching rules as quote_in_text."""
    q = _squash_repeats(normalize(quote))
    if len(q.split()) < MIN_QUOTE_WORDS:
        return []
    norms = [_squash_repeats(normalize(strip_speakers(s.text))) for s in segments]
    hits = []
    for i in range(len(segments)):
        for j in range(i, min(i + MAX_QUOTE_SPAN, len(segments))):
            run = _squash_repeats(" ".join(norms[i:j + 1]))
            if f" {q} " not in f" {run} ":
                continue
            tail = _squash_repeats(" ".join(norms[i + 1:j + 1]))
            if j > i and f" {q} " in f" {tail} ":
                break   # the quote starts in a later segment; that start is found on its own
            speakers = list(dict.fromkeys(s.speaker for s in segments[i:j + 1]))
            hits.append({"speakers": speakers, "start": segments[i].start_time, "end": segments[j].end_time})
            break
    return hits


def _seconds(m: Tuple[str, str, str]) -> int:
    a, b, c = m
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def _attribution_ok(claimed: str, hit: Dict, labels: Sequence[str]) -> bool:
    """A claim is checked only for what it states: a speaker label of this meeting, and/or timestamps. A name that
    is not a label (the transcript only has labels) or no speaker at all is not judged."""
    named = {l for l in labels if re.search(rf"(?<!\w){re.escape(l)}(?!\w)", claimed, re.IGNORECASE)}
    speaker_ok = not named or bool(named & set(hit["speakers"]))
    times = [_seconds(m) for m in _TS.findall(claimed)]
    time_ok = not times or (min(times) <= hit["end"] + TIME_TOLERANCE_S and max(times) >= hit["start"] - TIME_TOLERANCE_S)
    return speaker_ok and time_ok


def check_attribution(answer: str, segments: Sequence, fmt_ts: Callable[[float], str],
                      names: Sequence[str] = ()) -> Tuple[str, List[Dict]]:
    """Locate each quote of the answer and fix a wrong "(Speaker, time)" written right after it.
    Returns (answer with wrong attributions replaced, one record per quote). A record: kutipan, ditemukan, and when
    found speaker, mulai, selesai, ditulis (what the model wrote, or None), dikoreksi (it was wrong), dirapikan (it was
    right but a wider range than the quote, narrowed), ambigu (occurs more than once)."""
    labels = sorted({s.speaker for s in segments})
    edits, records = [], []
    for m in _QUOTED.finditer(answer or ""):
        q = m.group(1)
        if len(normalize(q).split()) < MIN_QUOTE_WORDS or is_name_not_quote(q, names):
            continue
        hits = locate_quote(q, segments)
        if not hits:
            records.append({"kutipan": q[:200], "ditemukan": False})
            continue
        am = _ATTR.match(answer, m.end())
        claimed = am.group(1) if am else None
        chosen, fixed, tidied = hits[0], False, False
        if claimed is not None:
            ok = [h for h in hits if _attribution_ok(claimed, h, labels)]
            if ok:
                chosen = ok[0]
                times = [_seconds(t) for t in _TS.findall(claimed)]
                if len(times) >= 2 and (abs(min(times) - chosen["start"]) > TIME_TOLERANCE_S
                                        or abs(max(times) - chosen["end"]) > TIME_TOLERANCE_S):
                    # right speaker and the quote lies inside the range, but the range is wider than the quote
                    # (typically the whole chunk): narrow it so the answer and the reference say the same thing.
                    tidied = True
                    edits.append((am.start(1) - 1, am.end(), f"({' dan '.join(chosen['speakers'])}, "
                                                              f"{fmt_ts(chosen['start'])}-{fmt_ts(chosen['end'])})"))
            else:
                times = [_seconds(t) for t in _TS.findall(claimed)]
                if times:   # several occurrences: correct to the one nearest the time the model gave
                    chosen = min(hits, key=lambda h: abs(h["start"] - times[0]))
                fixed = True
                edits.append((am.start(1) - 1, am.end(), f"({' dan '.join(chosen['speakers'])}, "
                                                          f"{fmt_ts(chosen['start'])}-{fmt_ts(chosen['end'])})"))
        records.append({"kutipan": q[:200], "ditemukan": True, "speaker": " dan ".join(chosen["speakers"]),
                        "mulai": fmt_ts(chosen["start"]), "selesai": fmt_ts(chosen["end"]), "ditulis": claimed,
                        "dikoreksi": fixed, "dirapikan": tidied, "ambigu": len(hits) > 1})
    for start, end, text in reversed(edits):
        answer = answer[:start] + text + answer[end:]
    return answer, records


def unverified_quotes(answer: str, transcript_text: str, names: Sequence[str] = ()) -> List[str]:
    """Quoted passages in the final answer that are not in the transcript."""
    out = []
    for m in _QUOTED.finditer(answer or ""):
        q = m.group(1)
        if (len(normalize(q).split()) >= MIN_QUOTE_WORDS and not is_name_not_quote(q, names)
                and not quote_in_text(q, transcript_text)):
            out.append(q[:120])
    return out


# Input checks

def check_input(message: str, meeting_info, max_chars: int) -> Optional[str]:
    """Reason to reject the request before any LLM call, or None."""
    if not message or not message.strip():
        return "pesan_kosong"
    if len(message) > max_chars:
        return "pesan_terlalu_panjang"
    if meeting_info is None:
        return "meeting_tidak_ditemukan"
    if meeting_info.status != "completed":
        return "meeting_belum_selesai_diproses"
    return None


# Scope: a short list of requests that are clearly not about a meeting. Kept
# narrow on purpose (false positives block real questions); everything else is
# left to the system prompt, and the evaluation set measures both.
_OUT_OF_SCOPE = [
    ("kode_program", re.compile(
        r"\b(tulis|tuliskan|buatkan|write|generate)\b.{0,20}\b(python|javascript|java|sql|html|css)\b"
        r"|\b(kode|code|script|program)\s+(python|javascript|java|sql|html|css)\b", re.IGNORECASE)),
    ("cuaca", re.compile(r"\b(cuaca|weather|prakiraan hujan)\b", re.IGNORECASE)),
    ("harga_aset", re.compile(r"\bharga\s+(saham|bitcoin|kripto|crypto|emas)\b"
                              r"|\b(stock|bitcoin|crypto)\s+price\b", re.IGNORECASE)),
    ("hiburan", re.compile(r"\b(resep|recipe|puisi|pantun|lelucon|poem|joke)\b", re.IGNORECASE)),
]


def out_of_scope(message: str) -> Optional[str]:
    """Category name when the request is clearly unrelated to a meeting, else None."""
    for name, pattern in _OUT_OF_SCOPE:
        if pattern.search(message or ""):
            return name
    return None


# Write intent: a write tool may only be requested when the user's own message
# in this turn asks for that kind of action. Text in the transcript never counts.
_WRITE_INTENT = {
    "buat_task": re.compile(r"\b(task|tasks|tugas|todo|to-do|tiket|ticket|jira|buat|buatkan|bikin|create|catat)\b",
                            re.IGNORECASE),
    "kirim_email_rekap": re.compile(r"\b(kirim|kirimkan|email|e-mail|surel|send|mail)\b", re.IGNORECASE),
}


def write_intent(tool: str, user_message: Optional[str]) -> bool:
    pattern = _WRITE_INTENT.get(tool)
    if pattern is None or user_message is None:
        return True
    return bool(pattern.search(user_message))


def wrap_transcript(text: str) -> str:
    """Transcript text handed to the LLM, marked as data. Closing tags inside are neutralised."""
    safe = re.sub(r"<\s*/?\s*transkrip_data\s*>", "[tag dihapus]", text or "", flags=re.IGNORECASE)
    return f"<transkrip_data>\n{safe}\n</transkrip_data>"


def summarize_flags(texts: Dict[int, str]) -> Dict[int, List[str]]:
    return {k: f for k, v in texts.items() if (f := injection_flags(v))}
