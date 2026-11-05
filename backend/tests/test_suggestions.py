from agent.approvals import ApprovalStore
from agent.guardrails import normalize
from agent.suggestions import suggest

QUOTE_1, QUOTE_2 = "I will send the budget draft on Friday", "someone should check the vendor contract"


def item(id_, quote, owner="jelas", deadline="jelas"):
    return {"id": id_, "isi": quote, "kutipan": quote, "status_penanggung_jawab": owner, "status_tenggat": deadline}


def rekap(action_items, kinds=("ringkasan", "keputusan", "isu_terbuka")):
    bagian = {k: {"status": "ok", "items": [item("X1", f"{k} satu dua tiga")]} for k in kinds}
    bagian["action_items"] = {"status": "ok", "items": action_items}
    return {"rekap_id": "r1", "meeting_id": "m1", "bagian": bagian}


def ids(result):
    return [s["id"] for s in result]


def test_no_rekap_means_no_suggestions():
    assert suggest(None, [], {}, []) == []


def test_untasked_action_items_are_offered_and_unclear_ones_are_counted():
    r = rekap([item("A1", QUOTE_1), item("A2", QUOTE_2, owner="ambigu", deadline="tidak_disebut")])
    out = suggest(r, [], {}, [])
    task = next(s for s in out if s["id"] == "task")
    assert "2 action item" in task["teks"] and "1 di antaranya" in task["teks"]
    assert task["prompt"] == "Buatkan task untuk semua action items"


def test_wording_when_every_item_is_unclear():
    r = rekap([item("A1", QUOTE_1, deadline="tidak_disebut"), item("A2", QUOTE_2, owner="ambigu")])
    task = next(s for s in suggest(r, [], {}, []) if s["id"] == "task")
    assert "Semuanya belum jelas" in task["teks"] and "di antaranya" not in task["teks"]


def test_items_that_are_already_tasks_are_not_offered_again():
    r = rekap([item("A1", QUOTE_1)])
    assert "task" not in ids(suggest(r, [], {normalize(QUOTE_1): "T1"}, []))


def test_pending_task_approval_hides_the_task_suggestion():
    r = rekap([item("A1", QUOTE_1)])
    assert "task" not in ids(suggest(r, [], {}, [{"tool": "buat_task", "status": "menunggu"}]))


def test_report_is_offered_only_when_the_recap_is_complete_and_nothing_was_exported():
    r = rekap([item("A1", QUOTE_1)])
    assert "laporan" in ids(suggest(r, [], {}, []))
    assert "laporan" not in ids(suggest(r, [{"format": "pdf"}], {}, []))
    partial = rekap([item("A1", QUOTE_1)], kinds=("ringkasan",))
    assert "laporan" not in ids(suggest(partial, [], {}, []))


def test_email_is_offered_for_a_ready_report_until_it_is_requested_or_sent():
    r = rekap([item("A1", QUOTE_1)])
    out = suggest(r, [{"format": "pdf"}, {"format": "srt"}], {}, [])
    email = next(s for s in out if s["id"] == "email")
    assert email["prompt"] == "Kirim laporan pdf ke email saya"          # srt is never mailed
    assert "email" not in ids(suggest(r, [{"format": "srt"}], {}, []))   # nothing mailable yet
    for status in ("menunggu", "diproses", "dieksekusi"):
        assert "email" not in ids(suggest(r, [{"format": "pdf"}], {}, [{"tool": "kirim_email_rekap", "status": status}]))
    assert "email" in ids(suggest(r, [{"format": "pdf"}], {}, [{"tool": "kirim_email_rekap", "status": "ditolak"}]))


def test_every_suggestion_prompt_passes_the_write_intent_guardrail():
    from agent import guardrails
    r = rekap([item("A1", QUOTE_1)])
    for s in suggest(r, [{"format": "pdf"}], {}, []):
        tool = {"task": "buat_task", "email": "kirim_email_rekap"}.get(s["id"])
        assert tool is None or guardrails.write_intent(tool, s["prompt"])


def test_store_lists_approvals_of_one_rekap(tmp_path):
    store = ApprovalStore(tmp_path / "a.db")
    a = store.create("tr1", "m1", "r1", "kirim_email_rekap", {}, {})
    store.create("tr2", "m1", "r2", "buat_task", {}, {})
    assert [x["approval_id"] for x in store.for_rekap("r1")] == [a]
