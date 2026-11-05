"""
Fixes decided after the evaluation of 2026-10-07 to 2026-10-10 (document 09, sections 8 and 25):
  1. U+2011 (non-breaking hyphen) no longer loses its glyph in the PDF.
  2. Item ids follow the order in which things were said (A1 is the earliest).
  3. Prompt rules 7 and 12 no longer contradict each other: ambiguous owner or deadline does not hold back a task request.

Reuses the fakes of test_agent.py (no API key, no model).
Run from backend/:  python -m pytest tests/test_perbaikan_senin.py -q
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent import (ACTION_ITEMS, MID, FakeStorage, ScriptedLLM, completion, fake_retrieve,  # noqa: E402,F401
                        tmp_dirs)
from agent.llm_client import ChatClient  # noqa: E402
from agent.loop import SYSTEM_PROMPT  # noqa: E402
from agent.tools import ToolContext, execute_tool  # noqa: E402
from agent.tracing import Tracer  # noqa: E402


def extract(items):
    llm = ChatClient(create=ScriptedLLM(completion(json.dumps({"items": items}))))
    ctx = ToolContext(tracer=Tracer(MID), llm=llm, storage=FakeStorage(), retrieve=fake_retrieve,
                      meeting_id=MID, user_message=None)
    out = execute_tool("ekstrak_poin_meeting", json.dumps({"meeting_id": MID, "jenis": "action_items"}), ctx)
    assert out["status"] == "ok", out
    return ctx, out["rekap_id"]


def test_item_ids_follow_the_order_in_which_things_were_said():
    early, late = ACTION_ITEMS["items"][0], ACTION_ITEMS["items"][1]      # said at 00:10 and 00:50
    ctx, rekap_id = extract([late, early])                                # the model lists them in reverse order
    items = ctx.rekaps.load(rekap_id)["bagian"]["action_items"]["items"]
    assert [i["id"] for i in items] == ["A1", "A2"]
    assert items[0]["isi"] == early["isi"] and items[1]["isi"] == late["isi"]
    assert items[0]["mulai"] < items[1]["mulai"]


def test_ids_already_stored_never_change_when_a_later_batch_is_added():
    early, late = ACTION_ITEMS["items"][0], ACTION_ITEMS["items"][1]
    ctx, rekap_id = extract([late])
    rekap = ctx.rekaps.load(rekap_id)
    assert [i["id"] for i in rekap["bagian"]["action_items"]["items"]] == ["A1"]
    added = ctx.rekaps.add_items(rekap, "action_items", [dict(early, mulai="00:10", kutipan=early["kutipan"])], None)
    assert [i["id"] for i in added] == ["A2"]                              # numbering continues; A1 stays the later item
    assert ctx.rekaps.load(rekap_id)["bagian"]["action_items"]["items"][0]["isi"] == late["isi"]


def test_pdf_keeps_a_non_breaking_hyphen_instead_of_dropping_it(caplog):
    item = dict(ACTION_ITEMS["items"][0], isi="Menyiapkan dokumen MR‑230 untuk 11‑13 Oktober")
    ctx, rekap_id = extract([item])
    with caplog.at_level(logging.WARNING):
        out = execute_tool("ekspor_laporan", json.dumps({"rekap_id": rekap_id, "formats": ["pdf"],
                                                         "izinkan_bagian_kosong": True}), ctx)
    assert out["status"] == "ok" and Path(out["files"][0]["path"]).read_bytes()[:4] == b"%PDF"
    assert not [r for r in caplog.records if "glyph" in r.getMessage().lower()], "PDF font still lacks a glyph"


def test_prompt_rules_7_and_12_agree_that_ambiguity_does_not_block_a_task_request():
    rule7 = SYSTEM_PROMPT.split("7. ", 1)[1].split("8. ", 1)[0]
    rule12 = SYSTEM_PROMPT.split("12. ", 1)[1].split("13. ", 1)[0]
    assert "minta user mengonfirmasi" not in SYSTEM_PROMPT and "minta user mengonfirmasi" not in rule7
    assert "diisi user saat persetujuan" in rule7 and "jangan menahan atau menolak" in rule7
    assert "tenggat tidak jelas tetap diajukan ke buat_task" in rule12 and "mengisi keduanya saat persetujuan" in rule12
    assert "jangan mengarang" in rule7                                       # still never invents an owner or a deadline
