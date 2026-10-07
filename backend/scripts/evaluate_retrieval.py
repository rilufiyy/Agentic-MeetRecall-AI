"""
Offline retrieval experiment: full-text vs vector vs hybrid on a labelled set.

Runs without the API server and without audio. The transcript is parsed,
indexed into FAISS + BM25 under a fixed experiment meeting id, and every
question in the evaluation set is run through each retrieval mode.

Usage (from the backend/ directory, or inside the backend container):

    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --k 5 --min-score 0.40
    python scripts/evaluate_retrieval.py --fusion weighted --alpha 0.7
    python scripts/evaluate_retrieval.py --alpha-sweep
    python scripts/evaluate_retrieval.py --rerank

Docker:
    docker compose exec backend python scripts/evaluate_retrieval.py --alpha-sweep

Outputs (in --out, default results/retrieval_eval/):
    summary.md          metrics table per mode and per question category
    results.json        full results including per-query rankings
    metrics_by_mode.png grouped bar chart (only if matplotlib is installed)
    alpha_sweep.png     MRR vs alpha for weighted fusion (with --alpha-sweep)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.retrieval_eval import run_evaluation  # noqa: E402
from services.transcript_import import parse_transcript  # noqa: E402
from services.vector_store import vector_store  # noqa: E402

MODES = ["fulltext", "vector", "hybrid"]
MODE_LABEL = {"fulltext": "Full-text (BM25)", "vector": "Vector (FAISS)", "hybrid": "Hybrid"}


def build_index(transcript_path: Path, meeting_id: str) -> int:
    segments, _ = parse_transcript(transcript_path.read_text(encoding="utf-8"))
    return vector_store.index_segments(meeting_id, segments)


def to_markdown(result: dict) -> str:
    k = result["k"]
    lines = [
        f"# Hasil Evaluasi Retrieval (k = {k})",
        "",
        f"Jumlah pertanyaan: {result['n_cases']} "
        f"({result['n_answerable']} dapat dijawab, "
        f"{result['n_cases'] - result['n_answerable']} di luar cakupan).",
        f"Konfigurasi: `{json.dumps(result['config'])}`",
        "",
        "Metrik peringkat dihitung tanpa ambang penolakan; ambang (min_score) dinilai terpisah "
        "lewat akurasi penolakan (pertanyaan di luar cakupan) dan salah tolak (pertanyaan yang "
        "seharusnya bisa dijawab).",
        "",
        f"| Mode | Hit@{k} | Recall@{k} | MRR@{k} | Akurasi penolakan | Salah tolak | Latensi rata-rata (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    fmt = lambda v: "-" if v is None else f"{v:.3f}"
    for mode, m in result["summary"].items():
        lines.append(
            f"| {MODE_LABEL.get(mode, mode)} | {fmt(m[f'hit@{k}'])} | {fmt(m[f'recall@{k}'])} | "
            f"{fmt(m[f'mrr@{k}'])} | {fmt(m['abstain_accuracy'])} | {fmt(m['false_abstain_rate'])} | "
            f"{fmt(m['avg_latency_ms'])} |"
        )
    cats = sorted({c for m in result["summary"].values() for c in m["by_category"]})
    lines += ["", f"## Hit@{k} per kategori pertanyaan", "",
              "| Kategori | n | " + " | ".join(MODE_LABEL.get(m, m) for m in result["summary"]) + " |",
              "|---|---|" + "---|" * len(result["summary"])]
    for cat in cats:
        row = [cat]
        n = next((m["by_category"][cat]["n"] for m in result["summary"].values()
                  if cat in m["by_category"]), 0)
        row.append(str(n))
        for m in result["summary"].values():
            row.append(fmt(m["by_category"].get(cat, {}).get(f"hit@{k}")))
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Pertanyaan yang gagal (relevan tidak muncul di top-k)", ""]
    misses = [r for r in result["per_query"] if r["hit"] == 0.0]
    if not misses:
        lines.append("Tidak ada.")
    for r in misses:
        lines.append(f"- [{MODE_LABEL.get(r['mode'], r['mode'])}] {r['id']} ({r['category']}): "
                     f"{r['query']}  relevan={r['relevant_ids']} diambil={r['retrieved_ids']}")
    return "\n".join(lines) + "\n"


def plot_by_mode(result: dict, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    k = result["k"]
    metrics = [f"hit@{k}", f"recall@{k}", f"mrr@{k}"]
    modes = list(result["summary"])
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    width = 0.8 / len(modes)
    colors = ["#94a3b8", "#6366f1", "#0f766e"]
    for i, mode in enumerate(modes):
        vals = [result["summary"][mode][m] or 0 for m in metrics]
        xs = [j + (i - (len(modes) - 1) / 2) * width for j in range(len(metrics))]
        bars = ax.bar(xs, vals, width, label=MODE_LABEL.get(mode, mode), color=colors[i % 3])
        ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
    ax.set_xticks(range(len(metrics)), [m.upper().replace("@", "@") for m in metrics])
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Skor")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, ncol=len(modes), loc="upper center",
              bbox_to_anchor=(0.5, 1.12))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def plot_alpha_sweep(rows: list, k: int, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(6, 3.2), dpi=150)
    alphas = [r["alpha"] for r in rows]
    ax.plot(alphas, [r[f"mrr@{k}"] for r in rows], marker="o", color="#6366f1", label=f"MRR@{k}")
    ax.plot(alphas, [r[f"hit@{k}"] for r in rows], marker="s", color="#0f766e", label=f"Hit@{k}")
    ax.set_xlabel("alpha (0 = hanya BM25, 1 = hanya vector)")
    ax.set_ylim(0, 1.05)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--transcript", default=str(BACKEND_DIR / "sample_data/sprint_review_portal_mitra.txt"))
    p.add_argument("--eval-set", default=str(BACKEND_DIR / "sample_data/retrieval_eval_set.json"))
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--fusion", choices=["rrf", "weighted"], default="rrf")
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--rrf-k", type=int, default=60)
    p.add_argument("--candidate-k", type=int, default=20)
    p.add_argument("--min-score", type=float, default=0.40,
                   help="cosine threshold for abstention (0 disables)")
    p.add_argument("--rerank", action="store_true")
    p.add_argument("--alpha-sweep", action="store_true")
    p.add_argument("--out", default=str(BACKEND_DIR / "results/retrieval_eval"))
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meeting_id = "experiment-" + Path(args.transcript).stem
    n = build_index(Path(args.transcript), meeting_id)
    cases = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))["cases"]
    print(f"Indexed {n} chunks, {len(cases)} evaluation questions.\n")

    base = {"fusion": args.fusion, "alpha": args.alpha, "rrf_k": args.rrf_k,
            "candidate_k": args.candidate_k, "rerank": args.rerank, "min_score": args.min_score}
    result = run_evaluation(meeting_id, cases, MODES, args.k, base)

    md = to_markdown(result)
    print(md)
    (out / "summary.md").write_text(md, encoding="utf-8")
    (out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if plot_by_mode(result, out / "metrics_by_mode.png"):
        print(f"Chart: {out / 'metrics_by_mode.png'}")

    if args.alpha_sweep:
        rows = []
        answerable = [c for c in cases if not c.get("expect_no_answer")]
        for alpha in [0.0, 0.25, 0.5, 0.75, 1.0]:
            r = run_evaluation(meeting_id, answerable, ["hybrid"], args.k,
                               {**base, "fusion": "weighted", "alpha": alpha, "min_score": 0.0})
            s = r["summary"]["hybrid"]
            rows.append({"alpha": alpha, f"hit@{args.k}": s[f"hit@{args.k}"],
                         f"mrr@{args.k}": s[f"mrr@{args.k}"]})
        print("\nAlpha sweep (weighted fusion):")
        for row in rows:
            print(f"  alpha={row['alpha']:.2f}  Hit@{args.k}={row[f'hit@{args.k}']:.3f}  "
                  f"MRR@{args.k}={row[f'mrr@{args.k}']:.3f}")
        (out / "alpha_sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        if plot_alpha_sweep(rows, args.k, out / "alpha_sweep.png"):
            print(f"Chart: {out / 'alpha_sweep.png'}")


if __name__ == "__main__":
    main()
