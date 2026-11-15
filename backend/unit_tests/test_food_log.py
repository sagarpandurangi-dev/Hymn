"""Food log: built-in list, photo → confirm → save, portions into Health, calories as a range."""
from __future__ import annotations

import base64
from datetime import date

import pytest

import food_ai
import food_catalog
from claude_client import AssistantUnavailable
from food_ai import Label, PhotoItem, PhotoReading

TODAY = date.today().isoformat()
IMG = base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()
EMPTY_LABEL = Label(product_name="", serving_size="", kcal="", protein_g="", carbs_g="", fat_g="", sugar_g="")


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/signup", json={"name": "Fd", "email": "food@example.com",
                                              "password": "correct-horse-battery", "security_question": "Q?",
                                              "security_answer": "A"})
    b = r.json()
    h = {"Authorization": f"Bearer {b['access_token']}"}
    client.put("/api/health/profile", headers=h, json={"consent": True})
    return {"id": b["user"]["id"], "headers": h}


def _plate(*items):
    async def fake(image, media_type):
        return PhotoReading(kind="plate", items=[PhotoItem(food_id=i, name=n, amount=a, confidence=c)
                                                 for i, n, a, c in items], label=EMPTY_LABEL)
    return fake


def test_the_list_is_internally_consistent():
    # Calories agree with protein, carbs and fat (4/4/9 kcal per gram) within 20% —
    # catches typos. Alcohol is the exception (7 kcal per gram of alcohol).
    for f in food_catalog.FOODS.values():
        if f["id"] in ("beer", "spirits", "wine") or f["kcal"] < 30:
            continue
        est = 4 * f["protein_g"] + 4 * f["carbs_g"] + 9 * f["fat_g"]
        assert abs(est - f["kcal"]) / f["kcal"] <= 0.2, f["id"]
    assert len(food_catalog.FOODS) >= 180 and food_catalog.VALUES_REVIEWED is False


def test_search_finds_indian_names_and_partial_words():
    ids = lambda q: [f["id"] for f in food_catalog.search(q)]
    assert ids("chapati")[0] == "roti" and ids("dahi")[0] == "curd" and ids("maggi") == ["instant_noodles"]
    assert ids("idly")[0] == "idli" and ids("chai")[0] == "chai" and "chicken_biryani" in ids("biry")
    assert ids("palya")[0] == "mixed_veg" and ids("") == []


def test_photo_to_confirmed_meal_feeds_health(client, user, monkeypatch):
    h = user["headers"]
    monkeypatch.setattr(food_ai, "read_photo", _plate(("roti", "roti", 2, "high"), ("dal", "dal", 1, "high"),
                                                      ("", "bhindi fry", 1, "medium"),
                                                      ("made_up", "gulab jamun", 1.2, "low")))
    r = client.post("/api/food/photo", headers=h, json={"image_base64": IMG}).json()
    assert r["kind"] == "plate" and r["photos_left"] == 29
    roti, dal, bhindi, sweet = r["items"]
    assert roti["food"]["id"] == "roti" and roti["nutrition"]["kcal"] == 210          # 2 × 105, from the list
    assert roti["nutrition"]["kcal_low"] == 170 and roti["nutrition"]["kcal_high"] == 260
    assert bhindi["food"]["id"] == "bhindi"                                           # matched by name
    assert sweet["food"]["id"] == "gulab_jamun" and sweet["amount"] == 1.0            # bad id → name; halves
    meal = client.post("/api/food/meals", headers=h, json={
        "date": TODAY, "meal": "lunch", "from_photo": True,
        "items": [{"food_id": "roti", "amount": 2}, {"food_id": "dal", "amount": 1},
                  {"food_id": "bhindi", "amount": 1}, {"food_id": "gulab_jamun", "amount": 1},
                  {"name": "Grandma's chutney"}]}).json()
    assert meal["items"][-1]["not_counted"] is True
    client.post("/api/food/meals", headers=h, json={"date": TODAY, "meal": "snack", "outside": True,
                                                    "items": [{"food_id": "samosa", "amount": 2}]})
    day = client.get(f"/api/food/day?date={TODAY}", headers=h).json()
    assert [m["meal"] for m in day["meals"]] == ["lunch", "snack"]
    p = day["totals"]["portions"]
    assert p == {"veg_fruit_portions": 1.0, "protein_servings": 1.0, "sugary_items": 1.0, "outside_meals": 1}
    assert day["totals"]["calories"]["estimate"] == 1170   # 210 + 150 + 140 + 150 (+0 chutney) + 2 × 260
    assert "rough" in day["totals"]["calories"]["note"]
    # The day's portions land in Health's daily log, which suggestions read.
    rows = {m["metric"]: m for m in client.get("/api/health/measurements", headers=h).json()}
    assert rows["veg_fruit_portions"]["value"] == 1 and rows["outside_meals"]["value"] == 1
    assert rows["sugary_items"]["note"] == "from food log"
    # Deleting a meal re-adds the day: no stale counts.
    client.delete(f"/api/food/meals/{meal['id']}", headers=h)
    rows = {m["metric"]: m["value"] for m in client.get("/api/health/measurements", headers=h).json()}
    assert rows == {"veg_fruit_portions": 0, "protein_servings": 0, "sugary_items": 0, "outside_meals": 1}


def test_food_log_never_duplicates_a_days_portions(client, user):
    h = user["headers"]
    for meal in ("breakfast", "lunch", "dinner"):
        client.post("/api/food/meals", headers=h, json={"date": TODAY, "meal": meal,
                                                        "items": [{"food_id": "banana"}]})
    vals = [m for m in client.get("/api/health/measurements?metric=veg_fruit_portions", headers=h).json()]
    assert [v["value"] for v in vals] == [3]                       # one row per day, the day's total
    # A manual tap in the daily log replaces it (last word wins).
    client.post("/api/health/daily", headers=h, json={"date": TODAY, "veg_fruit_portions": 5})
    vals = client.get("/api/health/measurements?metric=veg_fruit_portions", headers=h).json()
    assert [v["value"] for v in vals] == [5]


def test_eating_disorder_history_shows_portions_only(client, user, monkeypatch):
    h = user["headers"]
    client.put("/api/health/profile", headers=h, json={"consent": True, "eating_disorder_history": True})
    monkeypatch.setattr(food_ai, "read_photo", _plate(("idli", "idli", 3, "high")))
    item = client.post("/api/food/photo", headers=h, json={"image_base64": IMG}).json()["items"][0]
    assert "kcal" not in item["nutrition"] and "protein_g" not in item["nutrition"]
    meal = client.post("/api/food/meals", headers=h, json={"date": TODAY, "meal": "breakfast",
                                                           "items": [{"food_id": "idli", "amount": 3}]}).json()
    assert "kcal" not in meal["items"][0]["nutrition"]
    day = client.get(f"/api/food/day?date={TODAY}", headers=h).json()
    assert day["totals"]["calories"] is None and "protein_g" not in day["totals"]


def test_labels_become_your_own_foods(client, user, monkeypatch):
    h = user["headers"]

    async def label(image, media_type):
        return PhotoReading(kind="label", items=[], label=Label(product_name="Protein bar", serving_size="40 g",
                                                                kcal="180", protein_g="12", carbs_g="20",
                                                                fat_g="6", sugar_g="9"))
    monkeypatch.setattr(food_ai, "read_photo", label)
    r = client.post("/api/food/photo", headers=h, json={"image_base64": IMG}).json()
    assert r["kind"] == "label" and r["label"]["kcal"] == "180"
    mine = client.post("/api/food/my-foods", headers=h, json={"name": "Protein bar", "unit": "bar", "kcal": 180,
                                                              "protein_g": 12, "carbs_g": 20, "fat_g": 6,
                                                              "protein_servings": 1, "sugary": True}).json()
    assert mine["id"].startswith("my_") and mine["custom"] is True
    assert client.get("/api/food/search?q=protein", headers=h).json()[0]["id"] == mine["id"]
    m = client.post("/api/food/meals", headers=h, json={"date": TODAY, "meal": "snack",
                                                        "items": [{"food_id": mine["id"]}]}).json()
    assert m["totals"]["calories"]["estimate"] == 180 and m["totals"]["portions"]["sugary_items"] == 1
    # Someone else can't use it.
    other = client.post("/api/auth/signup", json={"name": "O", "email": "o@example.com",
                                                  "password": "correct-horse-battery", "security_question": "Q?",
                                                  "security_answer": "A"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    client.put("/api/health/profile", headers=oh, json={"consent": True})
    assert client.post("/api/food/meals", headers=oh, json={"date": TODAY, "meal": "snack",
                                                            "items": [{"food_id": mine["id"]}]}).status_code == 400


def test_photo_allowance_outages_and_consent(client, user, monkeypatch):
    h = user["headers"]
    monkeypatch.setenv("HYMN_FOOD_PHOTOS_FREE", "1")

    async def down(image, media_type):
        raise AssistantUnavailable("x")
    monkeypatch.setattr(food_ai, "read_photo", down)
    r = client.post("/api/food/photo", headers=h, json={"image_base64": IMG})
    assert r.status_code == 503 and "by name" in r.json()["detail"]        # failures don't use the allowance
    monkeypatch.setattr(food_ai, "read_photo", _plate(("apple", "apple", 1, "high")))
    assert client.post("/api/food/photo", headers=h, json={"image_base64": IMG}).json()["photos_left"] == 0
    r = client.post("/api/food/photo", headers=h, json={"image_base64": IMG})
    assert r.status_code == 429 and "search" in r.json()["detail"]
    assert client.post("/api/food/photo", headers=h, json={"image_base64": "not base64!!"}).status_code in (400, 429)
    # No health consent → no food log.
    other = client.post("/api/auth/signup", json={"name": "N", "email": "n@example.com",
                                                  "password": "correct-horse-battery", "security_question": "Q?",
                                                  "security_answer": "A"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.post("/api/food/meals", headers=oh, json={"date": TODAY, "meal": "lunch",
                                                            "items": [{"food_id": "rice"}]}).status_code == 403


def test_delete_all_health_data_removes_food(client, user):
    h = user["headers"]
    client.post("/api/food/my-foods", headers=h, json={"name": "Mom's ladoo", "kcal": 150})
    client.post("/api/food/meals", headers=h, json={"date": TODAY, "meal": "lunch", "items": [{"food_id": "rice"}]})
    client.delete("/api/health/all", headers=h)
    client.put("/api/health/profile", headers=h, json={"consent": True})
    assert client.get(f"/api/food/day?date={TODAY}", headers=h).json()["meals"] == []
    assert client.get("/api/food/my-foods", headers=h).json() == []
