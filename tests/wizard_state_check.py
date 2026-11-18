# Read-only check of qa.wizard1 server state on production backend (work roles, sleep blocks, people, setup status)
import sys
import requests
from collections import Counter

B = "https://hymn-production-4828.up.railway.app/api"
email = sys.argv[1] if len(sys.argv) > 1 else "qa.wizard1@hymn.app"
pw = sys.argv[2] if len(sys.argv) > 2 else "QaWizard2026!"
r = requests.post(f"{B}/auth/login", json={"email": email, "password": pw}, timeout=30)
print("login", r.status_code)
j = r.json()
tok = j["access_token"]
u = j["user"]
print("user id", u.get("id"), "completed_at", u.get("portfolio_setup_completed_at"))
H = {"Authorization": f"Bearer {tok}"}
for path in ["/work/roles", "/people", "/portfolio/setup-status", "/nudges/settings"]:
    x = requests.get(B + path, headers=H, timeout=30)
    print(path, x.status_code, str(x.json())[:400])
tc = requests.get(B + "/portfolio/time-commitments", headers=H, timeout=30).json()
sleep = [c for c in tc if c.get("commitment_type") == "sleep"]
print("total commitments", len(tc), "sleep", len(sleep))
cnt = Counter(c["day_of_week"] for c in sleep)
print("sleep per day", dict(cnt))
print("DUPLICATES" if any(v > 1 for v in cnt.values()) else "no duplicate sleep days")
for c in sleep:
    print("  ", c.get("id"), c["day_of_week"], c.get("start_time"), c.get("end_time"))
