"""WhatsApp task capture: the acceptance list from the handoff (signature, dedupe,
off-topic, AI disclosure, STOP, 24h window, quote-reply done, batching, Health,
purge, no phone numbers to the AI) plus linking, cards, reminders and limits."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import types
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import claude_client
import whatsapp
import whatsapp_ai

SECRET = "test-app-secret"
KOLKATA = ZoneInfo("Asia/Kolkata")
WA = "919845012345"


# --- fixtures -------------------------------------------------------------------

@pytest.fixture()
def env(monkeypatch):
    for k, v in {"WA_PHONE_NUMBER_ID": "123", "WA_ACCESS_TOKEN": "tok", "WA_APP_SECRET": SECRET,
                 "WA_VERIFY_TOKEN": "verify-me", "WA_DISPLAY_NUMBER": "+91 80000 00000"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(whatsapp, "AUTO_PROCESS", False)


@pytest.fixture()
def clock(monkeypatch):
    c = {"now": datetime(2026, 11, 20, 4, 30, tzinfo=timezone.utc)}      # 10:00 in Kolkata
    monkeypatch.setattr(whatsapp, "_now", lambda: c["now"])
    return c


@pytest.fixture()
def sent(monkeypatch):
    out = []

    def fake_post(payload):
        out.append(payload)
        return {"messages": [{"id": f"wamid.out{len(out)}"}]}
    monkeypatch.setattr(whatsapp, "post_graph", fake_post)
    return out


class FakeClaude:
    """Stands in for the API: records what Hymn sends and answers from a script."""

    def __init__(self):
        self.calls = []
        self.script = {}           # substring → TaskParse fields
        self.fail_first = False

    def parse_for(self, text):
        for key, fields in sorted(self.script.items(), key=lambda kv: -len(kv[0])):
            if key in text:
                base = {"is_task": True, "title": "", "due_date": "", "due_time": "", "due_confidence": 0.9,
                        "area": "", "people": [], "confidence": 0.9}
                return whatsapp_ai.TaskParse(**{**base, **fields})
        return whatsapp_ai.TaskParse(is_task=False, title="", due_date="", due_time="", due_confidence=0,
                                     area="", people=[], confidence=0.95)

    async def parse(self, **kw):
        self.calls.append(kw)
        if self.fail_first:
            self.fail_first = False
            whatsapp_ai.TaskParse.model_validate({})          # raises ValidationError, like bad JSON
        text = kw["messages"][0]["content"]
        return types.SimpleNamespace(parsed_output=self.parse_for(text), stop_reason="end_turn",
                                     usage=types.SimpleNamespace(input_tokens=500, output_tokens=40,
                                                                 cache_read_input_tokens=400))


@pytest.fixture()
def ai(monkeypatch):
    fake = FakeClaude()
    client = types.SimpleNamespace(with_options=lambda **kw: client,
                                   beta=types.SimpleNamespace(messages=types.SimpleNamespace(parse=fake.parse)))
    monkeypatch.setattr(claude_client, "get_client", lambda: client)
    return fake


@pytest.fixture()
def db(server):
    asyncio.run(whatsapp.ensure_whatsapp_indexes(server.db))
    return server.db


# --- helpers ----------------------------------------------------------------------

_n = {"i": 0}


def _msg(text="", *, wa=WA, wamid=None, reply_id=None, button=None, context=None):
    _n["i"] += 1
    m = {"from": wa, "id": wamid or f"wamid.in{_n['i']}", "timestamp": "0"}
    if reply_id:
        m.update({"type": "interactive", "interactive": {"type": "button_reply",
                                                         "button_reply": {"id": reply_id, "title": text or "x"}}})
    elif button:
        m.update({"type": "button", "button": {"payload": button, "text": text or "Done"}})
    else:
        m.update({"type": "text", "text": {"body": text}})
    if context:
        m["context"] = context
    return m


def _post(client, *messages, secret=SECRET, raw=None):
    body = raw or json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp", "messages": list(messages)}}]}]}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/whatsapp/webhook", content=body,
                       headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})


def _run(db, clock, wa=WA, seconds=11):
    clock["now"] += timedelta(seconds=seconds)
    asyncio.run(whatsapp.process_due(db, wa, clock["now"]))


def _say(client, db, clock, *messages, wa=WA):
    assert _post(client, *messages).status_code == 200
    _run(db, clock, wa)


def _texts(sent):
    out = []
    for p in sent:
        if p["type"] == "text":
            out.append(p["text"]["body"])
        elif p["type"] == "interactive":
            out.append(p["interactive"]["body"]["text"])
    return out


def _buttons(p):
    return [(b["reply"]["id"], b["reply"]["title"]) for b in p["interactive"]["action"]["buttons"]]


def _signup(client, email="wa@example.com"):
    b = client.post("/api/auth/signup", json={"name": "Asha", "email": email, "password": "correct-horse-battery",
                                              "security_question": "Q?", "security_answer": "A"}).json()
    return b["user"]["id"], {"Authorization": f"Bearer {b['access_token']}"}


@pytest.fixture()
def linked(client, db, env, clock, sent):
    uid, h = _signup(client)
    asyncio.run(db.users.update_one({"id": uid}, {"$set": {"timezone": "Asia/Kolkata"}}))
    r = client.post("/api/whatsapp/link", headers=h, json={"consent": True})
    assert r.status_code == 200, r.text
    assert r.json()["url"] == f"https://wa.me/918000000000?text={r.json()['code']}"
    _say(client, db, clock, _msg(r.json()["code"]))
    sent.clear()
    return {"id": uid, "h": h}


def _tasks(db, uid):
    return asyncio.run(db.tasks.find({"user_id": uid}, {"_id": 0}).to_list(length=None))


def _add_task(client, db, clock, sent, ai, text, title, due="2026-11-21", due_time=""):
    ai.script[text] = {"title": title, "due_date": due, "due_time": due_time}
    _say(client, db, clock, _msg(text))
    card = sent[-1]
    add = next(i for i, t in _buttons(card) if t == "Add")
    _say(client, db, clock, _msg("Add", reply_id=add))
    return card


# --- acceptance tests ----------------------------------------------------------------

def test_bad_signature_is_refused_and_nothing_is_stored(client, db, env, clock, sent):
    r = _post(client, _msg("Pay rent"), secret="wrong-secret")
    assert r.status_code == 401
    assert asyncio.run(db.wa_inbound.count_documents({})) == 0
    r = client.post("/api/whatsapp/webhook", content=b"{}")                   # no signature at all
    assert r.status_code == 401


def test_the_same_webhook_twice_makes_one_task(client, db, linked, clock, sent, ai):
    ai.script["electricity"] = {"title": "Pay electricity bill", "due_date": "2026-11-21"}
    m = _msg("Pay the electricity bill tomorrow", wamid="wamid.dup1")
    _post(client, m)
    _post(client, m)                                                           # Meta retries
    _run(db, clock)
    assert asyncio.run(db.wa_inbound.count_documents({"wamid": "wamid.dup1"})) == 1
    assert len(ai.calls) == 1 and len(sent) == 1
    add = _buttons(sent[0])[0][0]
    tap = _msg("Add", reply_id=add, wamid="wamid.tap1")
    _post(client, tap)
    _post(client, tap)
    _run(db, clock)
    assert [t["title"] for t in _tasks(db, linked["id"])] == ["Pay electricity bill"]


def test_off_topic_always_gets_the_fixed_reply(client, db, linked, clock, sent, ai):
    for i in range(50):
        _say(client, db, clock, _msg(f"What's the capital of France? Tell me a joke #{i}"))
    replies = _texts(sent)
    assert len(replies) == 50
    assert all(r.split("\n\n")[0] == whatsapp.OFF_TOPIC for r in replies)
    assert not _tasks(db, linked["id"])
    assert all(c["output_format"] is whatsapp_ai.TaskParse for c in ai.calls)   # only ever asked to extract


def test_ai_disclosure_once_per_new_24h_window(client, db, linked, clock, sent, ai):
    # Linking opened the window and the "Connected" reply carried the line.
    _say(client, db, clock, _msg("hello?"))
    assert whatsapp.DISCLOSURE not in _texts(sent)[-1]                       # same window: not repeated
    clock["now"] += timedelta(hours=25)
    _say(client, db, clock, _msg("anyone there?"))
    assert _texts(sent)[-1].endswith(whatsapp.DISCLOSURE)                    # new window: shown again
    _say(client, db, clock, _msg("hmm"))
    assert whatsapp.DISCLOSURE not in _texts(sent)[-1]


def test_the_connected_reply_discloses_ai(client, db, env, clock, sent):
    uid, h = _signup(client, "link@example.com")
    code = client.post("/api/whatsapp/link", headers=h, json={"consent": True}).json()["code"]
    _say(client, db, clock, _msg(f"Hi! {code}"))
    assert _texts(sent)[-1].startswith("Connected.") and _texts(sent)[-1].endswith(whatsapp.DISCLOSURE)
    logs = asyncio.run(db.consent_log.find({"user_id": uid}, {"_id": 0}).to_list(length=None))
    assert [l["method"] for l in logs] == ["app_checkbox", "app_checkbox_then_whatsapp_code"]
    assert client.get("/api/whatsapp", headers=h).json()["number"] == "•••• 2345"


def test_stop_means_no_more_messages_of_any_kind(client, db, linked, clock, sent, ai):
    _add_task(client, db, clock, sent, ai, "Call the plumber", "Call the plumber", due="2026-11-20")
    sent.clear()
    _say(client, db, clock, _msg("STOP"))
    _say(client, db, clock, _msg("Pay rent on Friday"))
    _say(client, db, clock, _msg("help"))
    clock["now"] = datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc) + timedelta(hours=1)   # past 09:00 IST
    asyncio.run(whatsapp.send_reminders(db, clock["now"]))
    assert sent == []
    assert asyncio.run(whatsapp.send_text(db, WA, "anything", now=clock["now"])) is None   # the send guard itself
    assert sent == []
    assert client.get("/api/whatsapp", headers=linked["h"]).json()["paused"] is True
    _say(client, db, clock, _msg("START"))
    assert _texts(sent)[-1].startswith("You're back on.")


def test_the_app_switch_stops_messages_too(client, db, linked, clock, sent, ai):
    assert client.post("/api/whatsapp/pause", headers=linked["h"], json={"paused": True}).json()["paused"] is True
    _say(client, db, clock, _msg("Pay rent on Friday"))
    assert sent == [] and ai.calls == []
    client.post("/api/whatsapp/pause", headers=linked["h"], json={"paused": False})
    _say(client, db, clock, _msg("hello"))
    assert len(sent) == 1


def test_free_form_outside_the_24h_window_is_blocked(client, db, linked, clock, sent):
    clock["now"] += timedelta(hours=25)
    assert asyncio.run(whatsapp.send_text(db, WA, "Hi there", now=clock["now"])) is None
    assert sent == []


def test_quote_reply_done_on_card_3_closes_only_task_3(client, db, linked, clock, sent, ai):
    cards = [_add_task(client, db, clock, sent, ai, f"Task number {i}", f"Task {i}") for i in range(1, 6)]
    third_card_wamid = asyncio.run(db.wa_outbound.find_one(
        {"kind": "card", "task_id": {"$ne": None}}, {"_id": 0}, skip=2, sort=[("sent_at", 1)]))["wamid"]
    _say(client, db, clock, _msg("done", context={"id": third_card_wamid}))
    status = {t["title"]: t["status"] for t in _tasks(db, linked["id"])}
    assert status == {"Task 1": "todo", "Task 2": "todo", "Task 3": "done", "Task 4": "todo", "Task 5": "todo"}
    assert len(cards) == 5


def test_three_forwards_within_5_seconds_make_one_card(client, db, linked, clock, sent, ai):
    ai.script["Venue"] = {"title": "Book the venue", "due_date": "2026-11-25"}
    for i, text in enumerate(("From Priya: Venue options attached", "Need to confirm by Tuesday", "Budget 2L")):
        _post(client, _msg(text, context={"forwarded": True}))
        clock["now"] += timedelta(seconds=2)
    _run(db, clock, seconds=0)                    # last one only 2s old: still waiting
    assert sent == [] and ai.calls == []
    _run(db, clock)
    assert len(ai.calls) == 1 and len(sent) == 1
    assert "Need to confirm by Tuesday" in ai.calls[0]["messages"][0]["content"]
    assert "Book the venue" in _texts(sent)[0]


def test_health_goes_to_the_app_and_nothing_is_kept(client, db, linked, clock, sent, ai):
    ai.script["BP"] = {"title": "Check BP", "area": "health"}
    _say(client, db, clock, _msg("Check my BP tomorrow morning", wamid="wamid.health"))
    assert "Health" in _texts(sent)[-1] and "app" in _texts(sent)[-1]
    assert not _tasks(db, linked["id"])
    assert asyncio.run(db.wa_drafts.count_documents({})) == 0
    assert "raw_text" not in asyncio.run(db.wa_inbound.find_one({"wamid": "wamid.health"}, {"_id": 0}))


def test_raw_text_older_than_7_days_is_purged(client, db, linked, clock, sent, ai):
    _say(client, db, clock, _msg("just saying hi", wamid="wamid.old"))
    asyncio.run(whatsapp.purge(db, clock["now"] + timedelta(days=6)))
    assert asyncio.run(db.wa_inbound.find_one({"wamid": "wamid.old"}))["raw_text"] == "just saying hi"
    asyncio.run(whatsapp.purge(db, clock["now"] + timedelta(days=7, minutes=1)))
    doc = asyncio.run(db.wa_inbound.find_one({"wamid": "wamid.old"}, {"_id": 0}))
    assert "raw_text" not in doc and doc["wamid"] == "wamid.old"            # the id stays for dedupe


def test_no_phone_numbers_reach_the_ai(client, db, linked, clock, sent, ai):
    _say(client, db, clock, _msg("Call Ravi on +91 98450 12345 or 080-2345 6789 about the 2 tickets on 25/11"))
    payload = json.dumps([c["messages"] for c in ai.calls] + [c["system"] for c in ai.calls])
    assert not re.search(r"\d[\d\s().-]{5,}\d", payload.replace("2026-11-20", ""))
    assert "[number]" in payload and "2 tickets" in payload and WA not in payload
    assert whatsapp_ai.redact("PIN 560001") == "PIN 560001"                 # short numbers stay


# --- the flows around them --------------------------------------------------------------

def test_unlinked_numbers_get_a_connect_link_and_nothing_is_created(client, db, env, clock, sent, ai):
    _say(client, db, clock, _msg("Pay rent", wa="910000011111"), wa="910000011111")
    assert "isn't connected" in _texts(sent)[0]
    assert ai.calls == [] and asyncio.run(db.tasks.count_documents({})) == 0


def test_link_needs_consent_and_codes_expire(client, db, env, clock, sent):
    uid, h = _signup(client, "consent@example.com")
    assert client.post("/api/whatsapp/link", headers=h, json={"consent": False}).status_code == 400
    code = client.post("/api/whatsapp/link", headers=h, json={"consent": True}).json()["code"]
    clock["now"] += timedelta(minutes=31)
    _say(client, db, clock, _msg(code))
    assert "expired" in _texts(sent)[-1]
    assert not client.get("/api/whatsapp", headers=h).json()["linked"]


def test_no_date_asks_with_buttons_and_a_picked_date_is_used(client, db, linked, clock, sent, ai):
    ai.script["passport"] = {"title": "Renew passport"}
    _say(client, db, clock, _msg("renew passport"))
    assert [t for _, t in _buttons(sent[-1])] == ["Today", "Tomorrow", "Pick date"]
    pick = _buttons(sent[-1])[2][0]
    _say(client, db, clock, _msg("Pick date", reply_id=pick))
    rows = sent[-1]["interactive"]["action"]["sections"][0]["rows"]
    assert len(rows) == 10 and rows[0]["title"] == "Today" and all(len(r["title"]) <= 24 for r in rows)
    _say(client, db, clock, _msg(rows[4]["title"], reply_id=rows[4]["id"]))
    [t] = _tasks(db, linked["id"])
    assert t["title"] == "Renew passport" and t["due_date"] == "2026-11-24" and t["source"] == "whatsapp"
    assert sent[-1]["type"] == "reaction" and sent[-1]["reaction"]["emoji"] == "✅"


def test_edit_and_cancel(client, db, linked, clock, sent, ai):
    ai.script["gas"] = {"title": "Book gas", "due_date": "2026-11-21"}
    _say(client, db, clock, _msg("book gas"))
    edit = next(i for i, t in _buttons(sent[-1]) if t == "Edit")
    _say(client, db, clock, _msg("Edit", reply_id=edit))
    ai.script["cylinder"] = {"title": "Book gas cylinder", "due_date": "2026-11-22"}
    _say(client, db, clock, _msg("book gas cylinder on saturday"))
    assert "Book gas cylinder" in _texts(sent)[-1]
    _say(client, db, clock, _msg("Edit", reply_id=edit))                        # the old card is gone
    assert "already handled" in _texts(sent)[-1]
    cancel = next(i for i, t in _buttons(sent[-2]) if t == "Cancel")
    _say(client, db, clock, _msg("Cancel", reply_id=cancel))
    assert _texts(sent)[-1] == "Okay, not added." and not _tasks(db, linked["id"])


def test_low_confidence_asks_to_rephrase(client, db, linked, clock, sent, ai):
    ai.script["thing"] = {"title": "Thing", "confidence": 0.4}
    _say(client, db, clock, _msg("that thing we discussed"))
    assert _texts(sent)[-1] == whatsapp.NOT_UNDERSTOOD
    assert asyncio.run(db.wa_drafts.count_documents({})) == 0


def test_reminder_at_due_time_then_done_and_snooze_buttons(client, db, linked, clock, sent, ai):
    _add_task(client, db, clock, sent, ai, "pay rent at 5pm", "Pay rent", due="2026-11-20", due_time="17:00")
    _add_task(client, db, clock, sent, ai, "call bank", "Call bank", due="2026-11-20")      # 09:00 default
    sent.clear()
    at = lambda hhmm: datetime(2026, 11, 20, *map(int, hhmm.split(":")), tzinfo=KOLKATA).astimezone(timezone.utc)
    assert asyncio.run(whatsapp.send_reminders(db, at("16:59"))) == 1       # the bank one (09:00, caught up)
    assert asyncio.run(whatsapp.send_reminders(db, at("17:00"))) == 1       # rent, exactly at 5 pm
    assert asyncio.run(whatsapp.send_reminders(db, at("17:01"))) == 0       # one reminder per task
    t = sent[-1]["template"]
    assert t["name"] == "task_due_reminder"
    assert [p["text"] for p in t["components"][0]["parameters"]] == ["Pay rent", "today at 5 pm"]
    payloads = [c["parameters"][0]["payload"] for c in t["components"][1:]]
    rent = next(x for x in _tasks(db, linked["id"]) if x["title"] == "Pay rent")
    assert payloads == [f"done:{rent['id']}", f"snooze:{rent['id']}"]
    clock["now"] = at("17:02")
    _say(client, db, clock, _msg("Snooze 1 day", button=payloads[1]))
    rent = next(x for x in _tasks(db, linked["id"]) if x["title"] == "Pay rent")
    assert rent["due_date"] == "2026-11-21" and rent["status"] == "todo" and rent["wa_reminded_at"] is None
    _say(client, db, clock, _msg("Done", button=payloads[0]))
    assert next(x for x in _tasks(db, linked["id"]) if x["title"] == "Pay rent")["status"] == "done"


def test_bare_done_and_done_with_words(client, db, linked, clock, sent, ai):
    _add_task(client, db, clock, sent, ai, "pay electricity", "Pay electricity bill")
    _say(client, db, clock, _msg("done"))                                       # only one recent: closes it
    assert [t["status"] for t in _tasks(db, linked["id"])] == ["done"]
    _add_task(client, db, clock, sent, ai, "buy milk", "Buy milk")
    _add_task(client, db, clock, sent, ai, "call priya", "Call Priya about the venue")
    _say(client, db, clock, _msg("done"))                                       # two: which one?
    rows = sent[-1]["interactive"]["action"]["sections"][0]["rows"]
    assert sorted(r["title"] for r in rows) == ["Buy milk", "Call Priya about the ve…"]
    assert all(len(r["title"]) <= 24 for r in rows)
    assert next(r for r in rows if r["title"] != "Buy milk")["description"] == "Call Priya about the venue"
    _say(client, db, clock, _msg("done priya venue"))
    status = {t["title"]: t["status"] for t in _tasks(db, linked["id"])}
    assert status["Call Priya about the venue"] == "done" and status["Buy milk"] == "todo"
    milk = next(r for r in rows if r["title"] == "Buy milk")
    _say(client, db, clock, _msg("Buy milk", reply_id=milk["id"]))
    assert {t["status"] for t in _tasks(db, linked["id"])} == {"done"}


def test_chain_messages_are_only_read_if_you_say_so(client, db, linked, clock, sent, ai):
    ai.script["Forward this"] = {"title": "Donate blood", "due_date": "2026-11-22"}
    _say(client, db, clock, _msg("Forward this to 10 people!!", context={"forwarded": True,
                                                                        "frequently_forwarded": True}))
    assert ai.calls == []
    assert [t for _, t in _buttons(sent[-1])] == ["Add as task", "Ignore"]
    _say(client, db, clock, _msg("Add as task", reply_id=_buttons(sent[-1])[0][0]))
    assert len(ai.calls) == 1 and "Donate blood" in _texts(sent)[-1]


def test_a_daily_messaging_limit_holds_reminders(client, db, env, clock, sent, ai, monkeypatch):
    monkeypatch.setenv("WA_MESSAGING_LIMIT", "1")
    people = []
    for i, wa in enumerate(("911111111111", "912222222222")):
        uid, h = _signup(client, f"lim{i}@example.com")
        code = client.post("/api/whatsapp/link", headers=h, json={"consent": True}).json()["code"]
        _say(client, db, clock, _msg(code, wa=wa), wa=wa)
        ai.script[f"task{i}"] = {"title": f"Task {i}", "due_date": "2026-11-20"}
        _say(client, db, clock, _msg(f"task{i}", wa=wa), wa=wa)
        _say(client, db, clock, _msg("Add", wa=wa, reply_id=_buttons(sent[-1])[0][0]), wa=wa)
        people.append(uid)
    sent.clear()
    assert asyncio.run(whatsapp.send_reminders(db, clock["now"])) == 1
    assert asyncio.run(whatsapp.send_reminders(db, clock["now"] + timedelta(hours=25))) == 0   # past catch-up


def test_ai_output_is_retried_once_and_tokens_are_logged(client, db, linked, clock, sent, ai):
    ai.fail_first = True
    ai.script["rent"] = {"title": "Pay rent", "due_date": "2026-11-21"}
    _say(client, db, clock, _msg("pay rent tomorrow"))
    assert len(ai.calls) == 2 and "Pay rent" in _texts(sent)[-1]
    [u] = asyncio.run(db.wa_ai_usage.find({}, {"_id": 0}).to_list(length=None))
    assert u["input_tokens"] == 500 and u["output_tokens"] == 40 and u["user_id"] == linked["id"]


def test_deleting_the_account_removes_whatsapp_data(client, db, linked, clock, sent, ai):
    _add_task(client, db, clock, sent, ai, "pay rent", "Pay rent")
    r = client.request("DELETE", "/api/account", headers=linked["h"],
                       json={"password": "correct-horse-battery", "confirm": "DELETE"})
    assert r.status_code == 200, r.text
    for name in ("wa_link", "consent_log", "wa_drafts", "wa_ai_usage", "wa_outbound"):
        assert asyncio.run(db[name].count_documents({"user_id": linked["id"]})) == 0, name
    assert asyncio.run(db.wa_inbound.count_documents({"user_id": linked["id"]})) == 0


def test_webhook_verification(client, env):
    q = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"}
    r = client.get("/api/whatsapp/webhook", params=q)
    assert r.status_code == 200 and r.text == "12345"
    assert client.get("/api/whatsapp/webhook", params={**q, "hub.verify_token": "nope"}).status_code == 403


def test_nothing_works_until_whatsapp_is_set_up(client, db, clock, sent):
    uid, h = _signup(client, "off@example.com")
    assert client.get("/api/whatsapp", headers=h).json()["available"] is False
    assert client.post("/api/whatsapp/link", headers=h, json={"consent": True}).status_code == 503
    assert _post(client, _msg("hi")).status_code == 404


def test_two_racing_add_taps_make_one_task(client, db, linked, clock, sent, ai):
    ai.script["rent"] = {"title": "Pay rent", "due_date": "2026-11-21"}
    _say(client, db, clock, _msg("pay rent tomorrow"))
    draft = asyncio.run(db.wa_drafts.find_one({"status": "pending"}, {"_id": 0}))
    user = asyncio.run(db.users.find_one({"id": linked["id"]}, {"_id": 0}))
    tap = {"wa_id": WA, "wamid": "wamid.tap"}
    first = asyncio.run(whatsapp.create_from_draft(db, user, dict(draft), tap, clock["now"]))
    second = asyncio.run(whatsapp.create_from_draft(db, user, dict(draft), tap, clock["now"]))   # stale copy
    assert first and second is None
    assert [t["title"] for t in _tasks(db, linked["id"])] == ["Pay rent"]


def test_a_task_that_starts_with_complete_is_a_new_task(client, db, linked, clock, sent, ai):
    _add_task(client, db, clock, sent, ai, "pay rent", "Pay rent")
    ai.script["report"] = {"title": "Complete the report", "due_date": "2026-11-21"}
    _say(client, db, clock, _msg("complete the report by friday"))
    assert "Complete the report" in _texts(sent)[-1]
    assert [t["status"] for t in _tasks(db, linked["id"])] == ["todo"]


def test_the_free_plan_has_a_monthly_whatsapp_limit(client, db, linked, clock, sent, ai):
    import metering
    asyncio.run(metering.save_settings(db, {"limits": {"whatsapp_tasks_month": {"free": 1, "premium": None}}}))
    _add_task(client, db, clock, sent, ai, "pay rent", "Pay rent")
    calls = len(ai.calls)
    _say(client, db, clock, _msg("call the plumber tomorrow"))
    assert len(ai.calls) == calls                                      # no AI spent once the limit is reached
    assert "free plan's limit" in _texts(sent)[-1]
