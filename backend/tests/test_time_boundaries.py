"""Focused API-boundary and capacity tests for strict 24-hour times."""

import os
import uuid

import pytest
import requests


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _payload(title: str, start_time: str, end_time: str) -> dict:
    return {
        "title": title,
        "day_of_week": "wednesday",
        "start_time": start_time,
        "end_time": end_time,
        "commitment_type": "work",
        "flexibility": "fixed",
        "effective_from": "2026-01-01",
    }


@pytest.fixture(scope="module")
def token() -> str:
    email = f"TEST_time_boundaries_{uuid.uuid4().hex[:10]}@hymn.app"
    response = requests.post(
        f"{API}/auth/signup",
        json={
            "email": email,
            "password": "TestPass123!",
            "security_question": "q?",
            "security_answer": "a",
        },
        timeout=10,
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_accepts_00_00_through_23_59(token):
    response = requests.post(
        f"{API}/portfolio/time-commitments",
        json=_payload("TEST_valid_boundaries", "00:00", "23:59"),
        headers=_headers(token),
        timeout=10,
    )
    assert response.status_code == 201, response.text
    commitment_id = response.json()["id"]

    delete = requests.delete(
        f"{API}/portfolio/time-commitments/{commitment_id}",
        headers=_headers(token),
        timeout=10,
    )
    assert delete.status_code == 200


def test_rejects_invalid_hours_and_minutes_without_persisting(token):
    invalid_values = ("24:00", "25:00", "-1:00", "23:60", "12:99")
    for index, invalid_time in enumerate(invalid_values):
        title = f"TEST_invalid_time_{index}"
        response = requests.post(
            f"{API}/portfolio/time-commitments",
            json=_payload(title, "00:00", invalid_time),
            headers=_headers(token),
            timeout=10,
        )
        assert response.status_code == 400, (invalid_time, response.text)

    listed = requests.get(
        f"{API}/portfolio/time-commitments",
        headers=_headers(token),
        timeout=10,
    )
    assert listed.status_code == 200
    assert not any(item["title"].startswith("TEST_invalid_time_") for item in listed.json())

    capacity = requests.get(
        f"{API}/portfolio/time-capacity/day",
        params={"date": "2026-01-07"},
        headers=_headers(token),
        timeout=10,
    )
    assert capacity.status_code == 200
    assert capacity.json()["committed_minutes"] == 0


def test_valid_overlapping_intervals_keep_union_math(token):
    ids = []
    for title, start_time, end_time in (
        ("TEST_overlap_one", "08:00", "10:00"),
        ("TEST_overlap_two", "09:00", "11:00"),
    ):
        response = requests.post(
            f"{API}/portfolio/time-commitments",
            json=_payload(title, start_time, end_time),
            headers=_headers(token),
            timeout=10,
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])

    capacity = requests.get(
        f"{API}/portfolio/time-capacity/day",
        params={"date": "2026-01-07"},
        headers=_headers(token),
        timeout=10,
    )
    assert capacity.status_code == 200
    assert capacity.json()["committed_minutes"] == 180
    assert capacity.json()["overlapping_minutes"] == 60

    for commitment_id in ids:
        delete = requests.delete(
            f"{API}/portfolio/time-commitments/{commitment_id}",
            headers=_headers(token),
            timeout=10,
        )
        assert delete.status_code == 200
