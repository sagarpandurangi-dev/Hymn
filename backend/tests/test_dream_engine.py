"""Universal Dream Engine: deterministic reasoning, tree safety, and API flow."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import asyncio
import json
import os
import random
import time
import uuid

import pytest
import requests
from bson.decimal128 import Decimal128
from fastapi import HTTPException
from pydantic import ValidationError
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

import dream_engine
from dream_providers import (
    IntentInterpretationRequest,
    IntentInterpretationResult,
    PlanSynthesisRequest,
    ProviderUnavailableError,
)


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _interpret(text: str, shape: str | None = None) -> dict:
    return dream_engine.deterministic_interpretation(
        text,
        "2026-07-27",
        shape,
    ).model_dump()


def _context(
    *,
    currency: str | None = None,
    liquid: str | None = None,
    unresolved: dict | None = None,
) -> dict:
    return {
        "finance": {
            "requested_currency": currency,
            "recorded_liquid_total": liquid,
            "unresolved_movements": unresolved or {},
        },
        "commitments": {
            "other_active_goals": [],
            "other_active_projects": [],
        },
    }


def _node(
    node_id: str,
    kind: str,
    title: str,
    parent_id: str | None = None,
    rank: int = 1024,
    origin: str = "user",
    state: str = "accepted",
) -> dict:
    return {
        "id": node_id,
        "kind": kind,
        "parent_id": parent_id,
        "rank": rank,
        "title": title,
        "description": "",
        "origin": origin,
        "decision_state": state,
        "timing": None,
        "dependencies": [],
        "evidence_ids": [],
        "assumptions": [],
        "checkin": (
            {
                "schedule_type": "manual",
                "question": "What changed?",
                "evidence_type": "note",
            }
            if kind == "checkin_requirement" else None
        ),
        "revision": 1,
        "created_at": "2026-07-27T00:00:00+00:00",
        "updated_at": "2026-07-27T00:00:00+00:00",
    }


def test_journey_classification_alternatives_and_authoritative_override():
    result = _interpret("I want to attain my CA qualification")
    assert result["primary"]["journey_shape"] == "professional_qualification"
    assert result["alternatives"]
    assert result["provider_kind"] == "deterministic"

    overridden = _interpret(
        "I want to attain my CA qualification",
        "custom",
    )
    assert overridden["primary"]["journey_shape"] == "custom"
    assert overridden["primary"]["confidence"] == "clear"
    assert "You chose" in overridden["primary"]["reason"]
    assert next(
        fact for fact in overridden["facts"] if fact["key"] == "journey_shape"
    )["origin"] == "user_corrected"


def test_custom_journey_is_available_for_arbitrary_words_without_invention():
    result = _interpret("Make Sunday feel less rushed")
    assert result["primary"]["journey_shape"] == "custom"
    assert next(
        fact for fact in result["facts"] if fact["key"] == "desired_outcome"
    )["value"] == "Make Sunday feel less rushed"
    assert not any(fact["key"] == "amount" for fact in result["facts"])
    assert any(row["journey_shape"] == "custom" for row in result["alternatives"]) is False


def test_purchase_facts_reuse_canonical_parser_and_preserve_original_words():
    result = _interpret("Buy an iPad for INR 80,000 by 2030-12-15")
    facts = {row["key"]: row for row in result["facts"]}
    assert result["primary"]["journey_shape"] == "purchase"
    assert facts["desired_object"]["value"] == "iPad"
    assert facts["amount"]["value"] == "80000.00"
    assert facts["currency"]["value"] == "INR"
    assert facts["deadline"]["value"] == "2030-12-15"
    assert facts["desired_outcome"]["value"] == "Buy an iPad for INR 80,000 by 2030-12-15"


def test_general_interpretation_extracts_only_explicit_subject_context_and_safe_date():
    result = _interpret(
        "Learn conversational Spanish for my partner by 31/12/2030 "
        "without weekday classes; I prefer weekend practice"
    )
    facts = {row["key"]: row["value"] for row in result["facts"]}
    assert facts["desired_object"] == "conversational Spanish for my partner"
    assert facts["beneficiary"] == "my partner"
    assert facts["deadline"] == "2030-12-31"
    assert facts["constraints"] == "without weekday classes"
    assert facts["preferences"] == "I prefer weekend practice"

    ambiguous = _interpret("Learn Spanish by 01/02/2030")
    ambiguous_facts = {row["key"]: row["value"] for row in ambiguous["facts"]}
    assert "deadline" not in ambiguous_facts
    assert any("day/month or month/day" in row for row in ambiguous["uncertainties"])


def test_financial_target_extracts_scaled_money_without_confusing_the_year():
    result = _interpret(
        "Have $1 million in the bank by 31/12/2030",
        "financial_target",
    )
    facts = {row["key"]: row["value"] for row in result["facts"]}
    assert facts["amount"] == "1000000.00"
    assert facts["currency"] == "USD"
    assert facts["deadline"] == "2030-12-31"


def test_corrections_are_authoritative_without_mutating_original_text_fact():
    interpretation = _interpret("Buy a laptop for $1,200")
    original = deepcopy(interpretation)
    corrected = dream_engine.apply_fact_corrections(
        interpretation,
        None,
        {"amount": "950", "currency": "USD", "desired_object": "Refurbished laptop"},
    )
    facts = {row["key"]: row for row in corrected["facts"]}
    assert facts["amount"]["value"] == "950.00"
    assert facts["amount"]["origin"] == "user_corrected"
    assert facts["desired_object"]["value"] == "Refurbished laptop"
    assert interpretation == original
    assert facts["desired_outcome"]["value"] == original["facts"][0]["value"]


def test_relative_financial_burden_is_person_specific_and_currency_safe():
    million = _interpret("Buy an iPhone for $1,000")
    light = dream_engine.relative_scale(
        million, _context(currency="USD", liquid="1000000"), "2026-07-27",
    )
    assert next(axis for axis in light["axes"] if axis["id"] == "financial")["level"] == "light"

    gap = _interpret("Buy a phone for INR 1000")
    major = dream_engine.relative_scale(
        gap, _context(currency="INR", liquid="100"), "2026-07-27",
    )
    assert next(axis for axis in major["axes"] if axis["id"] == "financial")["level"] in {
        "major", "transformational",
    }
    assert "exceeds" in next(
        axis for axis in major["axes"] if axis["id"] == "financial"
    )["summary"]

    missing_price = _interpret("Buy a Ferrari")
    unknown = dream_engine.relative_scale(
        missing_price, _context(currency="USD", liquid="1000000"), "2026-07-27",
    )
    assert next(axis for axis in unknown["axes"] if axis["id"] == "financial")["level"] is None

    mismatch = _interpret("Buy a Ferrari for $300,000")
    incompatible = dream_engine.relative_scale(
        mismatch, _context(currency="INR", liquid="100000000"), "2026-07-27",
    )
    financial = next(axis for axis in incompatible["axes"] if axis["id"] == "financial")
    assert financial["level"] is None
    assert "No compatible" in financial["summary"]


def test_unresolved_money_movement_is_disclosed_without_silent_adjustment():
    interpretation = _interpret("Buy a tablet for INR 10000")
    scale = dream_engine.relative_scale(
        interpretation,
        _context(currency="INR", liquid="50000", unresolved={"INR": "700.00"}),
        "2026-07-27",
    )
    financial = next(axis for axis in scale["axes"] if axis["id"] == "financial")
    assert "700.00" in financial["summary"]
    assert "less certain" in financial["summary"]
    liquid_line = next(
        row for row in scale["calculations"]
        if row["label"] == "Compatible recorded liquid resources"
    )
    assert liquid_line["value"] == "INR 50000.00"


def test_simple_plan_has_no_artificial_phase_and_long_plan_is_phased():
    purchase = _interpret("Buy an iPad for $1000 by 2026-12-15")
    simple_scale = dream_engine.relative_scale(
        purchase, _context(currency="USD", liquid="1000000"), "2026-07-27",
    )
    simple = dream_engine.deterministic_plan(purchase, _context(), simple_scale)
    assert not any(node["kind"] == "phase" for node in simple)
    assert any(node["kind"] == "checkin_requirement" for node in simple)

    custom = _interpret("Build a new career over the next five years", "custom")
    long_scale = {
        "recommended_depth": "transformational",
        "user_selected_depth": None,
    }
    phased = dream_engine.deterministic_plan(custom, _context(), long_scale)
    assert len([node for node in phased if node["kind"] == "phase"]) == 3
    assert all(
        node["parent_id"] is not None
        for node in phased
        if node["kind"] == "checkin_requirement"
    )


def test_user_provided_plan_wording_is_preserved():
    interpretation = _interpret("Prepare for a long journey", "custom")
    supplied = [
        _node("p1", "phase", "My exact first phase"),
        _node("m1", "milestone", "My exact milestone", "p1"),
        _node("t1", "task", "My exact task", "m1"),
    ]
    result = dream_engine.deterministic_plan(
        interpretation,
        _context(),
        {"recommended_depth": "major", "user_selected_depth": None},
        supplied,
    )
    assert [row["title"] for row in result] == [
        "My exact first phase", "My exact milestone", "My exact task",
    ]
    assert all(row["origin"] == "user" for row in result)


def test_insert_phase_two_renumbers_without_changing_stable_ids_or_children():
    nodes = [
        _node("p1", "phase", "Phase A", rank=1024),
        _node("m1", "milestone", "A milestone", "p1"),
        _node("p2", "phase", "Phase B", rank=2048),
        _node("m2", "milestone", "B milestone", "p2"),
        _node("p3", "phase", "Phase C", rank=3072),
    ]
    result = dream_engine.apply_tree_operation(nodes, {
        "type": "add",
        "parent_id": None,
        "relative_id": "p2",
        "placement": "before",
        "node": _node("inserted", "phase", "Inserted Phase"),
    })
    display = {row["id"]: row for row in dream_engine.display_plan_tree(result)}
    assert display["inserted"]["display_number"] == "2"
    assert display["p2"]["display_number"] == "3"
    assert display["m2"]["display_number"] == "3.1"
    assert display["m2"]["parent_id"] == "p2"


def test_add_phase_five_insert_milestone_and_move_subtree_intact():
    nodes = [
        _node(f"p{i}", "phase", f"Phase {i}", rank=i * 1024)
        for i in range(1, 5)
    ]
    nodes.extend([
        _node("m4", "milestone", "Fourth milestone", "p4"),
        _node("t4", "task", "Fourth task", "m4"),
    ])
    with_five = dream_engine.apply_tree_operation(nodes, {
        "type": "add",
        "parent_id": None,
        "placement": "inside_end",
        "node": _node("p5", "phase", "Phase 5"),
    })
    with_milestone = dream_engine.apply_tree_operation(with_five, {
        "type": "add",
        "parent_id": "p1",
        "relative_id": None,
        "placement": "inside_end",
        "node": _node("m11", "milestone", "Milestone 1.1", "p1"),
    })
    moved = dream_engine.apply_tree_operation(with_milestone, {
        "type": "move",
        "node_id": "p4",
        "parent_id": None,
        "relative_id": "p2",
        "placement": "before",
    })
    display = {row["id"]: row for row in dream_engine.display_plan_tree(moved)}
    assert display["p4"]["display_number"] == "2"
    assert display["m4"]["display_number"] == "2.1"
    assert display["t4"]["display_number"] == "2.1.1"
    assert display["p5"]["display_number"] == "5"
    assert display["m11"]["display_number"] == "1.1"


def test_delete_requires_explicit_subtree_choice_and_never_orphans():
    nodes = [
        _node("p1", "phase", "Parent"),
        _node("m1", "milestone", "Child", "p1"),
        _node("t1", "task", "Grandchild", "m1"),
    ]
    with pytest.raises(HTTPException) as blocked:
        dream_engine.apply_tree_operation(nodes, {"type": "delete", "node_id": "p1"})
    assert blocked.value.status_code == 409

    reparented = dream_engine.apply_tree_operation(nodes, {
        "type": "delete",
        "node_id": "p1",
        "delete_mode": "reparent_children",
        "destination_parent_id": None,
    })
    by_id = {node["id"]: node for node in reparented}
    assert "p1" not in by_id
    assert by_id["m1"]["parent_id"] is None
    assert by_id["t1"]["parent_id"] == "m1"

    cascaded = dream_engine.apply_tree_operation(nodes, {
        "type": "delete",
        "node_id": "p1",
        "delete_mode": "remove_subtree",
    })
    assert cascaded == []


@pytest.mark.parametrize(
    "mutator, message",
    [
        (
            lambda rows: [rows[0], {**rows[0]}],
            "unique",
        ),
        (
            lambda rows: [{**rows[0], "parent_id": "missing"}],
            "unknown parent",
        ),
        (
            lambda rows: [
                {**rows[0], "parent_id": "p2"},
                _node("p2", "phase", "Other", "p1"),
            ],
            "cannot be placed",
        ),
    ],
)
def test_tree_rejects_duplicate_or_orphan_or_invalid_parent(mutator, message):
    with pytest.raises(HTTPException) as error:
        dream_engine.validate_plan_tree(mutator([_node("p1", "phase", "Phase")]))
    assert message in error.value.detail.lower()


def test_tree_rejects_hierarchy_dependency_cycles_and_cross_subtree_move():
    parent_cycle = [
        _node("m1", "milestone", "One", "p1"),
        _node("p1", "phase", "Two"),
    ]
    parent_cycle[1]["parent_id"] = "m1"
    with pytest.raises(HTTPException):
        dream_engine.validate_plan_tree(parent_cycle)

    dependencies = [_node("a", "task", "A"), _node("b", "task", "B")]
    dependencies[0]["dependencies"] = ["b"]
    dependencies[1]["dependencies"] = ["a"]
    with pytest.raises(HTTPException) as error:
        dream_engine.validate_plan_tree(dependencies)
    assert "dependencies" in error.value.detail

    subtree = [
        _node("p1", "phase", "Phase"),
        _node("m1", "milestone", "Milestone", "p1"),
    ]
    with pytest.raises(HTTPException) as move_error:
        dream_engine.apply_tree_operation(subtree, {
            "type": "move", "node_id": "p1", "parent_id": "m1",
        })
    assert "descendant" in move_error.value.detail


def test_recompute_preserves_user_created_and_modified_nodes():
    modified = _node(
        "hymn-modified", "task", "My rewritten suggestion",
        origin="hymn", state="modified",
    )
    user = _node("user-node", "task", "My own step")
    fresh = [_node("fresh", "task", "New suggestion", origin="hymn", state="proposed")]
    result = dream_engine.preserve_user_nodes([modified, user], fresh)
    titles = {row["title"] for row in result}
    assert {"My rewritten suggestion", "My own step", "New suggestion"} == titles


def test_required_checkin_is_definition_not_actual_checkin():
    task = _node("task", "task", "Do work")
    requirement = _node("requirement", "checkin_requirement", "Weekly proof", "task")
    valid = dream_engine.validate_plan_tree([task, requirement])
    checkin = next(row for row in valid if row["id"] == "requirement")
    assert checkin["checkin"]["schedule_type"] == "manual"
    assert "date" not in checkin
    assert "notes" not in checkin


def test_randomized_valid_sibling_operations_keep_stable_ids_and_valid_tree():
    rng = random.Random(20260727)
    nodes = [_node(f"p{i}", "phase", f"Phase {i}", rank=i * 1024) for i in range(1, 6)]
    original_ids = {row["id"] for row in nodes}
    for _ in range(100):
        node_id = rng.choice(list(original_ids))
        siblings = dream_engine.display_plan_tree(nodes)
        current = next(row for row in siblings if row["id"] == node_id)
        choices = [row for row in siblings if row["id"] != node_id]
        relative = rng.choice(choices)
        nodes = dream_engine.apply_tree_operation(nodes, {
            "type": "move",
            "node_id": node_id,
            "parent_id": None,
            "relative_id": relative["id"],
            "placement": rng.choice(["before", "after"]),
        })
        assert {row["id"] for row in nodes} == original_ids
        assert len(dream_engine.display_plan_tree(nodes)) == len(original_ids)


def test_public_contract_has_no_raw_owned_rows_or_internal_provenance_codes():
    interpretation = _interpret("Buy an iPad")
    context = {
        **_context(),
        "source": None,
        "domains_queried": ["financial_accounts"],
        "domains_with_data": [],
        "evidence": [],
        "finance": {
            **_context()["finance"],
            "compatible_liquid_accounts": [],
            "recorded_liquid_account_count": 0,
            "balance_label": "Recorded liquid balance",
            "freshness_warning": None,
        },
        "commitments": {
            **_context()["commitments"],
            "open_task_count": 0,
            "recorded_checkin_count": 0,
        },
    }
    scale = dream_engine.relative_scale(interpretation, context, "2026-07-27")
    node = dream_engine.deterministic_plan(interpretation, context, scale)[0]
    proposal = {
        "id": "proposal",
        "schema_version": 1,
        "source": {"type": "intent", "id": None, "title": "Buy an iPad"},
        "status": "review",
        "revision": 1,
        "original_text": "Buy an iPad",
        "interpretation_version": 1,
        "interpretation": interpretation,
        "context": context,
        "scale": scale,
        "research": dream_engine.research_state_for(interpretation),
        "map": {"revision": 1, "nodes": [node], "history": []},
        "creation_preview": {},
        "applied_plan": None,
        "return_to": {
            "route": "/dreams/proposal", "label": "View",
            "target_type": "intent", "target_id": "proposal",
        },
        "updated_at": "now",
    }
    public = dream_engine.public_proposal(proposal)
    encoded = json.dumps(public)
    assert "financial_account:" not in encoded
    assert '"evidence_ids"' not in encoded
    assert '"created_at"' not in encoded
    assert "verified_structured_field" not in encoded
    assert all(
        not isinstance(fact["value"], dict)
        for fact in public["interpretation"]["facts"]
    )


def test_provider_schema_rejects_unexpected_fields_and_failure_has_fallback():
    with pytest.raises(ValidationError):
        IntentInterpretationResult.model_validate({
            "provider_kind": "external",
            "primary": {
                "journey_shape": "custom",
                "label": "Custom",
                "reason": "Suggestion",
                "confidence": "likely",
            },
            "write_to_database": True,
        })

    class FailingProvider:
        async def interpret(self, _request):
            raise ProviderUnavailableError("offline")

    assert not hasattr(FailingProvider(), "db")
    fallback = _interpret("Create my own unusual plan", "custom")
    assert fallback["primary"]["journey_shape"] == "custom"
    assert dream_engine.research_state_for(fallback)["provider_enabled"] is False


def test_local_provider_adapters_are_schema_valid_and_have_no_persistence_capability():
    interpreter = dream_engine.DeterministicIntentInterpretationProvider()
    interpretation = asyncio.run(interpreter.interpret(
        IntentInterpretationRequest(
            original_text="Learn Spanish",
            reference_date="2026-07-27",
        )
    ))
    synthesizer = dream_engine.DeterministicPlanSynthesisProvider()
    result = asyncio.run(synthesizer.synthesize(
        PlanSynthesisRequest(
            interpretation=interpretation,
            approved_context_summary={
                "context": _context(),
                "scale": {
                    "recommended_depth": "moderate",
                    "user_selected_depth": None,
                },
            },
        )
    ))
    assert result.provider_kind == "deterministic"
    assert result.nodes
    assert not hasattr(interpreter, "db")
    assert not hasattr(synthesizer, "db")
    assert all(node.id for node in result.nodes)


def _signup(label: str) -> dict:
    response = requests.post(
        f"{API}/auth/signup",
        json={
            "display_name": f"Dream {label}",
            "email": f"TEST_dream_{label}_{time.time_ns()}@hymn.app",
            "password": "TestPass123!",
            "security_question": "Question?",
            "security_answer": "Answer",
        },
        timeout=15,
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return {
        "id": payload["user"]["id"],
        "headers": {"Authorization": f"Bearer {payload['access_token']}"},
    }


@pytest.fixture(scope="module")
def api_context():
    client = MongoClient(MONGO_URL)
    database = client[DB_NAME]
    primary = _signup("primary")
    other = _signup("other")
    yield {"db": database, "primary": primary, "other": other}
    user_ids = [primary["id"], other["id"]]
    proposal_ids = [
        row["id"] for row in database.dream_proposals.find(
            {"user_id": {"$in": user_ids}}, {"id": 1},
        )
    ]
    map_ids = [
        row["id"] for row in database.active_plan_maps.find(
            {"user_id": {"$in": user_ids}}, {"id": 1},
        )
    ]
    for collection in (
        "required_checkin_requirements", "plan_phases", "active_plan_maps",
        "dream_apply_log", "dream_proposals", "tasks", "expected_outcomes",
        "knowledge_stages", "knowledge_journeys", "projects", "goals",
        "financial_accounts", "financial_events", "domains", "users",
    ):
        database[collection].delete_many({
            "$or": [
                {"user_id": {"$in": user_ids}},
                {"proposal_id": {"$in": proposal_ids}},
                {"plan_map_id": {"$in": map_ids}},
                {"id": {"$in": user_ids}},
            ]
        })
    client.close()


def _api_analyze(context, payload: dict, user="primary"):
    return requests.post(
        f"{API}/dreams/analyze",
        json={
            "reference_date": "2026-07-27",
            **payload,
        },
        headers=context[user]["headers"],
        timeout=20,
    )


def test_api_draft_is_owned_non_domain_persistent_and_stale_safe(api_context):
    database = api_context["db"]
    before = {
        "goals": database.goals.count_documents({"user_id": api_context["primary"]["id"]}),
        "tasks": database.tasks.count_documents({"user_id": api_context["primary"]["id"]}),
        "checkins": database.checkins.count_documents({"user_id": api_context["primary"]["id"]}),
    }
    response = _api_analyze(api_context, {
        "source_type": "intent",
        "text": "Buy an iPad for INR 80000 by 2030-12-15",
    })
    assert response.status_code == 200, response.text
    proposal = response.json()
    after = {
        "goals": database.goals.count_documents({"user_id": api_context["primary"]["id"]}),
        "tasks": database.tasks.count_documents({"user_id": api_context["primary"]["id"]}),
        "checkins": database.checkins.count_documents({"user_id": api_context["primary"]["id"]}),
    }
    assert before == after

    hidden = requests.get(
        f"{API}/dreams/{proposal['id']}",
        headers=api_context["other"]["headers"],
        timeout=15,
    )
    assert hidden.status_code == 404

    accepted = requests.post(
        f"{API}/dreams/{proposal['id']}/map/operations",
        json={
            "expected_revision": proposal["revision"],
            "operation": {"type": "accept_all"},
        },
        headers=api_context["primary"]["headers"],
        timeout=15,
    )
    assert accepted.status_code == 200, accepted.text
    replay_stale = requests.post(
        f"{API}/dreams/{proposal['id']}/map/operations",
        json={
            "expected_revision": proposal["revision"],
            "operation": {"type": "accept_all"},
        },
        headers=api_context["primary"]["headers"],
        timeout=15,
    )
    assert replay_stale.status_code == 409


def test_api_apply_is_idempotent_and_requirements_are_not_checkins(api_context):
    database = api_context["db"]
    response = _api_analyze(api_context, {
        "source_type": "intent",
        "text": "Buy a laptop for USD 1200 by 2030-12-15",
    })
    proposal = response.json()
    accepted = requests.post(
        f"{API}/dreams/{proposal['id']}/map/operations",
        json={
            "expected_revision": proposal["revision"],
            "operation": {"type": "accept_all"},
        },
        headers=api_context["primary"]["headers"],
        timeout=15,
    ).json()
    before_checkins = database.checkins.count_documents({
        "user_id": api_context["primary"]["id"],
    })
    first = requests.post(
        f"{API}/dreams/{proposal['id']}/apply",
        headers=api_context["primary"]["headers"],
        timeout=20,
    )
    assert first.status_code == 200, first.text
    second = requests.post(
        f"{API}/dreams/{proposal['id']}/apply",
        headers=api_context["primary"]["headers"],
        timeout=20,
    )
    assert second.status_code == 200, second.text
    assert second.json()["already_applied"] is True
    assert first.json()["plan_map_id"] == second.json()["plan_map_id"]
    assert database.active_plan_maps.count_documents({
        "proposal_id": proposal["id"],
    }) == 1
    assert database.tasks.count_documents({
        "user_id": api_context["primary"]["id"],
        "plan_map_id": first.json()["plan_map_id"],
    }) == accepted["creation_preview"]["counts"]["task"]
    assert database.required_checkin_requirements.count_documents({
        "user_id": api_context["primary"]["id"],
        "plan_map_id": first.json()["plan_map_id"],
    }) == accepted["creation_preview"]["counts"]["checkin_requirement"]
    assert database.checkins.count_documents({
        "user_id": api_context["primary"]["id"],
    }) == before_checkins


def test_partial_apply_failure_rolls_back_and_a_retry_recovers(api_context):
    user_id = api_context["primary"]["id"]
    proposal_id = str(uuid.uuid4())
    proposal = {
        "id": proposal_id,
        "user_id": user_id,
        "source": {"type": "intent", "id": None, "title": "A recoverable plan"},
        "original_text": "Build a recoverable plan",
        "interpretation": _interpret("Build a recoverable plan", "custom"),
        "scale": {"recommended_depth": "moderate", "user_selected_depth": None},
        "map": {
            "revision": 1,
            "history": [],
            "nodes": [_node("recover-task", "task", "Recoverable task")],
        },
        "status": "review",
        "revision": 1,
        "return_to": {
            "route": f"/dreams/{proposal_id}",
            "label": "View this intention",
            "target_type": "intent",
            "target_id": proposal_id,
        },
        "decision_history": [],
        "updated_at": "2026-07-27T00:00:00+00:00",
    }

    class FailingCollection:
        def __init__(self, collection, state):
            self._collection = collection
            self._state = state

        def __getattr__(self, name):
            return getattr(self._collection, name)

        async def insert_one(self, document):
            if not self._state["failed"]:
                self._state["failed"] = True
                raise RuntimeError("simulated task persistence failure")
            return await self._collection.insert_one(document)

    class FailingDatabase:
        def __init__(self, database):
            self._database = database
            self._state = {"failed": False}

        def __getattr__(self, name):
            collection = getattr(self._database, name)
            if name == "tasks":
                return FailingCollection(collection, self._state)
            return collection

        def __getitem__(self, name):
            return getattr(self, name)

    async def scenario():
        client = AsyncIOMotorClient(MONGO_URL)
        database = client[DB_NAME]
        await database.dream_proposals.insert_one(deepcopy(proposal))
        try:
            with pytest.raises(HTTPException) as failed:
                await dream_engine._apply_plan(
                    FailingDatabase(database),
                    user_id,
                    deepcopy(proposal),
                )
            assert failed.value.status_code == 500
            assert await database.active_plan_maps.count_documents({
                "proposal_id": proposal_id,
            }) == 0
            assert await database.tasks.count_documents({
                "user_id": user_id,
                "plan_node_id": "recover-task",
            }) == 0

            retry_proposal = await database.dream_proposals.find_one(
                {"id": proposal_id}, {"_id": 0},
            )
            result = await dream_engine._apply_plan(database, user_id, retry_proposal)
            assert result["already_applied"] is False
            assert await database.active_plan_maps.count_documents({
                "proposal_id": proposal_id,
            }) == 1
            assert await database.tasks.count_documents({
                "user_id": user_id,
                "plan_node_id": "recover-task",
            }) == 1
        finally:
            await database.tasks.delete_many({
                "user_id": user_id,
                "plan_node_id": "recover-task",
            })
            await database.active_plan_maps.delete_many({"proposal_id": proposal_id})
            await database.dream_apply_log.delete_many({"proposal_id": proposal_id})
            await database.dream_proposals.delete_many({"id": proposal_id})
            client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("source_type", ["goal", "project"])
def test_goal_and_project_entry_attach_without_duplicating_target(api_context, source_type):
    database = api_context["db"]
    now = "2026-07-27T00:00:00+00:00"
    source_id = str(uuid.uuid4())
    if source_type == "goal":
        domain = {
            "id": str(uuid.uuid4()), "user_id": api_context["primary"]["id"],
            "name": f"Dream domain {source_id}", "is_default": False,
            "created_at": now,
        }
        database.domains.insert_one(domain)
        database.goals.insert_one({
            "id": source_id, "user_id": api_context["primary"]["id"],
            "title": "Build a calm launch", "domain_id": domain["id"],
            "target_outcome": "A reviewed launch", "deadline": "2030-12-15",
            "status": "active", "notes": "", "checkin_cadence": "",
            "created_at": now, "updated_at": now,
        })
    else:
        database.projects.insert_one({
            "id": source_id, "user_id": api_context["primary"]["id"],
            "title": "Build a calm launch", "description": "A reviewed launch",
            "status": "active", "start_date": "", "target_end_date": "2030-12-15",
            "notes": "", "checkin_cadence": "",
            "created_at": now, "updated_at": now,
        })

    response = _api_analyze(api_context, {
        "source_type": source_type,
        "source_id": source_id,
    })
    assert response.status_code == 200, response.text
    proposal = response.json()
    accepted = requests.post(
        f"{API}/dreams/{proposal['id']}/map/operations",
        json={
            "expected_revision": proposal["revision"],
            "operation": {"type": "accept_all"},
        },
        headers=api_context["primary"]["headers"],
        timeout=15,
    ).json()
    applied = requests.post(
        f"{API}/dreams/{proposal['id']}/apply",
        headers=api_context["primary"]["headers"],
        timeout=20,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["return_to"]["target_type"] == source_type
    assert applied.json()["return_to"]["target_id"] == source_id
    collection = database.goals if source_type == "goal" else database.projects
    assert collection.count_documents({"id": source_id}) == 1
    target = collection.find_one({"id": source_id})
    assert target["dream_plan_id"] == applied.json()["plan_map_id"]
    assert accepted["creation_preview"]["counts"]["task"] >= 1


def test_learning_entry_creates_one_journey_only_on_apply(api_context):
    database = api_context["db"]
    before = database.knowledge_journeys.count_documents({
        "user_id": api_context["primary"]["id"],
    })
    response = _api_analyze(api_context, {
        "source_type": "learning",
        "text": "Learn conversational Spanish",
        "selected_shape": "learn_skill",
    })
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert database.knowledge_journeys.count_documents({
        "user_id": api_context["primary"]["id"],
    }) == before
    accepted = requests.post(
        f"{API}/dreams/{proposal['id']}/map/operations",
        json={
            "expected_revision": proposal["revision"],
            "operation": {"type": "accept_all"},
        },
        headers=api_context["primary"]["headers"],
        timeout=15,
    ).json()
    applied = requests.post(
        f"{API}/dreams/{proposal['id']}/apply",
        headers=api_context["primary"]["headers"],
        timeout=20,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["return_to"]["target_type"] == "journey"
    assert database.knowledge_journeys.count_documents({
        "user_id": api_context["primary"]["id"],
    }) == before + 1
    assert accepted["creation_preview"]["counts"]["milestone"] >= 1
