"""
Full-text (lexical) search over transcript segments using Okapi BM25.

Why BM25 next to FAISS?
  Dense embeddings match on meaning, so they handle paraphrased questions well,
  but they often miss exact tokens that carry little "semantic" signal:
  ticket codes (MR-218), version numbers (v2.4.1), names, and acronyms.
  BM25 scores documents by exact term overlap, weighted by how rare the term
  is (IDF) and normalised by document length, so it covers exactly that gap.

Design notes:
  - One in-memory index per meeting, built from the same chunk list FAISS uses,
    so chunk_id values are shared between the lexical and the dense index.
  - No stemming: the tokenizer lowercases, keeps codes such as "mr-218" or
    "v2.4.1" intact (plus their parts), and drops common ID + EN stopwords.
    This keeps the behaviour transparent for the retrieval experiments.
  - Nothing is persisted: building BM25 for a few hundred segments takes
    milliseconds, so the index is rebuilt lazily from the FAISS metadata.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence

# Stopwords (Indonesian + English, conversational fillers included)
_STOPWORDS = {
    # Indonesian
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "untuk", "dengan", "pada",
    "adalah", "akan", "juga", "atau", "ada", "tidak", "ga", "gak", "nggak",
    "enggak", "sudah", "udah", "belum", "bisa", "karena", "jadi", "kalau",
    "kalo", "saya", "aku", "kami", "kita", "kamu", "anda", "dia", "mereka",
    "nya", "lah", "kah", "pun", "sih", "dong", "deh", "ya", "iya", "oke", "ok",
    "nah", "tadi", "lagi", "masih", "sama", "dalam", "oleh", "saat", "sebagai",
    "apa", "siapa", "kapan", "mana", "bagaimana", "gimana", "berapa", "kenapa",
    "mengapa", "apakah", "tentang", "soal", "terus", "habis", "biar", "agar",
    "seperti", "kayak", "hanya", "cuma", "baru", "harus", "perlu", "mau",
    "ingin", "punya", "buat", "bikin", "hal", "para", "semua", "setiap",
    "antara", "bahwa", "tapi", "tetapi", "namun", "lalu", "kemudian",
    "dibahas", "disebut", "bilang", "katanya", "meeting", "rapat",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "can", "could", "should",
    "this", "that", "these", "those", "it", "its", "we", "you", "they", "he",
    "she", "i", "me", "my", "our", "your", "their", "in", "on", "at", "to",
    "for", "of", "and", "or", "but", "with", "from", "by", "as", "if", "so",
    "not", "no", "yes", "what", "who", "when", "where", "how", "which", "why",
    "about", "um", "uh", "yeah", "okay", "right", "well",
}

# A token is a run of letters/digits that may be joined by - . _ /
# e.g. "mr-218", "v2.4.1", "p95", "on-call"
_TOKEN_RE = re.compile(r"[0-9a-z]+(?:[-._/][0-9a-z]+)*")


def tokenize(text: str) -> List[str]:
    """Lowercase, split into tokens, keep compound codes and their parts."""
    tokens: List[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        raw = raw.strip("._-/")
        if not raw:
            continue
        parts = [p for p in re.split(r"[-._/]", raw) if p]
        if len(parts) > 1:
            tokens.append(raw)                     # exact code, e.g. "mr-218"
            tokens.extend(p for p in parts if p not in _STOPWORDS and len(p) > 1)
        elif raw not in _STOPWORDS and len(raw) > 1:
            tokens.append(raw)
    return tokens


class BM25Index:
    """Okapi BM25 over a fixed list of documents (transcript segments)."""

    def __init__(self, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_tokens: List[List[str]] = [tokenize(d) for d in documents]
        self.doc_freqs: List[Counter] = [Counter(t) for t in self.doc_tokens]
        self.doc_len: List[int] = [len(t) for t in self.doc_tokens]
        self.n_docs = len(documents)
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

        df: Counter = Counter()
        for tokens in self.doc_tokens:
            df.update(set(tokens))
        # BM25 IDF with +1 inside the log so it never becomes negative
        self.idf: Dict[str, float] = {
            term: math.log((self.n_docs - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }

    def score(self, query_tokens: Sequence[str], doc_idx: int) -> float:
        freqs = self.doc_freqs[doc_idx]
        dl = self.doc_len[doc_idx] or 1
        norm = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
        total = 0.0
        for term in set(query_tokens):
            tf = freqs.get(term, 0)
            if tf:
                total += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / (tf + norm)
        return total

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """Return [{doc_idx, score, matched_terms}] for docs with score > 0."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        q_set = set(q_tokens)
        hits = []
        for idx in range(self.n_docs):
            s = self.score(q_tokens, idx)
            if s > 0:
                matched = sorted(q_set.intersection(self.doc_freqs[idx]))
                hits.append({"doc_idx": idx, "score": s, "matched_terms": matched})
        hits.sort(key=lambda h: -h["score"])
        return hits[:top_k]
