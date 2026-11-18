# Prints GET /api/nudges/settings for a user against the production backend used by the frontend
import json
import sys

import requests

BASE = "https://hymn-production-4828.up.railway.app/api"
email = sys.argv[1] if len(sys.argv) > 1 else "qa.tester@hymn.app"
pw = sys.argv[2] if len(sys.argv) > 2 else "QaTester2026!"
r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
print("login", r.status_code, r.text[:200] if r.status_code != 200 else "")
if r.status_code != 200:
    sys.exit(0)
tok = r.json().get("token") or r.json().get("access_token")
h = {"Authorization": f"Bearer {tok}"}
s = requests.get(f"{BASE}/nudges/settings", headers=h, timeout=30)
print("settings", s.status_code)
print(json.dumps(s.json(), indent=1)[:3000])
n = requests.get(f"{BASE}/nudges?limit=20", headers=h, timeout=30)
print("nudges", n.status_code, n.text[:400])
