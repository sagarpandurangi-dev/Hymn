"""North-star vertical slice tests for universal purchase intentions."""

import os
import time
import uuid

import pytest
import requests
from bson.decimal128 import Decimal128
from pymongo import MongoClient

from fastapi import HTTPException

from intent_engine import classify_intent


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
FUTURE_DATE = "2099-12-15"


def _signup(label: str) -> dict:
    response = requests.post(
        f"{API}/auth/signup",
        json={
            "display_name": f"Intent {label}",
            "email": f"TEST_intent_{label}_{time.time_ns()}@hymn.app",
            "password": "TestPass123!",
            "security_question": "Question?",
            "security_answer": "Answer",
        },
        timeout=15,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "id": body["user"]["id"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


@pytest.fixture(scope="module")
def context():
    client = MongoClient(MONGO_URL)
    database = client[DB_NAME]
    primary = _signup("primary")
    other = _signup("other")
    state = {
        "db": database,
        "primary": primary,
        "other": other,
        "created_intent_id": None,
        "commitment_id": None,
    }
    yield state
    user_ids = [primary["id"], other["id"]]
    intent_ids = [
        row["id"]
        for row in database.universal_intents.find(
            {"user_id": {"$in": user_ids}},
            {"_id": 0, "id": 1},
        )
    ]
    database.universal_intents.delete_many({"user_id": {"$in": user_ids}})
    database.resource_allocations.delete_many({
        "$or": [
            {"user_id": {"$in": user_ids}},
            {"source_intent_id": {"$in": intent_ids}},
        ]
    })
    database.financial_audit.delete_many({"user_id": {"$in": user_ids}})
    database.financial_accounts.delete_many({"user_id": {"$in": user_ids}})
    database.monthly_money_commitments.delete_many({"user_id": {"$in": user_ids}})
    database.tasks.delete_many({"user_id": {"$in": user_ids}})
    database.goals.delete_many({"user_id": {"$in": user_ids}})
    database.domains.delete_many({"user_id": {"$in": user_ids}})
    database.users.delete_many({"id": {"$in": user_ids}})
    client.close()


def _analyze(context, payload: dict):
    return requests.post(
        f"{API}/intents/analyze",
        json=payload,
        headers=context["primary"]["headers"],
        timeout=15,
    )


def _known_purchase(price: str = "1000.00") -> dict:
    return {
        "text": "I want to buy an iPad",
        "purchase": {
            "expected_price": price,
            "currency": "USD",
            "desired_date": FUTURE_DATE,
        },
    }


def test_deterministic_purchase_parser_and_unsupported_classification():
    parsed = classify_intent("I want to buy an iPad for $999 by 2099-12-15")
    assert parsed["intent_type"] == "purchase"
    assert parsed["item"] == "iPad"
    assert parsed["extracted_price"] == "999.00"
    assert parsed["extracted_currency"] == "USD"
    assert parsed["extracted_date"] == FUTURE_DATE

    unsupported = classify_intent("I want to plan a trip")
    assert unsupported["intent_type"] == "unsupported"
    assert unsupported["item"] is None


@pytest.mark.parametrize(
    ("text", "item", "price", "currency", "desired_date"),
    [
        ("Buy an iPad", "iPad", None, None, None),
        ("Buy an iPad for ₹80,000", "iPad", "80000.00", "INR", None),
        (
            "Buy an iPad for 80000 INR by December 15",
            "iPad",
            "80000.00",
            "INR",
            "2026-12-15",
        ),
        (
            "I want to purchase a laptop next month for $1,200",
            "laptop",
            "1200.00",
            "USD",
            "2026-08-26",
        ),
        (
            "Buy a keyboard made for iPad for USD 120 by 2 January 2027",
            "keyboard made for iPad",
            "120.00",
            "USD",
            "2027-01-02",
        ),
    ],
)
def test_parser_extracts_supported_purchase_facts(
    text,
    item,
    price,
    currency,
    desired_date,
):
    parsed = classify_intent(text, "2026-07-26")
    assert parsed["intent_type"] == "purchase"
    assert parsed["item"] == item
    assert parsed["extracted_price"] == price
    assert parsed["extracted_currency"] == currency
    assert parsed["extracted_date"] == desired_date


def test_exact_labeled_price_sentence_extracts_item_amount_and_date():
    parsed = classify_intent(
        "buy a diamond ring by dec 31 2026 price 200000",
        "2026-07-26",
    )

    assert parsed["item"] == "diamond ring"
    assert parsed["extracted_price"] == "200000.00"
    assert parsed["extracted_currency"] is None
    assert parsed["extracted_date"] == "2026-12-31"


@pytest.mark.parametrize(
    "label",
    [
        "price 200000",
        "price: 200000",
        "price is 200000",
        "cost 200000",
        "costs 200000",
        "costing 200000",
        "budget 200000",
        "with a budget of 200000",
        "priced at 200000",
    ],
)
def test_labeled_amount_forms_are_supported_and_removed_from_item(label):
    parsed = classify_intent(f"Buy a diamond ring {label}", "2026-07-26")

    assert parsed["item"] == "diamond ring"
    assert parsed["extracted_price"] == "200000.00"
    assert parsed["extracted_currency"] is None


@pytest.mark.parametrize(
    ("text", "price", "currency"),
    [
        ("Buy a ring price ₹2,00,000", "200000.00", "INR"),
        ("Buy a ring cost INR 2,00,000", "200000.00", "INR"),
        ("Buy a ring costs 200,000 USD", "200000.00", "USD"),
        ("Buy a ring budget $200,000", "200000.00", "USD"),
        ("Buy a ring price 1,23,45,678 INR", "12345678.00", "INR"),
        ("Buy a ring cost USD 1,234,567.89", "1234567.89", "USD"),
    ],
)
def test_labeled_amounts_support_currency_and_valid_comma_grouping(
    text,
    price,
    currency,
):
    parsed = classify_intent(text, "2026-07-26")

    assert parsed["item"] == "ring"
    assert parsed["extracted_price"] == price
    assert parsed["extracted_currency"] == currency


def test_multiple_labeled_amounts_are_ambiguous():
    parsed = classify_intent(
        "Buy a diamond ring price 200000 or budget 250000",
        "2026-07-26",
    )

    assert parsed["extracted_price"] is None
    assert parsed["extracted_currency"] is None
    assert "expected_price" in parsed["ambiguities"]


@pytest.mark.parametrize(
    "text",
    [
        "Buy an iPhone 16",
        "Buy a TV model 200000",
        "Buy two chairs for 12 installments",
        "Buy chairs cost 12 units",
        "Buy tickets for 31/12/2026",
        "Buy a sofa in 2026",
    ],
)
def test_price_parser_avoids_dates_quantities_models_and_installment_counts(text):
    parsed = classify_intent(text, "2026-07-26")
    assert parsed["extracted_price"] is None


def test_existing_bare_for_amount_behavior_is_preserved():
    parsed = classify_intent(
        "Buy a diamond ring for 200000 by December 31 2026",
        "2026-07-26",
    )
    assert parsed["item"] == "diamond ring"
    assert parsed["extracted_price"] == "200000.00"
    assert parsed["extracted_date"] == "2026-12-31"


def test_relative_date_resolution_is_traceable_and_clamps_month_end():
    parsed = classify_intent(
        "Purchase a laptop next month for GBP 900",
        "2027-01-31",
    )
    assert parsed["extracted_date"] == "2027-02-28"
    assert parsed["extracted_timing_text"] == "next month"
    assert parsed["timing_precision"] == "relative_date"
    assert "2027-01-31" in parsed["timing_resolution"]


def test_unambiguous_day_first_numeric_date_and_item_cleanup():
    parsed = classify_intent(
        "Buy a hero honda splendor for 95000 on 31/12/2026",
        "2026-07-26",
    )
    assert parsed["item"] == "hero honda splendor"
    assert parsed["extracted_price"] == "95000.00"
    assert parsed["extracted_date"] == "2026-12-31"
    assert parsed["extracted_timing_text"] == "31/12/2026"
    assert parsed["timing_resolution"].startswith("Parsed as DD/MM/YYYY")


def test_unambiguous_day_first_date_survives_the_analyze_api_contract(context):
    response = _analyze(
        context,
        {
            "text": "Buy a hero honda splendor for 95000 on 31/12/2026",
            "purchase": {
                "price_unknown": False,
                "timing_unknown": False,
            },
            "reference_date": "2026-07-26",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["original_text"] == (
        "Buy a hero honda splendor for 95000 on 31/12/2026"
    )
    assert body["purchase"]["item"] == "hero honda splendor"
    assert body["purchase"]["expected_price"] == "95000.00"
    assert body["purchase"]["desired_date"] == "2026-12-31"
    assert body["purchase"]["timing_text"] == "31/12/2026"
    assert body["purchase"]["field_sources"]["desired_date"] == (
        "inferred_from_text"
    )


def test_day_first_numeric_leap_day_is_calendar_validated():
    leap_day = classify_intent("Buy a car by 29/02/2028", "2027-01-01")
    assert leap_day["extracted_date"] == "2028-02-29"

    with pytest.raises(HTTPException) as exc_info:
        classify_intent("Buy a car by 29/02/2027", "2026-07-26")
    assert exc_info.value.status_code == 400
    assert "valid calendar date" in exc_info.value.detail


@pytest.mark.parametrize(
    "text",
    [
        "Buy a car on 31/04/2027",
        "Buy a car before 32/12/2027",
        "Buy a car by 00/12/2027",
    ],
)
def test_impossible_numeric_dates_are_rejected(text):
    with pytest.raises(HTTPException) as exc_info:
        classify_intent(text, "2026-07-26")
    assert exc_info.value.status_code == 400


def test_ambiguous_and_us_style_numeric_dates_require_clarification():
    ambiguous = classify_intent("Buy a car on 01/02/2027", "2026-07-26")
    assert ambiguous["item"] == "car"
    assert ambiguous["extracted_date"] is None
    assert ambiguous["ambiguities"] == ["desired_date"]
    assert "day/month/year or month/day/year" in ambiguous["timing_ambiguity_reason"]

    us_style = classify_intent("Buy a car on 12/31/2026", "2026-07-26")
    assert us_style["item"] == "car"
    assert us_style["extracted_date"] is None
    assert us_style["ambiguities"] == ["desired_date"]
    assert "no confirmed locale" in us_style["timing_ambiguity_reason"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Buy a car on 2026-12-31", "2026-12-31"),
        ("Buy a car by December 15", "2026-12-15"),
        ("Buy a car next month", "2026-08-26"),
    ],
)
def test_prior_date_formats_remain_supported(text, expected):
    assert classify_intent(text, "2026-07-26")["extracted_date"] == expected


def test_parser_reports_ambiguity_and_avoids_false_positive_purchase_words():
    ambiguous_price = classify_intent(
        "Buy an iPad for $1,000 or $1,200 next month",
        "2026-07-26",
    )
    assert ambiguous_price["extracted_price"] is None
    assert "expected_price" in ambiguous_price["ambiguities"]

    ambiguous_date = classify_intent(
        "Buy an iPad by December 15 or January 10",
        "2026-07-26",
    )
    assert ambiguous_date["extracted_date"] is None
    assert "desired_date" in ambiguous_date["ambiguities"]

    assert classify_intent("Review the purchase order")["intent_type"] == "unsupported"
    assert classify_intent("I want to buy time")["intent_type"] == "unsupported"


@pytest.mark.parametrize(
    "text",
    [
        "Buy an iPad for ₹80,00",
        "Buy an iPad for $12.345",
        "Buy an iPad for 1,2,000 INR",
    ],
)
def test_parser_rejects_malformed_amount_language(text):
    with pytest.raises(HTTPException) as exc_info:
        classify_intent(text, "2026-07-26")
    assert exc_info.value.status_code == 400


def test_labeled_amount_api_keeps_amount_and_asks_for_missing_currency(context):
    original = "buy a diamond ring by dec 31 2026 price 200000"
    response = _analyze(
        context,
        {"text": original, "reference_date": "2026-07-26"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purchase"]["item"] == "diamond ring"
    assert body["purchase"]["expected_price"] == "200000.00"
    assert body["purchase"]["currency"] is None
    assert body["purchase"]["desired_date"] == "2026-12-31"
    assert "currency" in body["missing_data"]
    currency_question = next(
        row for row in body["clarification_questions"]
        if row["field"] == "currency"
    )
    assert "currency" in currency_question["question"].lower()


def test_labeled_amount_api_uses_explicit_profile_currency_when_available(context):
    db = context["db"]
    user_id = context["primary"]["id"]
    original = db.users.find_one({"id": user_id}, {"portfolio_reporting_currency": 1})
    try:
        db.users.update_one(
            {"id": user_id},
            {"$set": {"portfolio_reporting_currency": "INR"}},
        )
        response = _analyze(
            context,
            {
                "text": "buy a diamond ring by dec 31 2026 price 200000",
                "reference_date": "2026-07-26",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["purchase"]["expected_price"] == "200000.00"
        assert body["purchase"]["currency"] == "INR"
        assert body["purchase"]["field_sources"]["currency"] == "known_profile"
    finally:
        if original and "portfolio_reporting_currency" in original:
            db.users.update_one(
                {"id": user_id},
                {"$set": {
                    "portfolio_reporting_currency": original[
                        "portfolio_reporting_currency"
                    ],
                }},
            )
        else:
            db.users.update_one(
                {"id": user_id},
                {"$unset": {"portfolio_reporting_currency": ""}},
            )


def test_buy_ipad_without_context_is_honest_and_stateless(context):
    before = context["db"].universal_intents.count_documents({
        "user_id": context["primary"]["id"],
    })
    response = _analyze(context, {"text": "Buy an iPad"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent_type"] == "purchase"
    assert body["purchase"]["item"] == "iPad"
    assert body["affordability_status"] == "insufficient_data"
    assert body["result_status"] == "needs_input"
    assert {"expected_price", "desired_date"} <= set(body["missing_data"])
    assert body["financial_snapshot"]["has_financial_data"] is False
    assert body["financial_snapshot"]["available_before_purchase"] is None
    assert body["impacted_goals_or_commitments"] == []
    assert context["db"].universal_intents.count_documents({
        "user_id": context["primary"]["id"],
    }) == before


def test_sentence_inference_prefills_review_with_traceable_sources(context):
    original = "Buy an iPad for 80000 INR by December 15"
    response = _analyze(
        context,
        {"text": original, "reference_date": "2026-07-26"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["original_text"] == original
    assert body["reference_date"] == "2026-07-26"
    assert body["purchase"]["item"] == "iPad"
    assert body["purchase"]["expected_price"] == "80000.00"
    assert body["purchase"]["currency"] == "INR"
    assert body["purchase"]["desired_date"] == "2026-12-15"
    assert body["purchase"]["timing_text"] == "December 15"
    assert body["purchase"]["field_sources"] == {
        "item": "inferred_from_text",
        "expected_price": "inferred_from_text",
        "currency": "inferred_from_text",
        "desired_date": "inferred_from_text",
    }
    assert {
        "intent_text:item",
        "intent_text:expected_price",
        "intent_text:desired_date",
        "inferred_from_text:currency",
    } <= {row["id"] for row in body["evidence"]}


def test_missing_inputs_are_targeted_and_unknown_is_allowed(context):
    missing = _analyze(context, {"text": "Buy an iPad"}).json()
    question_fields = {row["field"] for row in missing["clarification_questions"]}
    assert question_fields == {"expected_price", "desired_date"}

    unknown = _analyze(
        context,
        {
            "text": "Buy an iPad",
            "purchase": {"price_unknown": True, "timing_unknown": True},
        },
    )
    assert unknown.status_code == 200, unknown.text
    body = unknown.json()
    assert body["result_status"] == "review_ready"
    assert body["can_confirm"] is True
    assert body["affordability_status"] == "insufficient_data"
    assert body["clarification_questions"] == []
    assert {"expected_price", "desired_date"} <= set(body["missing_data"])


def test_ambiguous_numeric_date_returns_targeted_api_clarification(context):
    response = _analyze(
        context,
        {
            "text": "Buy a car on 01/02/2027",
            "reference_date": "2026-07-26",
            "purchase": {"price_unknown": True},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purchase"]["item"] == "car"
    assert body["purchase"]["desired_date"] is None
    assert "desired_date" in body["missing_data"]
    question = next(
        row for row in body["clarification_questions"]
        if row["field"] == "desired_date"
    )
    assert "day/month/year or month/day/year" in question["question"]


def test_user_corrections_override_inference_and_keep_original_sentence(context):
    original = "I want to purchase a laptop next month for $1,200"
    response = _analyze(
        context,
        {
            "text": original,
            "reference_date": "2026-07-26",
            "purchase": {
                "expected_price": "999.00",
                "currency": "EUR",
                "desired_date": "2026-09-10",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["original_text"] == original
    assert body["classification"]["extracted_price"] == "1200.00"
    assert body["classification"]["extracted_currency"] == "USD"
    assert body["classification"]["extracted_date"] == "2026-08-26"
    assert body["purchase"]["expected_price"] == "999.00"
    assert body["purchase"]["currency"] == "EUR"
    assert body["purchase"]["desired_date"] == "2026-09-10"
    assert body["purchase"]["field_sources"]["expected_price"] == "user_edited"
    assert body["purchase"]["field_sources"]["currency"] == "user_edited"
    assert body["purchase"]["field_sources"]["desired_date"] == "user_edited"


def test_unsupported_intent_preserves_text_without_persistence(context):
    before = context["db"].universal_intents.count_documents({
        "user_id": context["primary"]["id"],
    })
    response = _analyze(context, {"text": "I want to plan a trip to Kyoto"})
    assert response.status_code == 200
    body = response.json()
    assert body["result_status"] == "unsupported"
    assert body["original_text"] == "I want to plan a trip to Kyoto"
    assert body["can_confirm"] is False
    assert context["db"].universal_intents.count_documents({
        "user_id": context["primary"]["id"],
    }) == before


def test_malformed_amounts_dates_and_empty_text_are_rejected(context):
    bad_amount = _analyze(context, _known_purchase("12.345"))
    assert bad_amount.status_code == 400
    bad_date = _known_purchase()
    bad_date["purchase"]["desired_date"] = "2099-02-30"
    invalid_date = _analyze(context, bad_date)
    assert invalid_date.status_code == 400
    bad_currency = _known_purchase()
    bad_currency["purchase"]["currency"] = "ZZZ"
    invalid_currency = _analyze(context, bad_currency)
    assert invalid_currency.status_code == 400
    malformed_text_amount = _analyze(
        context,
        {"text": "Buy an iPad for $12.345 by 2099-12-15"},
    )
    assert malformed_text_amount.status_code == 400
    empty = _analyze(context, {"text": "   "})
    assert empty.status_code == 400


def test_income_without_a_recorded_liquid_balance_is_not_assumed_affordable(context):
    db = context["db"]
    user_id = context["primary"]["id"]
    income_id = str(uuid.uuid4())
    db.monthly_money_commitments.insert_one({
        "id": income_id,
        "user_id": user_id,
        "title": "Recorded income only",
        "currency": "USD",
        "amount": Decimal128("5000.00"),
        "commitment_type": "income",
        "fixed_or_flexible": "fixed",
        "start_month": "2099-01",
        "end_month": None,
    })
    try:
        body = _analyze(context, _known_purchase()).json()
        assert body["financial_snapshot"]["has_financial_data"] is True
        assert body["financial_snapshot"]["has_liquid_balance"] is False
        assert body["affordability_status"] == "insufficient_data"
        assert "financial_context" in body["missing_data"]
    finally:
        db.monthly_money_commitments.delete_one({"id": income_id, "user_id": user_id})


def test_affordability_states_use_recorded_calculation_evidence(context):
    db = context["db"]
    user_id = context["primary"]["id"]
    account_id = str(uuid.uuid4())
    db.financial_accounts.insert_one({
        "id": account_id,
        "user_id": user_id,
        "account_type": "cash",
        "name": "Purchase cash",
        "currency": "USD",
        "current_value": Decimal128("5000.00"),
        "liquidity_type": "liquid",
        "fixed_or_flexible": "flexible",
        "notes": "",
        "created_at": FUTURE_DATE,
        "updated_at": FUTURE_DATE,
    })
    income_id = str(uuid.uuid4())
    expense_id = str(uuid.uuid4())
    db.monthly_money_commitments.insert_many([
        {
            "id": income_id,
            "user_id": user_id,
            "title": "Recorded income",
            "currency": "USD",
            "amount": Decimal128("1000.00"),
            "commitment_type": "income",
            "fixed_or_flexible": "fixed",
            "start_month": "2099-01",
            "end_month": None,
        },
        {
            "id": expense_id,
            "user_id": user_id,
            "title": "Recorded expenses",
            "currency": "USD",
            "amount": Decimal128("500.00"),
            "commitment_type": "expense",
            "fixed_or_flexible": "fixed",
            "start_month": "2099-01",
            "end_month": None,
        },
    ])

    affordable = _analyze(context, _known_purchase()).json()
    assert affordable["affordability_status"] == "affordable"
    assert affordable["financial_snapshot"]["available_before_purchase"] == "5500.00"
    assert affordable["financial_snapshot"]["projected_after_purchase"] == "4500.00"
    evidence_ids = {row["id"] for row in affordable["evidence"]}
    assert f"financial_account:{account_id}" in evidence_ids
    assert f"monthly_money_commitment:{income_id}" in evidence_ids
    assert "create_draft_commitment" in {row["id"] for row in affordable["options"]}

    db.financial_accounts.update_one(
        {"id": account_id},
        {"$set": {"current_value": Decimal128("600.00")}},
    )
    borderline = _analyze(context, _known_purchase()).json()
    assert borderline["affordability_status"] == "borderline"

    db.financial_accounts.update_one(
        {"id": account_id},
        {"$set": {"current_value": Decimal128("0.00")}},
    )
    not_affordable = _analyze(context, _known_purchase()).json()
    assert not_affordable["affordability_status"] == "not_affordable"
    assert len(not_affordable["options"]) >= 2
    assert "create_draft_commitment" not in {
        row["id"] for row in not_affordable["options"]
    }

    db.financial_accounts.update_one(
        {"id": account_id},
        {"$set": {"current_value": Decimal128("5000.00")}},
    )


def test_impacted_goal_is_reported_only_from_owned_recorded_evidence(context):
    db = context["db"]
    user_id = context["primary"]["id"]
    goal_id = str(uuid.uuid4())
    allocation_id = str(uuid.uuid4())
    db.goals.insert_one({
        "id": goal_id,
        "user_id": user_id,
        "title": "Emergency reserve",
    })
    db.resource_allocations.insert_one({
        "id": allocation_id,
        "user_id": user_id,
        "resource_type": "money",
        "currency": "USD",
        "quantity": Decimal128("250.00"),
        "status": "reserved",
        "state": "reserved",
        "date": FUTURE_DATE,
        "title": "Emergency reserve contribution",
        "goal_id": goal_id,
    })
    try:
        body = _analyze(context, _known_purchase()).json()
        assert body["impacted_goals_or_commitments"] == [{
            "type": "goal",
            "id": goal_id,
            "title": "Emergency reserve",
            "reason": "It has a recorded money commitment due by the purchase date.",
            "evidence_id": f"resource_allocation:{allocation_id}",
        }]
        assert "goals" in body["contexts_queried"]
        assert f"resource_allocation:{allocation_id}" in {
            row["id"] for row in body["evidence"]
        }
    finally:
        db.resource_allocations.delete_one({"id": allocation_id, "user_id": user_id})
        db.goals.delete_one({"id": goal_id, "user_id": user_id})


def test_save_only_confirmation_creates_no_downstream_record(context):
    idempotency_key = f"intent-save-{uuid.uuid4()}"
    response = requests.post(
        f"{API}/intents/confirm",
        json={
            "text": "Buy an iPad",
            "purchase": {"price_unknown": True, "timing_unknown": True},
            "selected_option_id": "save_only",
            "idempotency_key": idempotency_key,
        },
        headers=context["primary"]["headers"],
        timeout=15,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["selected_option_id"] == "save_only"
    assert body["downstream_records"] == []


def test_confirmation_is_canonical_owned_and_idempotent(context):
    idempotency_key = f"intent-confirm-{uuid.uuid4()}"
    payload = {
        **_known_purchase(),
        "selected_option_id": "create_draft_commitment",
        "idempotency_key": idempotency_key,
    }
    first = requests.post(
        f"{API}/intents/confirm",
        json=payload,
        headers=context["primary"]["headers"],
        timeout=15,
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "confirmed"
    assert body["selected_option_id"] == "create_draft_commitment"
    assert len(body["downstream_records"]) == 1
    intent_id = body["id"]
    commitment_id = body["downstream_records"][0]["id"]
    context["created_intent_id"] = intent_id
    context["commitment_id"] = commitment_id

    allocation = context["db"].resource_allocations.find_one({
        "user_id": context["primary"]["id"],
        "financial_commitment_id": commitment_id,
    })
    assert allocation["state"] == "draft"
    assert allocation["status"] == "proposed"
    assert allocation["source"] == "universal_intent"
    assert allocation["source_intent_id"] == intent_id
    assert context["db"].tasks.count_documents({
        "user_id": context["primary"]["id"],
        "financial_commitment_id": commitment_id,
    }) == 0

    repeated = requests.post(
        f"{API}/intents/confirm",
        json=payload,
        headers=context["primary"]["headers"],
        timeout=15,
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == intent_id
    assert context["db"].resource_allocations.count_documents({
        "user_id": context["primary"]["id"],
        "source_intent_id": intent_id,
    }) == 1


def test_detail_refresh_and_ownership_isolation(context):
    intent_id = context["created_intent_id"]
    own = requests.get(
        f"{API}/intents/{intent_id}",
        headers=context["primary"]["headers"],
        timeout=15,
    )
    assert own.status_code == 200
    assert own.json()["id"] == intent_id
    assert own.json()["assessment"]["evidence"]

    other = requests.get(
        f"{API}/intents/{intent_id}",
        headers=context["other"]["headers"],
        timeout=15,
    )
    assert other.status_code == 404

    listed = requests.get(
        f"{API}/intents",
        headers=context["primary"]["headers"],
        timeout=15,
    )
    assert listed.status_code == 200
    assert intent_id in {row["id"] for row in listed.json()}


def test_cancel_or_back_after_analysis_leaves_no_partial_record(context):
    before_intents = context["db"].universal_intents.count_documents({
        "user_id": context["primary"]["id"],
    })
    before_allocations = context["db"].resource_allocations.count_documents({
        "user_id": context["primary"]["id"],
    })
    response = _analyze(context, _known_purchase("750.00"))
    assert response.status_code == 200
    # The client may now cancel or navigate back; no cleanup API is necessary
    # because analysis is deliberately stateless.
    assert context["db"].universal_intents.count_documents({
        "user_id": context["primary"]["id"],
    }) == before_intents
    assert context["db"].resource_allocations.count_documents({
        "user_id": context["primary"]["id"],
    }) == before_allocations
