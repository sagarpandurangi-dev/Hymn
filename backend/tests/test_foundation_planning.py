"""Focused tests for provider-neutral deterministic Foundation generation."""

import os
import socket
import uuid

import planning_engine
import requests
from pymongo import MongoClient


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _compact_context():
    return {
        "target_type": "project",
        "target_id": "project-1",
        "target_summary": {"title": "Prepare the Foundation release"},
        "resolved_context": {
            "objective": {
                "value": "Prepare the Foundation release",
                "evidence_id": "e-objective",
                "evidence": "verified_structured_field",
                "confidence": "high",
                "blocking": False,
            },
            "success_criteria": {
                "value": "All release checks pass",
                "evidence_id": "e-success",
                "evidence": "user_confirmed",
                "confidence": "high",
                "blocking": False,
            },
        },
        "existing_expected_outcomes": [],
        "existing_tasks": [],
        "existing_knowledge_stages": [],
        "existing_knowledge_components": [],
        "capacity": {
            "time": {"status": "unknown"},
            "money": {"by_currency": [], "has_unknown_due_dates": False},
        },
        "portfolio_summary": {
            "active_goals_count": 0,
            "active_projects_count": 1,
        },
    }


def test_local_generator_is_deterministic_and_contract_preserving():
    first = planning_engine._generate_plan_locally(
        _compact_context(), "project", "project-1",
    )
    second = planning_engine._generate_plan_locally(
        _compact_context(), "project", "project-1",
    )

    assert first.model_dump() == second.model_dump()
    assert first.objective_summary == "Prepare the Foundation release"
    assert first.measurable_success_criteria == "All release checks pass"
    assert first.proposed_tasks == []
    assert first.proposed_outcomes == []
    assert first.blocking_questions[0].field == "plan_items"


def test_local_generator_never_opens_a_network_connection(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("planning generation attempted outbound network access")

    monkeypatch.setattr(socket, "create_connection", fail_if_called)

    result = planning_engine._generate_plan_locally(
        _compact_context(), "project", "project-1",
    )

    assert result.blocking_questions


def test_generate_endpoint_returns_controlled_local_result():
    email = f"TEST_foundation_planning_{uuid.uuid4().hex[:12]}@hymn.app"
    signup = requests.post(
        f"{API}/auth/signup",
        json={
            "email": email,
            "password": "TestPass123!",
            "security_question": "q?",
            "security_answer": "a",
        },
        timeout=15,
    )
    assert signup.status_code == 201, signup.text
    user_id = signup.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    project = requests.post(
        f"{API}/projects",
        json={
            "title": "Prepare Foundation release",
            "description": "",
            "status": "active",
            "start_date": "2026-07-25",
            "target_end_date": "2026-12-31",
            "notes": "",
        },
        headers=headers,
        timeout=15,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    analyzed = requests.post(
        f"{API}/planning/analyze",
        json={"target_type": "project", "target_id": project_id},
        headers=headers,
        timeout=15,
    )
    assert analyzed.status_code == 200, analyzed.text
    proposal = analyzed.json()

    confirmations = []
    for fact in proposal["current_state"]:
        if not fact.get("blocking"):
            continue
        value = "All Foundation checks pass" if fact["field"] == "success_criteria" else fact.get("value")
        confirmations.append(
            {
                "field": fact["field"],
                "action": "edit",
                "value": value,
            }
        )

    confirmed = requests.post(
        f"{API}/planning/proposals/{proposal['id']}/confirm",
        json={"confirmations": confirmations},
        headers=headers,
        timeout=15,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["ready_to_generate"] is True

    generated = requests.post(
        f"{API}/planning/proposals/{proposal['id']}/generate",
        headers=headers,
        timeout=15,
    )
    assert generated.status_code == 200, generated.text
    result = generated.json()
    assert result["status"] == "blocking_input_required"
    assert result["objective_summary"] == "Prepare Foundation release"
    assert result["measurable_success_criteria"] == "All Foundation checks pass"
    assert result["proposed_tasks"] == []
    assert result["approval_actions"] == []
    assert result["validation_errors"] == []
    assert result["blocking_questions"][0]["field"] == "plan_items"

    client = MongoClient(os.environ["MONGO_URL"])
    try:
        database = client[os.environ["DB_NAME"]]
        database.plan_proposals.delete_many({"user_id": user_id})
        database.projects.delete_many({"user_id": user_id})
        database.users.delete_one({"id": user_id})
    finally:
        client.close()
