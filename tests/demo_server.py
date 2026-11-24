"""Preview the portal with sample data and NO database:  python tests/demo_server.py
Everything lives in memory and disappears when you stop it.
Sign in as  boss@org.com / BossPass123!  (admin)  or  sara@org.com / Password123!  (HR user)."""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fakes"))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"] = "boss@org.com", "BossPass123!"

import app as portal                    # noqa: E402
from pymongo import MongoClient         # noqa: E402

db = portal.init_db(client=MongoClient(), db_name="demo")
c = portal.app.test_client()


def call(method, path, token=None, **kw):
    r = c.open(path, method=method, headers={"Authorization": "Bearer " + token} if token else {}, **kw)
    return r.get_json(silent=True) or {}


A = call("POST", "/api/auth/login", json={"email": "boss@org.com", "password": "BossPass123!"})["token"]
boss = call("GET", "/api/me", A)["user"]["id"]
P = ["view_dashboard", "view_tasks", "view_announcements", "access_documents", "chat_history", "submit_requests"]
call("POST", "/api/admin/users", A, json={"name": "Sara Khan", "email": "sara@org.com", "password": "Password123!", "department": "HR",
     "jobTitle": "HR Executive", "managerId": boss, "joiningDate": "2025-03-01", "permissions": P, "assignments": [
         {"title": "Update leave tracker", "description": "Monthly refresh", "dueDate": "2026-11-01", "priority": "High", "status": "In Progress", "progress": 40},
         {"title": "Onboard new hire", "dueDate": "2026-12-15", "priority": "Medium"},
         {"title": "Archive old forms", "priority": "Low", "status": "Completed"}]})
call("POST", "/api/admin/users", A, json={"name": "Omar Ali", "email": "omar@org.com", "password": "Password123!", "department": "IT", "jobTitle": "Sysadmin", "permissions": P})
call("POST", "/api/admin/announcements", A, json={"title": "Annual Compliance Training", "body": "Everyone must complete the course by 15 December.", "category": "Training program", "department": "all", "pinned": True})
call("POST", "/api/admin/announcements", A, json={"title": "Winter holidays", "body": "The office is closed from 25 to 31 December.", "category": "Holiday notice", "department": "all"})


def pdf():
    from reportlab.pdfgen import canvas
    b = io.BytesIO(); cv = canvas.Canvas(b)
    for t in ["HR policy handbook. Welcome to the company.", "Working hours are nine to five, Monday to Friday.",
              "Leave policy. Employees are entitled to 20 annual leaves each year."]:
        cv.drawString(72, 750, t); cv.showPage()
    cv.save(); return b.getvalue()


try:
    call("POST", "/api/admin/documents", A, content_type="multipart/form-data", data={
        "title": "HR Policy 2026", "department": "HR", "category": "Policy", "file": (io.BytesIO(pdf()), "HR_Policy_2026.pdf", "application/pdf")})
except Exception as e:  # noqa: BLE001  (reportlab missing: skip the sample PDF)
    print("sample PDF skipped:", e)
call("POST", "/api/requests", call("POST", "/api/auth/login", json={"email": "sara@org.com", "password": "Password123!"})["token"],
     json={"type": "Leave", "title": "Family trip", "startDate": "2026-12-20", "endDate": "2026-12-24", "details": "Wedding"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    print(f"\nDemo portal (in-memory data) at http://localhost:{port}\n")
    portal.app.run(host="127.0.0.1", port=port, debug=False)
