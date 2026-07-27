"""Focused tests for the sanitized, deterministic Planning v1 contract."""

from copy import deepcopy
from decimal import Decimal
import json
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

import planning_engine


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _proposal(
    *,
    target_type="goal",
    title="Have $1 million in the bank by 31/12/2030",
    success="Have $1 million in the bank",
    deadline="2030-12-31",
    accounts=None,
    other_goals=None,
):
    snapshot = {
        "target_type": target_type,
        "target_id": "target-1",
        "target": {
            "id": "target-1",
            "title": title,
            "target_outcome": success if target_type == "goal" else "",
            "deadline": deadline if target_type == "goal" else "",
            "target_end_date": deadline if target_type == "project" else "",
        },
        "linked_goal": None,
        "expected_outcomes": [],
        "tasks": [],
        "checkins": [],
        "portfolio": {
            "financial_accounts": accounts or [],
            "active_goals": other_goals or [],
            "active_projects": [],
            "time_commitments": [],
            "monthly_money_commitments": [],
            "resource_allocations": [],
        },
    }
    return {
        "id": "proposal-1",
        "user_id": "user-1",
        "target_type": target_type,
        "target_id": "target-1",
        "snapshot": snapshot,
        "status": "confirmation_required",
        "inferred_context": {
            "objective": title,
            "success_criteria": success or None,
            "target_date": deadline or None,
            "dependencies": None,
            "constraints": None,
            "plan_structure": None,
        },
        "context_overrides": {},
        "context_decisions": {},
        "question_answers": {},
        "draft_plan": {"version": 0, "items": [], "can_apply": False},
        "applied_plan": None,
    }


def _account(account_id, name, value, currency="USD"):
    return {
        "id": account_id,
        "name": name,
        "account_type": "bank",
        "currency": currency,
        "current_value": value,
        "liquidity_type": "liquid",
    }


def _item(public, key):
    for section in public["context_review"]["sections"]:
        for item in section["items"]:
            if item["key"] == key:
                return item
    raise AssertionError(f"missing public review item: {key}")


def test_public_contract_is_human_readable_and_contains_no_private_tokens():
    proposal = _proposal(
        accounts=[_account("bank-1", "Everyday bank", "250000")],
        other_goals=[{"id": "other-1", "title": "Another goal"}],
    )

    public = planning_engine._public_payload(proposal)
    encoded = json.dumps(public)

    assert public["context_review"]["title"] == "Does Hymn understand your situation?"
    assert public["stage"] == "review"
    assert public["next_action"]["action"] == "build_draft"
    assert "verified_structured_field" not in encoded
    assert "evidence_id" not in encoded
    assert '"confidence"' not in encoded
    assert "active_goals_count" not in encoded
    assert "llm" not in encoded.lower()
    for section in public["context_review"]["sections"]:
        for item in section["items"]:
            assert item["value"] is None or isinstance(item["value"], str)
            assert isinstance(item["why"]["summary"], str)
            assert all(isinstance(line, str) for line in item["why"]["evidence"])


def test_unique_owned_liquid_balance_is_used_without_summing_other_values():
    proposal = _proposal(accounts=[
        _account("bank-1", "Goal bank", "250000"),
        {
            **_account("investment-1", "Investments", "900000"),
            "liquidity_type": "semi_liquid",
        },
        {
            **_account("debt-1", "Credit card", "50000"),
            "account_type": "credit_card",
        },
        _account("inr-1", "Rupee bank", "999999", currency="INR"),
    ])

    effective = planning_engine._effective_context(proposal)
    target = planning_engine._parse_financial_target(effective, proposal["snapshot"])
    balance = planning_engine._liquid_balance_context(proposal, effective, target)
    feasibility = planning_engine._human_feasibility(proposal, effective, target, balance)

    assert target["amount"] == Decimal("1000000")
    assert target["currency"] == "USD"
    assert balance["account"]["id"] == "bank-1"
    calculations = {row["label"]: row["value"] for row in feasibility["calculations"]}
    assert calculations["Current recorded balance"] == "USD 250,000.00"
    assert calculations["Remaining gap"] == "USD 750,000.00"
    assert all("1,149,999" not in value for value in calculations.values())


def test_multiple_matching_balances_create_an_inline_selection_question():
    proposal = _proposal(accounts=[
        _account("bank-1", "Everyday bank", "250000"),
        _account("bank-2", "Savings bank", "300000"),
    ])

    public = planning_engine._public_payload(proposal)
    question = next(
        row for row in public["context_review"]["questions"]
        if row["id"] == "balance_account"
    )

    assert public["stage"] == "questions"
    assert question["input_type"] == "select"
    assert {option["value"] for option in question["options"]} == {"bank-1", "bank-2"}
    assert _item(public, "current_balance")["status"] == "missing"
    assert "550,000" not in json.dumps(public)


def test_current_target_is_separate_from_honest_other_goal_count():
    proposal = _proposal(other_goals=[
        {"id": "other-1", "title": "Other one", "status": "active"},
        {"id": "other-2", "title": "Other two", "status": "paused"},
    ])

    public = planning_engine._public_payload(proposal)
    active_item = _item(public, "other_goals")
    paused_item = _item(public, "paused_goals")

    assert active_item["label"] == "Other active goals"
    assert active_item["value"] == "1 other active goal."
    assert paused_item["value"] == "1 other paused goal."
    assert "current goal" in active_item["why"]["summary"].lower()


def test_answered_unknown_required_question_is_not_a_dead_end():
    proposal = _proposal(accounts=[
        _account("bank-1", "Everyday bank", "250000"),
        _account("bank-2", "Savings bank", "300000"),
    ])
    proposal["question_answers"]["balance_account"] = {
        "value": None,
        "recorded_at": "2026-07-26T00:00:00+00:00",
    }

    public = planning_engine._public_payload(proposal)

    assert all(
        question["id"] != "balance_account"
        for question in public["context_review"]["questions"]
    )
    assert public["context_review"]["feasibility"]["status"] == "insufficient_information"


def test_authoritative_edit_does_not_mutate_inference_and_drives_draft():
    proposal = _proposal(
        target_type="project",
        title="Prepare launch",
        success="",
        deadline="2030-12-31",
    )
    original = deepcopy(proposal["inferred_context"])

    planning_engine._save_override(
        proposal, "success_criteria", "Release checklist passes", "user_edit",
    )
    planning_engine._save_override(
        proposal,
        "plan_structure",
        "Run the release checklist; Record the result",
        "user_edit",
    )
    items = planning_engine._make_draft_items(proposal)

    assert proposal["inferred_context"] == original
    assert any(item["title"] == "Release checklist passes" for item in items)
    assert any(item["title"] == "Run the release checklist" for item in items)
    assert any(item["title"] == "Record the result" for item in items)
    assert all("Prepare launch" not in item["title"] or item["kind"] == "milestone" for item in items)


def test_missing_context_is_an_inline_question_not_a_dead_end():
    proposal = _proposal(
        target_type="project",
        title="Prepare launch",
        success="",
        deadline="",
    )

    before = planning_engine._public_payload(proposal)
    assert before["stage"] == "questions"
    assert before["next_action"]["action"] == "answer_questions"
    assert {q["id"] for q in before["context_review"]["questions"]} == {
        "success_criteria",
        "target_date",
    }
    assert all(q["prompt"] and q["help_text"] for q in before["context_review"]["questions"])

    planning_engine._save_override(
        proposal, "success_criteria", "A reviewed launch is ready", "question_answer",
    )
    proposal["question_answers"]["success_criteria"] = {
        "value": "A reviewed launch is ready",
    }
    proposal["question_answers"]["target_date"] = {"value": None}
    after = planning_engine._public_payload(proposal)
    assert after["stage"] == "review"
    assert after["next_action"]["action"] == "build_draft"


def test_draft_replacement_supports_reorder_defer_add_and_remove():
    original = [
        planning_engine.DraftItemInput(
            id="remove-me", kind="task", title="Remove me", position=0,
        ),
        planning_engine.DraftItemInput(
            id="keep-me", kind="outcome", title="Keep me", position=1,
        ),
    ]
    replacement = [
        planning_engine.DraftItemInput(
            id="new-task",
            kind="task",
            title="New task",
            status="deferred",
            position=0,
            parent_id="keep-me",
        ),
        planning_engine.DraftItemInput(
            id="keep-me", kind="outcome", title="Edited outcome", position=1,
        ),
    ]

    assert {item["id"] for item in planning_engine._validate_draft_items(original)} == {
        "remove-me", "keep-me",
    }
    result = planning_engine._validate_draft_items(replacement)
    assert [item["id"] for item in result] == ["new-task", "keep-me"]
    assert result[0]["status"] == "deferred"
    assert result[1]["title"] == "Edited outcome"


def test_invalid_draft_parent_and_invalid_date_are_rejected():
    with pytest.raises(Exception) as parent_error:
        planning_engine._validate_draft_items([
            planning_engine.DraftItemInput(
                id="task-1",
                kind="task",
                title="Task",
                parent_id="someone-elses-item",
            )
        ])
    assert getattr(parent_error.value, "status_code", None) == 400

    proposal = _proposal()
    with pytest.raises(Exception) as date_error:
        planning_engine._save_override(
            proposal, "target_date", "2030-02-30", "user_edit",
        )
    assert getattr(date_error.value, "status_code", None) == 400


def test_apply_response_is_stable_and_returns_to_the_owned_target():
    proposal = _proposal(target_type="project", title="Prepare launch")
    proposal["return_to"] = planning_engine._return_metadata(
        "project", "target-1", "Prepare launch",
    )
    proposal["applied_plan"] = {
        "draft_version": 3,
        "items": [{"id": "task-1", "kind": "task", "title": "Run checks"}],
        "created_outcome_ids": [],
        "created_task_ids": ["created-task-1"],
        "applied_at": "2030-01-01T00:00:00+00:00",
    }

    first = planning_engine._apply_response(proposal, already_applied=False)
    repeated = planning_engine._apply_response(proposal, already_applied=True)

    assert first["created_task_ids"] == repeated["created_task_ids"]
    assert repeated["already_applied"] is True
    assert repeated["return_to"]["route"] == "/projects/target-1"
    assert repeated["attached_plan"]["items"][0]["title"] == "Run checks"


def test_context_review_api_ownership_persistence_and_idempotent_apply():
    marker = uuid.uuid4().hex[:12]
    first_email = f"TEST_planning_review_{marker}@hymn.app"
    second_email = f"TEST_planning_review_other_{marker}@hymn.app"
    user_ids = []
    target_id = None
    proposal_id = None

    def signup(email, name):
        response = requests.post(
            f"{API}/auth/signup",
            json={
                "display_name": name,
                "email": email,
                "password": "TestPass123!",
                "security_question": "Test question?",
                "security_answer": "Test answer",
            },
            timeout=15,
        )
        assert response.status_code == 201, response.text
        user_ids.append(response.json()["user"]["id"])
        return {
            "Authorization": f"Bearer {response.json()['access_token']}",
        }

    db_client = MongoClient(os.environ["MONGO_URL"])
    database = db_client[os.environ["DB_NAME"]]
    try:
        owner = signup(first_email, "Planning Owner")
        other = signup(second_email, "Other Planner")
        domains = requests.get(f"{API}/domains", headers=owner, timeout=15)
        assert domains.status_code == 200, domains.text
        domain_id = domains.json()[0]["id"]

        goal = requests.post(
            f"{API}/goals",
            headers=owner,
            json={
                "title": "Have $1 million in the bank by 31/12/2030",
                "domain_id": domain_id,
                "target_outcome": "Have $1 million in the bank",
                "deadline": "2030-12-31",
                "status": "active",
                "notes": "",
                "checkin_cadence": "",
            },
            timeout=15,
        )
        assert goal.status_code == 201, goal.text
        target_id = goal.json()["id"]

        account = requests.post(
            f"{API}/portfolio/financial-accounts",
            headers=owner,
            json={
                "account_type": "bank",
                "name": "Goal bank",
                "currency": "USD",
                "current_value": "250000",
                "liquidity_type": "liquid",
                "fixed_or_flexible": "flexible",
                "notes": "",
            },
            timeout=15,
        )
        assert account.status_code == 201, account.text

        opened = requests.post(
            f"{API}/planning/context-reviews",
            headers=owner,
            json={"target_type": "goal", "target_id": target_id},
            timeout=15,
        )
        assert opened.status_code == 200, opened.text
        public = opened.json()
        proposal_id = public["id"]
        assert public["stage"] == "review"
        assert "current_state" not in public
        assert "evidence_map" not in public

        reopened = requests.post(
            f"{API}/planning/context-reviews",
            headers=owner,
            json={"target_type": "goal", "target_id": target_id},
            timeout=15,
        )
        assert reopened.status_code == 200
        assert reopened.json()["id"] == proposal_id

        changed = requests.put(
            f"{API}/goals/{target_id}",
            headers=owner,
            json={"notes": "Use only the selected bank balance."},
            timeout=15,
        )
        assert changed.status_code == 200, changed.text
        refreshed = requests.post(
            f"{API}/planning/context-reviews",
            headers=owner,
            json={"target_type": "goal", "target_id": target_id},
            timeout=15,
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["id"] != proposal_id
        proposal_id = refreshed.json()["id"]

        isolated = requests.get(
            f"{API}/planning/context-reviews/{proposal_id}",
            headers=other,
            timeout=15,
        )
        assert isolated.status_code == 404

        corrected = requests.patch(
            f"{API}/planning/proposals/{proposal_id}/context",
            headers=owner,
            json={
                "updates": {
                    "success_criteria": "The selected bank records USD 1 million",
                    "plan_structure": "Review the recorded balance; Log monthly progress",
                }
            },
            timeout=15,
        )
        assert corrected.status_code == 200, corrected.text
        success_item = _item(corrected.json(), "success_criteria")
        assert success_item["value"] == "The selected bank records USD 1 million"
        assert success_item["status"] == "user_edited"

        # Draft persistence is allowed; downstream Goal records are untouched.
        before_outcomes = database.expected_outcomes.count_documents({
            "user_id": user_ids[0],
            "goal_id": target_id,
        })
        before_tasks = database.tasks.count_documents({"user_id": user_ids[0]})
        drafted = requests.post(
            f"{API}/planning/proposals/{proposal_id}/draft",
            headers=owner,
            timeout=15,
        )
        assert drafted.status_code == 200, drafted.text
        draft = drafted.json()["draft_plan"]
        assert draft["can_apply"] is True
        assert any(item["title"] == "The selected bank records USD 1 million" for item in draft["items"])
        assert any(item["title"] == "Review the recorded balance" for item in draft["items"])
        assert database.expected_outcomes.count_documents({
            "user_id": user_ids[0],
            "goal_id": target_id,
        }) == before_outcomes
        assert database.tasks.count_documents({"user_id": user_ids[0]}) == before_tasks

        acknowledged = requests.post(
            f"{API}/planning/proposals/{proposal_id}/context/objective/decision",
            headers=owner,
            json={"action": "looks_right"},
            timeout=15,
        )
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["draft_plan"]["version"] == draft["version"]
        assert acknowledged.json()["draft_plan"]["items"] == draft["items"]

        applied = requests.post(
            f"{API}/planning/proposals/{proposal_id}/apply",
            headers=owner,
            timeout=15,
        )
        assert applied.status_code == 200, applied.text
        first_apply = applied.json()
        assert first_apply["already_applied"] is False
        assert first_apply["return_to"]["route"] == f"/goals/{target_id}"
        assert first_apply["created_outcome_ids"]
        assert first_apply["created_task_ids"]

        repeated = requests.post(
            f"{API}/planning/proposals/{proposal_id}/apply",
            headers=owner,
            timeout=15,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["already_applied"] is True
        assert repeated.json()["created_outcome_ids"] == first_apply["created_outcome_ids"]
        assert repeated.json()["created_task_ids"] == first_apply["created_task_ids"]

        attached = requests.get(
            f"{API}/planning/targets/goal/{target_id}/attached-plan",
            headers=owner,
            timeout=15,
        )
        assert attached.status_code == 200, attached.text
        assert attached.json()["attached"] is True
        assert attached.json()["proposal_id"] == proposal_id

        saved_goal = database.goals.find_one(
            {"id": target_id, "user_id": user_ids[0]},
        )
        assert saved_goal["planning_plan_id"] == proposal_id
        assert database.expected_outcomes.count_documents({
            "id": {"$in": first_apply["created_outcome_ids"]},
            "user_id": user_ids[0],
        }) == len(first_apply["created_outcome_ids"])
        assert database.tasks.count_documents({
            "id": {"$in": first_apply["created_task_ids"]},
            "user_id": user_ids[0],
        }) == len(first_apply["created_task_ids"])
    finally:
        if user_ids:
            proposal_ids = [
                row["id"]
                for row in database.plan_proposals.find(
                    {"user_id": {"$in": user_ids}},
                    {"id": 1},
                )
            ]
            database.plan_action_log.delete_many({
                "proposal_id": {"$in": proposal_ids},
            })
            database.plan_proposals.delete_many({"user_id": {"$in": user_ids}})
            database.tasks.delete_many({"user_id": {"$in": user_ids}})
            database.expected_outcomes.delete_many({"user_id": {"$in": user_ids}})
            database.financial_accounts.delete_many({"user_id": {"$in": user_ids}})
            database.goals.delete_many({"user_id": {"$in": user_ids}})
            database.domains.delete_many({"user_id": {"$in": user_ids}})
            database.users.delete_many({"id": {"$in": user_ids}})
        db_client.close()
