"""
Offline retrieval evaluation: compare full-text, vector, and hybrid search on a
labelled question set.

Each evaluation case is a dict:
  {
    "id": "q01",
    "query": "Siapa yang pegang tiket MR-218?",
    "category": "kata_kunci",              # free label, used for the breakdown
    "relevant_text_contains": ["MR-218"],  # a segment is relevant if its text
                                           # contains any of these (case-insensitive)
    "relevant_chunk_ids": [],              # optional explicit ids
    "expect_no_answer": false              # true = question is not covered by
                                           # the meeting; ideal behaviour is abstain
  }

Labelling by text fragment instead of chunk_id keeps the set valid when the
same meeting is re-transcribed and segment boundaries shift slightly.

Metrics (answerable cases only, computed on the top-k results):
  - Hit@k    : share of questions with at least one relevant segment in top-k
  - Recall@k : share of all relevant segments that appear in top-k (averaged)
  - MRR@k    : mean of 1 / rank of the first relevant segment (0 if none)
Ranking metrics are computed with the abstention threshold switched off, so
they measure retrieval quality alone. The threshold (min_score) is then
evaluated separately:
  - Abstain accuracy   : share of expect_no_answer questions that were rejected
  - False abstain rate : share of answerable questions that were wrongly
                         rejected by the same threshold
Both are only meaningful when min_score > 0.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

from services.retrieval import RetrievalConfig, retrieval_service


def relevant_ids(case: Dict, chunks: List[Dict]) -> set:
    ids = set(case.get("relevant_chunk_ids") or [])
    needles = [n.lower() for n in case.get("relevant_text_contains") or []]
    if needles:
        for c in chunks:
            text = c["text"].lower()
            if any(n in text for n in needles):
                ids.add(c["chunk_id"])
    return ids


def evaluate_ranking(retrieved: Sequence[int], relevant: set) -> Dict[str, float]:
    hit, rr = 0.0, 0.0
    for rank, d in enumerate(retrieved, start=1):
        if d in relevant:
            hit, rr = 1.0, 1.0 / rank
            break
    recall = len(relevant.intersection(retrieved)) / len(relevant) if relevant else 0.0
    return {"hit": hit, "recall": recall, "rr": rr}


def run_evaluation(
    meeting_id: str,
    cases: List[Dict],
    modes: Sequence[str] = ("fulltext", "vector", "hybrid"),
    k: int = 3,
    base_config: Dict | None = None,
) -> Dict:
    """Run every case through every mode and aggregate the metrics."""
    chunks = retrieval_service._chunks(meeting_id)
    if not chunks:
        raise ValueError(f"No index for meeting {meeting_id}")

    base_config = dict(base_config or {})
    summary, per_query = {}, []
    for mode in modes:
        agg = defaultdict(list)
        by_cat: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        latencies: List[float] = []
        min_score = float(base_config.get("min_score", 0.0) or 0.0)
        for case in cases:
            cfg = RetrievalConfig(**{**base_config, "mode": mode, "top_k": k})
            # Threshold decision (used for both case types)
            gated = retrieval_service.retrieve(meeting_id, case["query"], cfg)
            row = {
                "id": case.get("id", ""),
                "query": case["query"],
                "category": case.get("category", "umum"),
                "mode": mode,
                "abstained": gated.abstained,
            }
            if case.get("expect_no_answer"):
                latencies.append(gated.latency_ms)
                ok = 1.0 if gated.abstained else 0.0
                agg["abstain"].append(ok)
                row.update({"retrieved_ids": [c["chunk_id"] for c in gated.chunks],
                            "relevant_ids": [], "hit": None, "recall": None,
                            "rr": None, "abstain_ok": ok})
            else:
                if min_score > 0:
                    agg["false_abstain"].append(1.0 if gated.abstained else 0.0)
                # Pure ranking quality: same config with the threshold off
                cfg.min_score = 0.0
                outcome = retrieval_service.retrieve(meeting_id, case["query"], cfg)
                latencies.append(outcome.latency_ms)
                retrieved = [c["chunk_id"] for c in outcome.chunks]
                rel = relevant_ids(case, chunks)
                m = evaluate_ranking(retrieved, rel)
                for key, val in m.items():
                    agg[key].append(val)
                    by_cat[row["category"]][key].append(val)
                row.update({"retrieved_ids": retrieved, "relevant_ids": sorted(rel),
                            **m, "abstain_ok": None})
            per_query.append(row)

        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
        summary[mode] = {
            f"hit@{k}": mean(agg["hit"]),
            f"recall@{k}": mean(agg["recall"]),
            f"mrr@{k}": mean(agg["rr"]),
            "abstain_accuracy": mean(agg["abstain"]),
            "false_abstain_rate": mean(agg["false_abstain"]),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "by_category": {
                cat: {f"hit@{k}": mean(v["hit"]), f"mrr@{k}": mean(v["rr"]), "n": len(v["hit"])}
                for cat, v in sorted(by_cat.items())
            },
        }
    return {
        "meeting_id": meeting_id,
        "k": k,
        "n_cases": len(cases),
        "n_answerable": sum(1 for c in cases if not c.get("expect_no_answer")),
        "config": base_config,
        "summary": summary,
        "per_query": per_query,
    }
