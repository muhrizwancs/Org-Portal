"""Run:  python rag/selftest.py     (no database needed)"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rag.engine import answer          # noqa: E402
from rag.seed_knowledge import SEED    # noqa: E402

now = dt.datetime.now()
user = {"name": "Sara Khan", "email": "sara@org.com", "role": "user", "jobTitle": "Analyst",
        "permissions": ["view_reports", "view_dashboard"], "active": True, "createdAt": now,
        "assignments": [{"title": "Q4 report", "description": "Prepare the Q4 summary", "assignedAt": now}]}
admin = {"name": "Boss", "email": "a@org.com", "role": "admin", "jobTitle": "Director",
         "permissions": [], "active": True, "createdAt": now, "assignments": []}
qs = ["what is my role", "who am I?", "what can I use", "what am I used to", "what is assigned to me",
      "what are my tasks", "how do I reset my password", "who are the users", "how do I add a user",
      "hello", "recipe for pizza"]
for label, u in (("USER", user), ("ADMIN", admin)):
    print(f"\n========= {label} =========")
    for q in qs:
        r = answer(q, u, SEED, [admin, user])
        src = " | ".join(f"{s['title']} {s['score']}" for s in r["sources"]) or "no match"
        print(f"Q: {q:30s} -> [{src}]")
