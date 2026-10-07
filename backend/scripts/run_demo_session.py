"""
Run a full demo session against a running MeetRecall stack and collect every
artefact needed for the article and the presentation.

What it does (all through the public API and UI, nothing is mocked):
  1. Uses an existing meeting (--meeting-id) or imports a transcript (--transcript)
  2. Retrieval comparison: every question in the evaluation set through
     fulltext, vector, and hybrid search (no LLM call)
  3. Chat: every question through the RAG chatbot (default mode: hybrid),
     throttled to stay inside the Groq free-tier limits
  4. Labelled evaluation (Hit@k, Recall@k, MRR@k, abstain accuracy) plus an
     alpha sweep for weighted fusion, with charts
  5. Optional screenshots of the Retrieval Lab, AI Chat, and Upload pages

Run it from the host (not inside the container) while `docker compose up` is running:

    pip install requests matplotlib playwright
    python -m playwright install chromium        # once, for screenshots

    python backend/scripts/run_demo_session.py \
        --meeting-id <id from the Hasil page> \
        --eval-set backend/sample_data/retrieval_eval_set.json \
        --screenshots

    # or import the synthetic sample transcript first:
    python backend/scripts/run_demo_session.py \
        --transcript backend/sample_data/sprint_review_portal_mitra.txt \
        --eval-set backend/sample_data/retrieval_eval_set.json --screenshots

Outputs go to demo_results/<timestamp>/ :
    retrieval_compare.md   top-k per method for every question, relevant hits marked
    chat_answers.md        chatbot answers with cited chunks
    evaluation_summary.md  metrics table per method and per question category
    metrics_by_mode.png    Hit@k / Recall@k / MRR@k per method
    alpha_sweep.png        weighted-fusion quality versus alpha
    results.json           everything above in machine-readable form
    screenshots/*.png      when --screenshots is given
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

MODES = ["fulltext", "vector", "hybrid"]
MODE_LABEL = {"fulltext": "Full-text (BM25)", "vector": "Vector (FAISS)", "hybrid": "Hybrid"}


# API helpers

class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.s = requests.Session()

    def _post(self, path: str, timeout: int = 600, **kw):
        try:
            r = self.s.post(f"{self.base}{path}", timeout=timeout, **kw)
        except requests.ConnectionError:
            # a dropped keep-alive connection: retry once on a fresh session
            self.s = requests.Session()
            for v in (kw.get("files") or {}).values():
                if hasattr(v[1], "seek"):
                    v[1].seek(0)
            r = self.s.post(f"{self.base}{path}", timeout=timeout, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def health(self) -> dict:
        return self.s.get(f"{self.base}/health", timeout=10).json()

    def providers(self) -> dict:
        try:
            return self.s.get(f"{self.base}/api/providers", timeout=10).json()
        except Exception:
            return {}

    def transcript(self, meeting_id: str) -> dict:
        r = self.s.get(f"{self.base}/api/transcript/{meeting_id}", timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Meeting {meeting_id} not available ({r.status_code}): {r.text[:200]}")
        return r.json()

    def import_transcript(self, path: Path) -> str:
        with path.open("rb") as f:
            res = self._post("/api/transcript/import", files={"file": (path.name, f, "text/plain")})
        return res["meeting_id"]

    def retrieve(self, meeting_id: str, query: str, top_k: int, settings: dict) -> dict:
        return self._post(f"/api/rag/retrieve/{meeting_id}",
                          json={"query": query, "top_k": top_k, "modes": MODES, **settings})

    def chat(self, meeting_id: str, query: str, top_k: int, settings: dict) -> dict:
        return self._post(f"/api/rag/chat/{meeting_id}",
                          json={"query": query, "top_k": top_k, **settings})

    def evaluate(self, meeting_id: str, cases: list, k: int, settings: dict, modes=None) -> dict:
        return self._post(f"/api/rag/evaluate/{meeting_id}", timeout=1800,
                          json={"cases": cases, "k": k, "modes": modes or MODES, **settings})


def relevant_ids(case: dict, segments: list) -> set:
    """Indices of transcript segments matching the labels (label sanity check only)."""
    ids = set()
    needles = [n.lower() for n in case.get("relevant_text_contains") or []]
    for i, seg in enumerate(segments):
        if needles and any(n in seg["text"].lower() for n in needles):
            ids.add(i)
    return ids


def is_relevant(case: dict, chunk: dict) -> bool:
    """A retrieved chunk is relevant when it contains a label fragment. Chunks span
    several segments, so segment indices cannot be compared with chunk_id."""
    if chunk.get("chunk_id") in (case.get("relevant_chunk_ids") or []):
        return True
    text = chunk.get("text", "").lower()
    return any(n.lower() in text for n in case.get("relevant_text_contains") or [])


# Report writers

def fmt(v, nd=3):
    return "-" if v is None else f"{v:.{nd}f}"


def write_compare_md(path: Path, rows: list, k: int) -> None:
    out = ["# Perbandingan Retrieval per Pertanyaan", "",
           f"Top-{k} per metode. Tanda [v] = chunk memuat fragmen label set evaluasi.", ""]
    for row in rows:
        out += [f"## {row['id']} ({row['category']}): {row['query']}", ""]
        if row.get("expect_no_answer"):
            out += ["_Pertanyaan di luar cakupan (tidak ada chunk relevan)._", ""]
        else:
            labels = row["case"].get("relevant_text_contains") or []
            out += [f"Label relevan: {', '.join(repr(n) for n in labels) or 'tidak ada'}"
                    + ("" if row["label_matched"] else " (tidak cocok dengan segmen mana pun)"), ""]
        for res in row["results"]:
            out.append(f"**{MODE_LABEL.get(res['mode'], res['mode'])}** "
                       f"({res.get('latency_ms', 0):.1f} ms"
                       + (f", ditolak: {res['abstain_reason']}" if res.get("abstained") else "") + ")")
            out.append("")
            out.append("| # | Chunk | Pembicara @ waktu | Skor | Teks |")
            out.append("|---|---|---|---|---|")
            for c in res["chunks"]:
                mark = " [v]" if is_relevant(row["case"], c) else ""
                # a chunk holds several "Speaker: text" lines; keep the table row on one line
                text = c["text"].replace("|", "/").replace("\n", " / ")
                if len(text) > 110:
                    text = text[:107] + "..."
                out.append(f"| {c.get('rank')} | {c.get('chunk_id')}{mark} | {c.get('speaker')} @ "
                           f"{c.get('start_time', 0):.0f}s | {fmt(c.get('score'), 4)} | {text} |")
            out.append("")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_chat_md(path: Path, rows: list) -> None:
    out = ["# Jawaban Chatbot", ""]
    for row in rows:
        r = row["response"]
        out += [f"## {row['id']} ({row['category']}): {row['query']}", "",
                f"Mode: {r.get('retrieval_mode')}, ditolak: {r.get('abstained')}"
                + (f" ({r.get('abstain_reason')})" if r.get("abstained") else "")
                + f", latensi retrieval: {r.get('retrieval_latency_ms', 0):.1f} ms, "
                  f"total: {row['seconds']:.1f} s", "",
                "**Jawaban:**", "", r.get("transcription_summary", "").strip() or "(kosong)", ""]
        if r.get("sources"):
            out.append("**Sumber:**")
            out.append("")
            for s in r["sources"]:
                text = (s.get("text") or "").replace("\n", " / ")
                out.append(f"- [{s.get('speaker')} @ {s.get('start_time', 0):.0f}s] {text}")
            out.append("")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_eval_md(path: Path, result: dict, sweep: list) -> None:
    k = result["k"]
    out = [f"# Hasil Evaluasi Retrieval (k = {k})", "",
           f"Jumlah pertanyaan: {result['n_cases']} ({result['n_answerable']} dapat dijawab, "
           f"{result['n_cases'] - result['n_answerable']} di luar cakupan).",
           f"Konfigurasi: `{json.dumps(result.get('config', {}))}`", "",
           "Metrik peringkat dihitung tanpa ambang penolakan; ambang dinilai lewat akurasi "
           "penolakan (di luar cakupan) dan salah tolak (seharusnya dijawab).", "",
           f"| Metode | Hit@{k} | Recall@{k} | MRR@{k} | Akurasi penolakan | Salah tolak | Latensi (ms) |",
           "|---|---|---|---|---|---|---|"]
    for mode, m in result["summary"].items():
        out.append(f"| {MODE_LABEL.get(mode, mode)} | {fmt(m[f'hit@{k}'])} | {fmt(m[f'recall@{k}'])} | "
                   f"{fmt(m[f'mrr@{k}'])} | {fmt(m.get('abstain_accuracy'))} | "
                   f"{fmt(m.get('false_abstain_rate'))} | {fmt(m.get('avg_latency_ms'), 2)} |")
    cats = sorted({c for m in result["summary"].values() for c in m["by_category"]})
    out += ["", f"## Hit@{k} per kategori", "",
            "| Kategori | n | " + " | ".join(MODE_LABEL.get(m, m) for m in result["summary"]) + " |",
            "|---|---|" + "---|" * len(result["summary"])]
    for cat in cats:
        n = next((m["by_category"][cat]["n"] for m in result["summary"].values()
                  if cat in m["by_category"]), 0)
        vals = [fmt(m["by_category"].get(cat, {}).get(f"hit@{k}")) for m in result["summary"].values()]
        out.append(f"| {cat} | {n} | " + " | ".join(vals) + " |")
    if sweep:
        out += ["", "## Alpha sweep (fusi berbobot, hybrid)", "",
                f"| alpha | Hit@{k} | MRR@{k} |", "|---|---|---|"]
        for r in sweep:
            out.append(f"| {r['alpha']:.2f} | {fmt(r['hit'])} | {fmt(r['mrr'])} |")
    out += ["", "## Pertanyaan yang meleset", ""]
    misses = [r for r in result["per_query"] if r.get("hit") == 0.0]
    out += [f"- [{MODE_LABEL.get(r['mode'], r['mode'])}] {r['id']} ({r['category']}): {r['query']} "
            f"relevan={r['relevant_ids']} diambil={r['retrieved_ids']}" for r in misses] or ["Tidak ada."]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def plot_charts(result: dict, sweep: list, out: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed, charts skipped")
        return
    k = result["k"]
    metrics = [f"hit@{k}", f"recall@{k}", f"mrr@{k}"]
    modes = list(result["summary"])
    colors = ["#94a3b8", "#6366f1", "#0f766e"]
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=160)
    width = 0.8 / len(modes)
    for i, mode in enumerate(modes):
        vals = [result["summary"][mode][m] or 0 for m in metrics]
        xs = [j + (i - (len(modes) - 1) / 2) * width for j in range(len(metrics))]
        bars = ax.bar(xs, vals, width, label=MODE_LABEL.get(mode, mode), color=colors[i % 3])
        ax.bar_label(bars, fmt="%.2f", fontsize=7, padding=2)
    ax.set_xticks(range(len(metrics)), [m.replace("hit", "Hit").replace("recall", "Recall")
                                        .replace("mrr", "MRR") for m in metrics])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Skor")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, ncol=len(modes), loc="upper center", bbox_to_anchor=(0.5, 1.14))
    fig.tight_layout()
    fig.savefig(out / "metrics_by_mode.png")
    plt.close(fig)
    if sweep:
        fig, ax = plt.subplots(figsize=(6, 3.2), dpi=160)
        a = [r["alpha"] for r in sweep]
        ax.plot(a, [r["mrr"] for r in sweep], marker="o", color="#6366f1", label=f"MRR@{k}")
        ax.plot(a, [r["hit"] for r in sweep], marker="s", color="#0f766e", label=f"Hit@{k}")
        ax.set_xlabel("alpha (0 = hanya BM25, 1 = hanya vector)")
        ax.set_ylim(0, 1.05)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(out / "alpha_sweep.png")
        plt.close(fig)


# Screenshots

def take_screenshots(ui: str, meeting_id: str, shots: list, eval_set: Path, out: Path,
                     timeout_s: int) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed, screenshots skipped (pip install playwright)")
        return []
    done = []
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1600}, device_scale_factor=1.5)

        def wait_idle():
            # Streamlit shows a "running" status widget while the script executes
            page.wait_for_timeout(800)
            try:
                page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached",
                                       timeout=timeout_s * 1000)
            except Exception:
                pass
            page.wait_for_timeout(1200)

        def snap(name: str):
            path = out / f"{name}.png"
            main = page.locator('[data-testid="stMain"]')
            try:
                main.screenshot(path=str(path))
            except Exception:
                page.screenshot(path=str(path), full_page=True)
            done.append(str(path))
            print(f"  screenshot: {path.name}")

        for shot in shots:
            try:
                if shot["page"] == "lab":
                    params = {"meeting": meeting_id, "q": shot["query"], "top_k": shot.get("top_k", 5),
                              "fusion": shot.get("fusion", "rrf"), "run": 1}
                    page.goto(f"{ui}/Retrieval_Lab?{urlencode(params)}")
                    page.get_by_text("latensi").first.wait_for(timeout=timeout_s * 1000)
                    wait_idle()
                    snap(shot["name"])
                elif shot["page"] == "chat":
                    params = {"meeting": meeting_id, "q": shot["query"], "mode": shot.get("mode", "hybrid"),
                              "min_score": shot.get("min_score", 0.40), "open_sources": 1,
                              "top_k": shot.get("top_k", 3), "rerank": 1 if shot.get("rerank") else 0}
                    page.goto(f"{ui}/AI_Chat?{urlencode(params)}")
                    page.locator('[data-testid="stChatMessage"]').nth(1).wait_for(timeout=timeout_s * 1000)
                    wait_idle()
                    snap(shot["name"])
                elif shot["page"] == "eval":
                    page.goto(f"{ui}/Retrieval_Lab?{urlencode({'meeting': meeting_id})}")
                    wait_idle()
                    page.get_by_role("tab", name="Evaluasi Berlabel").click()
                    page.wait_for_timeout(800)
                    page.locator('input[type="file"]').last.set_input_files(str(eval_set))
                    page.wait_for_timeout(1500)
                    page.get_by_role("button", name="Jalankan evaluasi").click()
                    page.get_by_text("Ringkasan").first.wait_for(timeout=timeout_s * 1000)
                    wait_idle()
                    snap(shot["name"])
                elif shot["page"] == "upload":
                    page.goto(f"{ui}/Upload")
                    wait_idle()
                    snap(shot["name"])
            except Exception as exc:
                print(f"  screenshot {shot['name']} failed: {exc}")
        browser.close()
    return done


def default_shots(cases: list, min_score: float) -> list:
    """Pick representative questions per category for the screenshots."""
    first = {}
    for c in cases:
        first.setdefault(c.get("category", "umum"), c)
    order = ["kata_kunci", "parafrase", "lintas_bahasa"]
    shots = []
    for i, cat in enumerate(order, start=1):
        if cat in first:
            shots.append({"name": f"{i:02d}_compare_{cat}", "page": "lab", "query": first[cat]["query"]})
    shots.append({"name": "04_eval_tab", "page": "eval"})
    answerable = [c for c in cases if not c.get("expect_no_answer")]
    mixed = first.get("campuran") or (answerable[0] if answerable else None)
    if mixed:
        shots.append({"name": "08_chat_answer", "page": "chat", "query": mixed["query"],
                      "min_score": min_score})
    oos = first.get("di_luar_cakupan")
    if oos:
        shots.append({"name": "09_chat_rejected", "page": "chat", "query": oos["query"],
                      "min_score": max(min_score, 0.40)})
    shots.append({"name": "10_upload_page", "page": "upload"})
    return shots


# Main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8090")
    ap.add_argument("--ui", default="http://localhost:8503")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--meeting-id")
    src.add_argument("--transcript", type=Path, help="import this .txt/.json transcript first")
    ap.add_argument("--eval-set", type=Path, required=True)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--top-k-compare", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=0.40)
    ap.add_argument("--chat-mode", default="hybrid", choices=MODES)
    ap.add_argument("--chat-delay", type=float, default=6.0,
                    help="seconds between chat calls (Groq free tier: about 8K tokens/min)")
    ap.add_argument("--no-chat", action="store_true")
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--screenshots", action="store_true")
    ap.add_argument("--shot-timeout", type=int, default=240)
    ap.add_argument("--out", type=Path, default=Path("demo_results"))
    args = ap.parse_args()

    api = Api(args.api)
    try:
        print("Backend:", api.health())
    except Exception as exc:
        sys.exit(f"Backend not reachable at {args.api}: {exc}")
    prov = api.providers()
    if prov:
        print("LLM backend:", prov.get("llm"))

    meeting_id = args.meeting_id or api.import_transcript(args.transcript)
    segments = api.transcript(meeting_id)["segments"]
    print(f"Meeting {meeting_id}: {len(segments)} segments")

    data = json.loads(args.eval_set.read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    out = args.out / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    settings = {"fusion": "rrf", "rrf_k": 60, "alpha": 0.5, "rerank": False}

    # Label sanity check: every answerable question must match at least one segment
    def label_matched(c: dict) -> bool:
        return bool(c.get("relevant_chunk_ids")) or bool(relevant_ids(c, segments))

    unmatched = [c["id"] for c in cases if not c.get("expect_no_answer") and not label_matched(c)]
    if unmatched:
        print(f"WARNING: labels match no segment for {unmatched}; check relevant_text_contains")

    # 1. Retrieval comparison
    print("Retrieval comparison ...")
    compare_rows = []
    for c in cases:
        res = api.retrieve(meeting_id, c["query"], args.top_k_compare, settings)
        compare_rows.append({**{k: c.get(k) for k in ("id", "query", "category", "expect_no_answer")},
                             "case": c, "label_matched": label_matched(c),
                             "results": res["results"]})
    write_compare_md(out / "retrieval_compare.md", compare_rows, args.top_k_compare)

    # 2. Chat
    chat_rows = []
    if not args.no_chat:
        print(f"Chat ({args.chat_mode}, {len(cases)} questions, {args.chat_delay}s apart) ...")
        for i, c in enumerate(cases):
            t0 = time.time()
            try:
                r = api.chat(meeting_id, c["query"], args.k,
                             {**settings, "retrieval_mode": args.chat_mode,
                              "min_score": args.min_score, "expand_neighbors": 1})
            except Exception as exc:
                r = {"transcription_summary": f"ERROR: {exc}", "sources": []}
            chat_rows.append({"id": c.get("id"), "query": c["query"], "category": c.get("category"),
                              "seconds": time.time() - t0, "response": r})
            print(f"  {c.get('id')}: {time.time() - t0:.1f}s")
            if i < len(cases) - 1:
                time.sleep(args.chat_delay)
        write_chat_md(out / "chat_answers.md", chat_rows)

    # 3. Evaluation and alpha sweep
    print("Evaluation ...")
    evaluation = api.evaluate(meeting_id, cases, args.k, {**settings, "min_score": args.min_score})
    sweep = []
    if not args.no_sweep:
        answerable = [c for c in cases if not c.get("expect_no_answer")]
        for alpha in [0.0, 0.25, 0.5, 0.75, 1.0]:
            r = api.evaluate(meeting_id, answerable, args.k,
                             {**settings, "fusion": "weighted", "alpha": alpha, "min_score": 0.0},
                             modes=["hybrid"])
            s = r["summary"]["hybrid"]
            sweep.append({"alpha": alpha, "hit": s[f"hit@{args.k}"], "mrr": s[f"mrr@{args.k}"]})
    write_eval_md(out / "evaluation_summary.md", evaluation, sweep)
    plot_charts(evaluation, sweep, out)

    # 4. Screenshots
    shots_taken = []
    if args.screenshots:
        print("Screenshots ...")
        shots_taken = take_screenshots(args.ui.rstrip("/"), meeting_id,
                                       default_shots(cases, args.min_score),
                                       args.eval_set.resolve(), out / "screenshots", args.shot_timeout)

    (out / "results.json").write_text(json.dumps({
        "meeting_id": meeting_id, "n_segments": len(segments), "providers": prov,
        "unmatched_labels": unmatched, "compare": compare_rows, "chat": chat_rows,
        "evaluation": evaluation, "alpha_sweep": sweep, "screenshots": shots_taken,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Results in {out.resolve()}")


if __name__ == "__main__":
    main()
