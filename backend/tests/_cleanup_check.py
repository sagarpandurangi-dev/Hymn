import os, requests
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email":"test@hymn.app","password":"TestPass123!"})
tok = r.json().get("token") or r.json().get("access_token")
s.headers.update({"Authorization": f"Bearer {tok}"})
tasks = s.get(f"{BASE}/api/tasks", params={"includeCompleted":"true"}).json()
leftover_tasks = [t for t in tasks if t.get("title","").startswith("TEST_")]
print(f"Leftover TEST_ tasks: {len(leftover_tasks)}")
for t in leftover_tasks:
    print("  del task", t["id"], t["title"], t.get("due_date"))
    s.delete(f"{BASE}/api/tasks/{t['id']}")
goals = s.get(f"{BASE}/api/goals").json()
leftover_goals = [g for g in goals if g.get("title","").startswith("TEST_")]
print(f"Leftover TEST_ goals: {len(leftover_goals)}")
for g in leftover_goals:
    print("  del goal", g["id"], g["title"])
    s.delete(f"{BASE}/api/goals/{g['id']}")
# Verify
tasks2 = s.get(f"{BASE}/api/tasks", params={"includeCompleted":"true"}).json()
goals2 = s.get(f"{BASE}/api/goals").json()
print("After sweep — TEST_ tasks:", sum(1 for t in tasks2 if t.get("title","").startswith("TEST_")))
print("After sweep — TEST_ goals:", sum(1 for g in goals2 if g.get("title","").startswith("TEST_")))
