"""Focused integration tests for Check-in spending reconciliation.

All writes are isolated to TEST_ users in hymn_test and removed afterward.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import os
import uuid

from bson.decimal128 import Decimal128
from pymongo import MongoClient
import pytest
import requests


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _signup(label: str) -> tuple[str, str]:
    response = requests.post(
        f"{API}/auth/signup",
        json={
            "display_name": f"Reconciliation {label}",
            "email": f"TEST_reconciliation_{label}_{uuid.uuid4().hex[:10]}@hymn.app",
            "password": "TestPass123!",
            "security_question": "Test question?",
            "security_answer": "Test answer",
        },
        timeout=15,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["access_token"], body["user"]["id"]


@pytest.fixture
def context():
    client = MongoClient(os.environ["MONGO_URL"])
    database = client[os.environ["DB_NAME"]]
    owner_token, owner_id = _signup("owner")
    other_token, other_id = _signup("other")

    domains = requests.get(
        f"{API}/domains",
        headers=_headers(owner_token),
        timeout=15,
    )
    assert domains.status_code == 200, domains.text
    goal = requests.post(
        f"{API}/goals",
        headers=_headers(owner_token),
        json={
            "title": "TEST_reconciliation_goal",
            "domain_id": domains.json()[0]["id"],
        },
        timeout=15,
    )
    assert goal.status_code == 201, goal.text
    outcome = requests.post(
        f"{API}/expected-outcomes",
        headers=_headers(owner_token),
        json={
            "goal_id": goal.json()["id"],
            "title": "TEST reconciliation outcome",
        },
        timeout=15,
    )
    assert outcome.status_code == 201, outcome.text

    account_id = str(uuid.uuid4())
    database.financial_accounts.insert_one({
        "id": account_id,
        "user_id": owner_id,
        "account_type": "bank",
        "name": "TEST untouched bank",
        "currency": "INR",
        "current_value": Decimal128(Decimal("5000")),
        "liquidity_type": "liquid",
        "fixed_or_flexible": "flexible",
        "notes": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    checkin = requests.post(
        f"{API}/checkins",
        headers=_headers(owner_token),
        json={
            "type": "goal",
            "title": "TEST INR 700 check-in",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "time": "12:00",
            "expected_outcome_id": outcome.json()["id"],
            "money_spent": "700",
            "money_currency": "INR",
        },
        timeout=15,
    )
    assert checkin.status_code == 201, checkin.text
    checkin_id = checkin.json()["id"]
    event = database.financial_events.find_one(
        {
            "user_id": owner_id,
            "source": "checkin",
            "checkin_id": checkin_id,
        },
        {"_id": 0},
    )
    assert event is not None

    yield {
        "database": database,
        "owner_token": owner_token,
        "owner_id": owner_id,
        "other_token": other_token,
        "other_id": other_id,
        "goal_id": goal.json()["id"],
        "checkin_id": checkin_id,
        "event_id": event["id"],
        "account_id": account_id,
    }

    user_ids = [owner_id, other_id]
    database.financial_audit.delete_many({"user_id": {"$in": user_ids}})
    database.financial_dedupe_candidates.delete_many({"user_id": {"$in": user_ids}})
    database.financial_events.delete_many({"user_id": {"$in": user_ids}})
    database.financial_accounts.delete_many({"user_id": {"$in": user_ids}})
    database.resource_allocations.delete_many({"user_id": {"$in": user_ids}})
    database.checkins.delete_many({"user_id": {"$in": user_ids}})
    database.expected_outcomes.delete_many({"user_id": {"$in": user_ids}})
    database.goals.delete_many({"user_id": {"$in": user_ids}})
    database.domains.delete_many({"user_id": {"$in": user_ids}})
    database.users.delete_many({"id": {"$in": user_ids}})
    client.close()


def _resolve(context, token: str | None = None):
    return requests.post(
        f"{API}/finance/reconciliation/{context['event_id']}/reject",
        headers=_headers(token or context["owner_token"]),
        timeout=15,
    )


def _resolution_audits(context) -> list:
    return list(context["database"].financial_audit.find({
        "user_id": context["owner_id"],
        "record_id": context["event_id"],
        "new_value.outcome": "resolved_unplanned",
    }))


def test_checkin_creates_one_canonical_awaiting_finance_actual(context):
    database = context["database"]
    events = list(database.financial_events.find({
        "user_id": context["owner_id"],
        "checkin_id": context["checkin_id"],
    }))

    assert len(events) == 1
    assert events[0]["source_reference"] == f"checkin:{context['checkin_id']}"
    assert events[0]["confirmation_status"] == "confirmed"
    assert events[0]["reconciliation_status"] == "awaiting_reconciliation"
    assert events[0]["amount"] == Decimal128(Decimal("700"))
    assert "financial_transactions" not in database.list_collection_names()


def test_first_and_repeated_unplanned_resolution_are_idempotent(context):
    pending_before = requests.get(
        f"{API}/finance/reconciliation/suggestions",
        headers=_headers(context["owner_token"]),
        timeout=15,
    )
    assert pending_before.status_code == 200
    assert context["event_id"] in {
        item["event"]["id"] for item in pending_before.json()
    }
    account_before = deepcopy(context["database"].financial_accounts.find_one({
        "id": context["account_id"],
        "user_id": context["owner_id"],
    }))

    first = _resolve(context)
    repeated = _resolve(context)

    assert first.status_code == 200, first.text
    assert repeated.status_code == 200, repeated.text
    assert first.json()["already_resolved"] is False
    assert repeated.json()["already_resolved"] is True
    assert first.json()["resolution"] == "resolved_unplanned"
    assert first.json()["canonical_actual"] == {
        "record_type": "financial_event",
        "record_id": context["event_id"],
        "source": "checkin",
    }
    assert first.json()["balance_adjustment"]["status"] == "not_applied"
    assert first.json()["navigation"]["route"] == "/(tabs)/finance"

    pending_after = requests.get(
        f"{API}/finance/reconciliation/suggestions",
        headers=_headers(context["owner_token"]),
        timeout=15,
    )
    assert pending_after.status_code == 200
    assert context["event_id"] not in {
        item["event"]["id"] for item in pending_after.json()
    }
    assert context["database"].financial_events.count_documents({
        "user_id": context["owner_id"],
        "checkin_id": context["checkin_id"],
    }) == 1
    assert len(_resolution_audits(context)) == 1

    account_after = context["database"].financial_accounts.find_one({
        "id": context["account_id"],
        "user_id": context["owner_id"],
    })
    assert account_after == account_before


def test_concurrent_replayed_resolution_creates_one_final_audit(context):
    def submit():
        return _resolve(context)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: submit(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["already_resolved"] for response in responses) == [
        False,
        True,
    ]
    assert len(_resolution_audits(context)) == 1
    assert context["database"].financial_events.count_documents({
        "user_id": context["owner_id"],
        "checkin_id": context["checkin_id"],
    }) == 1


def test_legacy_unmatched_event_resolves_without_rewriting_history(context):
    database = context["database"]
    database.financial_events.update_one(
        {"id": context["event_id"], "user_id": context["owner_id"]},
        {"$set": {"reconciliation_status": "unmatched"}},
    )
    legacy_audit_id = str(uuid.uuid4())
    database.financial_audit.insert_one({
        "id": legacy_audit_id,
        "user_id": context["owner_id"],
        "record_type": "financial_event",
        "record_id": context["event_id"],
        "action": "reconciled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "reconciliation",
        "new_value": {"outcome": "unmatched"},
    })

    response = _resolve(context)

    assert response.status_code == 200, response.text
    assert response.json()["already_resolved"] is False
    assert database.financial_audit.count_documents({"id": legacy_audit_id}) == 1
    assert len(_resolution_audits(context)) == 1


def test_cross_user_event_id_is_rejected_without_changing_owner_data(context):
    response = _resolve(context, context["other_token"])

    assert response.status_code == 404
    event = context["database"].financial_events.find_one({
        "id": context["event_id"],
        "user_id": context["owner_id"],
    })
    assert event["reconciliation_status"] == "awaiting_reconciliation"
    assert len(_resolution_audits(context)) == 0


def test_matching_to_a_planned_commitment_is_a_final_lifecycle_state(context):
    commitment = requests.post(
        f"{API}/finance/commitments",
        headers=_headers(context["owner_token"]),
        json={
            "title": "TEST planned INR expense",
            "amount": "700",
            "currency": "INR",
            "due_date": datetime.now(timezone.utc).date().isoformat(),
            "priority": "medium",
        },
        timeout=15,
    )
    assert commitment.status_code == 201, commitment.text
    reserved = requests.post(
        f"{API}/finance/commitments/{commitment.json()['id']}/reserve",
        headers=_headers(context["owner_token"]),
        timeout=15,
    )
    assert reserved.status_code == 200, reserved.text

    matched = requests.post(
        f"{API}/finance/reconciliation/{context['event_id']}/confirm",
        headers=_headers(context["owner_token"]),
        json={"commitment_id": commitment.json()["id"]},
        timeout=15,
    )

    assert matched.status_code == 200, matched.text
    event = context["database"].financial_events.find_one({
        "id": context["event_id"],
        "user_id": context["owner_id"],
    })
    assert event["reconciliation_status"] == "matched"
    assert event["reconciliation_resolution"] == "planned_commitment"
    pending = requests.get(
        f"{API}/finance/reconciliation/suggestions",
        headers=_headers(context["owner_token"]),
        timeout=15,
    )
    assert context["event_id"] not in {
        item["event"]["id"] for item in pending.json()
    }


def test_failed_resolution_does_not_write_and_can_be_retried(context):
    database = context["database"]
    database.financial_events.update_one(
        {"id": context["event_id"], "user_id": context["owner_id"]},
        {"$set": {"confirmation_status": "rejected"}},
    )

    failed = _resolve(context)

    assert failed.status_code == 409
    assert "confirmed" in failed.json()["detail"].lower()
    assert len(_resolution_audits(context)) == 0
    failed_event = database.financial_events.find_one({"id": context["event_id"]})
    assert failed_event["reconciliation_status"] == "awaiting_reconciliation"

    database.financial_events.update_one(
        {"id": context["event_id"], "user_id": context["owner_id"]},
        {"$set": {"confirmation_status": "confirmed"}},
    )
    retried = _resolve(context)

    assert retried.status_code == 200, retried.text
    assert retried.json()["already_resolved"] is False
    assert len(_resolution_audits(context)) == 1
