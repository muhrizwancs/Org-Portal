"""End-to-end tests for the portal. No MongoDB or internet needed:  python tests/run_tests.py

Uses a tiny in-memory stand-in for pymongo (tests/fakes) so the real Flask routes can be exercised.
"""
import datetime as dt
import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fakes"))          # fake pymongo / bson / gridfs
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ["ADMIN_EMAIL"] = "boss@org.com"
os.environ["ADMIN_PASSWORD"] = "BossPass123!"

import app as portal                       # noqa: E402
from pymongo import MongoClient            # noqa: E402

db = portal.init_db(client=MongoClient(), db_name="test")
client = portal.app.test_client()
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


def call(method, path, token=None, json=None, **kw):
    headers = {"Authorization": "Bearer " + token} if token else {}
    r = client.open(path, method=method, headers=headers, json=json, **kw)
    return r.status_code, (r.get_json(silent=True) or {}), r


def login(email, pw):
    c, d, _ = call("POST", "/api/auth/login", json={"email": email, "password": pw})
    assert c == 200, d
    return d["token"]


def mk_user(admin, name, email, dept, perms=None, **extra):
    body = {"name": name, "email": email, "password": "Password123!", "department": dept,
            "permissions": perms if perms is not None else ["view_dashboard", "view_tasks", "view_announcements",
                                                              "access_documents", "chat_history", "submit_requests"], **extra}
    c, d, _ = call("POST", "/api/admin/users", admin, body)
    assert c == 201, d
    return d["user"]


def make_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    pages = ["Human Resources Policy Handbook. Welcome to the company and its values.",
             "Working hours are nine to five from Monday to Friday with a one hour lunch break.",
             "Leave policy. Employees are entitled to 20 annual leaves every calendar year. Unused leave expires in March."]
    for t in pages:
        c.drawString(72, 750, t)
        c.showPage()
    c.save()
    return buf.getvalue()


def make_docx(text):
    import docx
    d = docx.Document()
    d.add_paragraph(text)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def upload(admin, title, dept, filename, data, category="Policy", ctype="application/octet-stream"):
    return call("POST", "/api/admin/documents", admin, data={
        "title": title, "department": dept, "category": category, "file": (io.BytesIO(data), filename, ctype)},
        content_type="multipart/form-data")


def ask(token, q, chat_id=None):
    c, d, _ = call("POST", "/api/chat", token, {"message": q, "chatId": chat_id})
    assert c == 200, d
    return d


# ===================================================================== startup / migration
print("\nStartup")
admin_doc = db.users.find_one({"email": "boss@org.com"})
check("first admin is super admin with an employee id", admin_doc.get("superAdmin") and admin_doc["employeeId"] == "EMP-0001")
check("seed knowledge loaded and approved", db.knowledge.count_documents({"status": "approved"}) >= 15)
check("department-tagged seed entry", db.knowledge.find_one({"title": "How to request leave"})["department"] == "HR")

A = login("boss@org.com", "BossPass123!")
c, d, _ = call("GET", "/api/me", A)
check("/api/me returns catalog, defaults and config", c == 200 and "view_tasks" in d["permissionCatalog"]
      and "HR" in d["config"]["departments"] and "view_dashboard" in d["defaultPerms"])

# ===================================================================== users / profile
print("\nUsers and profile")
boss_id = d["user"]["id"]
sara = mk_user(A, "Sara Khan", "sara@org.com", "HR", jobTitle="HR Executive", managerId=boss_id, joiningDate="2025-03-01")
omar = mk_user(A, "Omar Ali", "omar@org.com", "IT", jobTitle="Sysadmin")
ali = mk_user(A, "Ali Raza", "ali@org.com", "Sales", perms=[])          # no page access at all
check("employee ids are sequential", [sara["employeeId"], omar["employeeId"], ali["employeeId"]] == ["EMP-0002", "EMP-0003", "EMP-0004"])
check("manager name resolved", sara["managerName"] == "Organization Admin", sara["managerName"])
c, d, _ = call("POST", "/api/admin/users", A, {"name": "X", "email": "x@org.com", "password": "Password123!", "department": "Nope"})
check("unknown department rejected", c == 400)
c, d, _ = call("POST", "/api/admin/users", A, {"name": "X", "email": "sara@org.com", "password": "Password123!"})
check("duplicate email rejected", c == 409)
S, O, L = (login(e, "Password123!") for e in ("sara@org.com", "omar@org.com", "ali@org.com"))
c, d, _ = call("GET", "/api/me", S)
check("profile shows department, manager, joining date", d["user"]["department"] == "HR" and d["user"]["managerName"] and d["user"]["joiningDate"] == "2025-03-01")
c, _, _ = call("GET", "/api/admin/users", S)
check("user cannot list users (403)", c == 403)
c, _, _ = call("PATCH", f"/api/admin/users/{boss_id}", A, {"managerId": boss_id})
check("cannot be own manager", c == 400)

# ===================================================================== page access control
print("\nPage access (admin ticks who can see which page)")
for path in ("/api/tasks", "/api/announcements", "/api/documents", "/api/chats", "/api/requests", "/api/dashboard"):
    c, _, _ = call("GET", path, L)
    check(f"user with no access gets 403 on {path}", c == 403)
    c, _, _ = call("GET", path, S)
    check(f"user with access gets 200 on {path}", c == 200)
c, _, _ = call("GET", "/api/notifications", L)
check("notifications always available", c == 200)
call("PATCH", f"/api/admin/users/{ali['id']}", A, {"permissions": ["view_announcements"]})
c, _, _ = call("GET", "/api/announcements", L)
check("access applies immediately after admin saves", c == 200)
c, _, _ = call("GET", "/api/documents", L)
check("...and only for the ticked page", c == 403)

# ===================================================================== announcements
print("\nAnnouncements")
c, d, _ = call("POST", "/api/admin/announcements", A, {"title": "Eid holidays", "body": "Office closed 3 days for Eid.", "category": "Holiday notice", "department": "all"})
check("admin posts a holiday notice", c == 201)
ann_id = d["announcement"]["id"]
c, d, _ = call("POST", "/api/admin/announcements", A, {"title": "HR training", "body": "Compliance training for HR.", "category": "Training program", "department": "HR"})
c, d, _ = call("GET", "/api/announcements", S)
check("HR user sees both", len(d["announcements"]) == 2)
c, d, _ = call("GET", "/api/announcements", O)
check("IT user sees only the company-wide one", [a["title"] for a in d["announcements"]] == ["Eid holidays"])
c, d, _ = call("GET", "/api/notifications", S)
check("users were notified", d["unread"] == 2 and any("Eid" in n["text"] for n in d["items"]))
c, d, _ = call("GET", "/api/notifications", O)
check("department targeting applies to notifications", d["unread"] == 1)
c, _, _ = call("POST", "/api/admin/announcements", S, {"title": "t", "body": "b", "category": "New policy"})
check("user cannot post announcements", c == 403)
c, _, _ = call("POST", "/api/admin/announcements", A, {"title": "t", "body": "b", "category": "Bogus"})
check("bad category rejected", c == 400)
c, d, _ = call("PATCH", f"/api/admin/announcements/{ann_id}", A, {"pinned": True})
check("pin an announcement", c == 200 and d["announcement"]["pinned"])
c, d, _ = call("POST", "/api/notifications/read", S, {"all": True})
c, d, _ = call("GET", "/api/notifications", S)
check("mark all read", d["unread"] == 0)

# ===================================================================== documents + citations
print("\nDocument Center and RAG citations")
pdf = make_pdf()
c, d, _ = upload(A, "HR Policy 2026", "HR", "HR_Policy_2026.pdf", pdf, "Policy", "application/pdf")
check("upload PDF", c == 201 and d["document"]["indexed"] and d["document"]["chunkCount"] >= 3, d)
hr_doc = d["document"]["id"]
c, d, _ = upload(A, "IT Policy", "IT", "IT_Policy.docx", make_docx("VPN access requires a ticket approved by your manager. Use the company VPN client on all laptops."), "Policy")
check("upload DOCX is indexed", c == 201 and d["document"]["indexed"], d)
c, d, _ = upload(A, "Travel Form", "all", "travel_form.xlsx", b"PK\x03\x04 fake sheet", "Form")
check("non-searchable file stored, with a reason", c == 201 and not d["document"]["indexed"] and d["document"]["indexNote"])
c, d, _ = upload(A, "Evil", "all", "run.exe", b"MZ")
check("disallowed file type rejected", c == 400)
c, d, _ = upload(A, "Empty", "all", "e.txt", b"")
check("empty file rejected", c == 400)
c, d, _ = call("GET", "/api/documents", S)
check("HR user sees HR + company docs, not IT", sorted(x["title"] for x in d["documents"]) == ["HR Policy 2026", "Travel Form"])
c, d, _ = call("GET", "/api/documents", O)
check("IT user sees IT + company docs, not HR", sorted(x["title"] for x in d["documents"]) == ["IT Policy", "Travel Form"])
c, _, r = call("GET", f"/api/documents/{hr_doc}/download", S)
check("download works for the right department", c == 200 and r.data == pdf and "attachment" in r.headers["Content-Disposition"])
c, _, _ = call("GET", f"/api/documents/{hr_doc}/download", O)
check("download blocked for another department (404)", c == 404)
c, _, _ = call("GET", f"/api/documents/{hr_doc}/download", L)
check("download blocked without Document Center access", c == 403)

r = ask(S, "What is the leave policy?")
src = r["sources"][0]
check("answer cites file and page", src.get("file") == "HR_Policy_2026.pdf" and src.get("page") == 3, r["sources"])
check("answer text states the fact and a Source line", "20 annual leaves" in r["answer"] and "Source: HR_Policy_2026.pdf, page 3" in r["answer"], r["answer"][:200])
r = ask(O, "What is the leave policy?")
check("IT user never gets HR document text", "20 annual leaves" not in r["answer"] and not any(s.get("file") == "HR_Policy_2026.pdf" for s in r["sources"]))
r = ask(O, "How do I get VPN access?")
check("IT user gets the IT docx answer", any(s.get("file") == "IT_Policy.docx" for s in r["sources"]) and "VPN" in r["answer"], r["sources"])
r = ask(S, "How do I get VPN access?")
check("HR user cannot retrieve IT document text", not any(s.get("file") == "IT_Policy.docx" for s in r["sources"]))
call("PATCH", f"/api/admin/users/{sara['id']}", A, {"permissions": ["view_dashboard", "chat_history"]})
r = ask(S, "What is the leave policy?")
check("without Document Center access the assistant does not quote files", "20 annual leaves" not in r["answer"])
call("PATCH", f"/api/admin/users/{sara['id']}", A, {"permissions": ["view_dashboard", "view_tasks", "view_announcements", "access_documents", "chat_history", "submit_requests"]})

# replace a file = new version + notification
c, d, _ = call("PATCH", f"/api/admin/documents/{hr_doc}", A, data={
    "title": "HR Policy 2026", "department": "HR", "category": "Policy",
    "file": (io.BytesIO(make_docx("Leave policy. Employees get 25 annual leaves from 2027.")), "HR_Policy_2027.docx", "application/octet-stream")},
    content_type="multipart/form-data")
check("replacing a file bumps the version", c == 200 and d["document"]["version"] == 2 and d["document"]["filename"] == "HR_Policy_2027.docx", d)
r = ask(S, "What is the leave policy?")
check("assistant uses the new version only", "25 annual leaves" in r["answer"] and "20 annual leaves" not in r["answer"])
c, d, _ = call("GET", "/api/notifications", S)
check("'document updated' notification", any("Document updated" in n["text"] for n in d["items"]))

# ===================================================================== department-based knowledge
print("\nDepartment-based knowledge")
call("POST", "/api/admin/knowledge", A, {"title": "Overtime rules HR", "text": "HR overtime is paid at 1.5 times after approval.", "keywords": "overtime pay", "department": "HR"})
call("POST", "/api/admin/knowledge", A, {"title": "Overtime rules IT", "text": "IT overtime is compensated with time off in lieu.", "keywords": "overtime pay", "department": "IT"})
r = ask(S, "overtime pay rules")
check("HR employee gets the HR answer first", r["sources"][0]["title"] == "Overtime rules HR", r["sources"])
r = ask(O, "overtime pay rules")
check("IT employee gets the IT answer first", r["sources"][0]["title"] == "Overtime rules IT", r["sources"])

# ===================================================================== ask about me
print("\nAsk about me")
call("PATCH", f"/api/admin/users/{sara['id']}", A, {"assignments": [
    {"title": "Update leave tracker", "description": "Monthly refresh", "dueDate": "2020-01-01", "priority": "High", "status": "In Progress", "progress": 40},
    {"title": "Onboard new hire", "dueDate": "2999-01-01", "priority": "Low"}]})
r = ask(S, "Who is my manager?")
check("manager answer", "Organization Admin" in r["answer"], r["answer"][:150])
r = ask(S, "What are my pending tasks?")
check("task answer has priority, status, progress, overdue", "Update leave tracker" in r["answer"] and "High" in r["answer"] and "40%" in r["answer"] and "overdue" in r["answer"], r["answer"][:300])
r = ask(S, "What documents are relevant to my department?")
check("department documents answer", "HR Policy 2026" in r["answer"] and "Travel Form" in r["answer"] and "IT Policy" not in r["answer"], r["answer"][:300])
r = ask(S, "Show company holidays")
check("holidays come from Holiday notices", "Eid holidays" in r["answer"], r["answer"][:200])
r = ask(S, "What is my department?")
check("department answer", "HR" in r["answer"])
r = ask(S, "Show latest announcements")
check("announcements answer", "HR training" in r["answer"] and "Eid holidays" in r["answer"], r["answer"][:200])
r = ask(A, "who are the users")
check("admin still gets the org overview", any(s["title"].startswith("Organization overview") for s in r["sources"]))
r = ask(S, "who are the users")
check("user never gets the org overview", not any("overview" in s["title"].lower() for s in r["sources"]) and "Omar" not in r["answer"])
r = ask(S, "recipe for pizza")
check("unknown topic is honest", r["confidence"] == 0 and r["sources"] == [])

# ===================================================================== chat history
print("\nChat history")
r1 = ask(S, "What is my role?")
cid = r1["chatId"]
r2 = ask(S, "What can I use?", cid)
check("follow-up stays in the same chat", r2["chatId"] == cid)
c, d, _ = call("GET", "/api/chats", S)
check("chat is listed with a title", c == 200 and any(x["id"] == cid and x["title"] == "What is my role?" and x["count"] == 4 for x in d["chats"]), d)
c, d, _ = call("GET", f"/api/chats/{cid}", S)
check("chat can be reopened", len(d["chat"]["messages"]) == 4 and d["chat"]["messages"][1]["role"] == "bot")
c, _, _ = call("GET", f"/api/chats/{cid}", O)
check("another user cannot read it", c == 404)
c, _, _ = call("DELETE", f"/api/chats/{cid}", O)
c, _, _ = call("GET", f"/api/chats/{cid}", S)
check("another user cannot delete it", c == 200)
r = ask(L, "hello")
check("user without Chat history still gets answers, nothing saved", r["chatId"] is None and r["answer"])
r = ask(S, "hello", "0123456789abcdef01234567")
check("unknown chatId starts a new chat", r["chatId"] and r["chatId"] != "0123456789abcdef01234567")
c, _, _ = call("DELETE", f"/api/chats/{cid}", S)
c, _, _ = call("GET", f"/api/chats/{cid}", S)
check("delete chat", c == 404)

# ===================================================================== feedback
print("\nFeedback")
r = ask(S, "What is the leave policy?")
fb = {"rating": "up", "question": "What is the leave policy?", "answer": r["answer"], "sources": ["HR Policy 2026"], "messageId": r["messageId"], "chatId": r["chatId"]}
c, _, _ = call("POST", "/api/feedback", S, fb)
check("thumbs up", c == 200)
c, d, _ = call("GET", f"/api/chats/{r['chatId']}", S)
check("vote is saved inside the chat", [m for m in d["chat"]["messages"] if m["id"] == r["messageId"]][0]["feedback"] == "up")
call("POST", "/api/feedback", S, {**fb, "rating": "down"})
r3 = ask(O, "insurance benefits")
call("POST", "/api/feedback", O, {"rating": "down", "question": "insurance benefits", "answer": r3["answer"], "messageId": r3["messageId"]})
c, d, _ = call("GET", "/api/admin/feedback", A)
check("changing your vote replaces it (no duplicates)", c == 200 and d["up"] == 0 and d["down"] == 2, d)
c, d, _ = call("GET", "/api/admin/feedback?rating=down", A)
check("admin filters not-helpful answers", len(d["items"]) == 2 and d["items"][0]["question"])
c, _, _ = call("POST", "/api/feedback", S, {"rating": "meh"})
check("invalid rating rejected", c == 400)
c, _, _ = call("GET", "/api/admin/feedback", S)
check("feedback list is admin only", c == 403)

# ===================================================================== tasks
print("\nTask management")
c, d, _ = call("GET", "/api/tasks", S)
tasks = {t["title"]: t for t in d["tasks"]}
check("tasks carry priority, due date, status, progress, overdue", tasks["Update leave tracker"]["overdue"] and tasks["Update leave tracker"]["progress"] == 40 and tasks["Onboard new hire"]["status"] == "Assigned" and tasks["Onboard new hire"]["priority"] == "Low")
tid = tasks["Update leave tracker"]["id"]
c, d, _ = call("PATCH", f"/api/tasks/{tid}", S, {"progress": 100})
check("progress 100 completes the task", d["task"]["status"] == "Completed" and d["task"]["progress"] == 100 and d["task"]["completedAt"] and not d["task"]["overdue"])
c, d, _ = call("GET", "/api/notifications", A)
check("admin notified about completion", any("completed the task" in n["text"] for n in d["items"]))
c, d, _ = call("PATCH", f"/api/tasks/{tid}", S, {"status": "In Progress"})
check("re-opening a task", d["task"]["status"] == "In Progress" and d["task"]["progress"] == 10 and d["task"]["completedAt"] is None)
tid2 = tasks["Onboard new hire"]["id"]
c, d, _ = call("PATCH", f"/api/tasks/{tid2}", S, {"progress": 55})
check("moving the slider moves the card", d["task"]["status"] == "In Progress")
c, _, _ = call("PATCH", f"/api/tasks/{tid2}", S, {"progress": "abc"})
check("bad progress rejected", c == 400)
c, _, _ = call("PATCH", f"/api/tasks/{tid2}", O, {"progress": 5})
check("cannot touch someone else's task", c == 404)
c, d, _ = call("GET", "/api/admin/tasks", A)
check("admin sees all tasks", {t["userName"] for t in d["tasks"]} == {"Sara Khan"} and len(d["tasks"]) == 2)
c, d, _ = call("GET", "/api/notifications", S)
check("'new task assigned' notification", any("New task assigned" in n["text"] for n in d["items"]))

# ===================================================================== dashboard
print("\nDashboard")
c, d, _ = call("GET", "/api/dashboard", S)
check("user dashboard cards", d["department"] == "HR" and d["tasks"]["total"] == 2 and d["tasks"]["pending"] == 2 and d["documents"] == 2 and len(d["announcements"]) == 2 and "admin" not in d, d)
c, d, _ = call("GET", "/api/dashboard", A)
check("admin dashboard has organization numbers", d["admin"]["users"] == 4 and "pendingRequests" in d["admin"])

# ===================================================================== requests / approval
print("\nApproval workflow")
c, _, _ = call("POST", "/api/requests", S, {"type": "Leave", "title": "Family trip", "startDate": "2026-12-20"})
check("leave needs both dates", c == 400)
c, _, _ = call("POST", "/api/requests", S, {"type": "Leave", "title": "Family trip", "startDate": "2026-12-20", "endDate": "2026-12-10"})
check("end date before start rejected", c == 400)
c, d, _ = call("POST", "/api/requests", S, {"type": "Leave", "title": "Family trip", "details": "Wedding", "startDate": "2026-12-20", "endDate": "2026-12-24"})
rid = d["request"]["id"]
check("submit leave request", c == 201 and d["request"]["status"] == "Pending")
c, d, _ = call("POST", "/api/requests", S, {"type": "Equipment", "title": "New monitor"})
rid2 = d["request"]["id"]
c, d, _ = call("POST", "/api/requests", S, {"type": "Equipment", "title": "Cancel me"})
rid3 = d["request"]["id"]
c, _, _ = call("POST", "/api/requests", L, {"type": "Leave", "title": "x"})
check("no Requests access -> 403", c == 403)
c, d, _ = call("GET", "/api/notifications", A)
check("admin notified of new requests", sum(1 for n in d["items"] if "request from Sara" in n["text"]) == 3)
c, d, _ = call("GET", "/api/admin/requests?status=Pending", A)
check("admin sees pending requests", len(d["requests"]) == 3)
c, d, _ = call("PATCH", f"/api/admin/requests/{rid}", A, {"status": "Approved", "note": "Enjoy"})
check("approve with a note", c == 200 and d["request"]["status"] == "Approved" and d["request"]["adminNote"] == "Enjoy" and d["request"]["decidedByName"])
c, _, _ = call("PATCH", f"/api/admin/requests/{rid}", A, {"status": "Rejected"})
check("cannot decide twice", c == 400)
c, d, _ = call("PATCH", f"/api/admin/requests/{rid2}", A, {"status": "Rejected", "note": "Budget"})
c, _, _ = call("POST", f"/api/requests/{rid3}/cancel", S)
check("user cancels own pending request", c == 200)
c, _, _ = call("POST", f"/api/requests/{rid}/cancel", S)
check("cannot cancel a decided request", c == 400)
c, _, _ = call("POST", f"/api/requests/{rid3}/cancel", O)
check("cannot cancel someone else's request", c == 404)
c, d, _ = call("GET", "/api/notifications", S)
check("user notified of decisions", any("approved" in n["text"] and "Enjoy" in n["text"] for n in d["items"]) and any("rejected" in n["text"] for n in d["items"]))
c, _, _ = call("PATCH", f"/api/admin/requests/{rid}", S, {"status": "Approved"})
check("user cannot approve", c == 403)

# ===================================================================== knowledge approval
print("\nKnowledge approval workflow")
hr_admin = mk_user(A, "Second Admin", "admin2@org.com", "Management", role="admin")
A2 = login("admin2@org.com", "Password123!")
check("new admin is not a super admin", not hr_admin["superAdmin"])
c, d, _ = call("POST", "/api/admin/knowledge", A2, {"title": "Parking rules", "text": "Parking is allowed behind the building.", "keywords": "parking car", "department": "all"})
kid = d["entry"]["id"]
check("regular admin's entry starts as draft", d["entry"]["status"] == "draft")
r = ask(S, "parking rules")
check("drafts are not used by the assistant", "behind the building" not in r["answer"])
c, d, _ = call("PATCH", f"/api/admin/knowledge/{kid}", A2, {"action": "submit"})
check("submit -> pending", d["entry"]["status"] == "pending")
c, d, _ = call("GET", "/api/notifications", A)
check("super admin notified", any("waiting for approval" in n["text"] for n in d["items"]))
r = ask(S, "parking rules")
check("pending is not used either", "behind the building" not in r["answer"])
c, _, _ = call("PATCH", f"/api/admin/knowledge/{kid}", A2, {"action": "approve"})
check("a regular admin cannot approve their own entry", c == 403)
c, d, _ = call("PATCH", f"/api/admin/knowledge/{kid}", A, {"action": "approve", "note": "Looks good"})
check("super admin approves", c == 200 and d["entry"]["status"] == "approved" and d["entry"]["reviewedByName"])
r = ask(S, "parking rules")
check("approved entries are used", "behind the building" in r["answer"])
c, d, _ = call("GET", "/api/notifications", A2)
check("author notified of approval", any("approved" in n["text"] for n in d["items"]))
c, _, _ = call("DELETE", f"/api/admin/knowledge/{kid}", A2)
check("regular admin cannot delete live knowledge", c == 403)
c, d, _ = call("POST", "/api/admin/knowledge", A2, {"title": "Rejected one", "text": "Bad idea text here.", "submit": True})
kid2 = d["entry"]["id"]
check("'submit' on create goes straight to pending", d["entry"]["status"] == "pending")
c, d, _ = call("PATCH", f"/api/admin/knowledge/{kid2}", A, {"action": "reject", "note": "Not accurate"})
check("super admin rejects with a note", d["entry"]["status"] == "rejected" and d["entry"]["reviewNote"] == "Not accurate")
c, d, _ = call("PATCH", f"/api/admin/knowledge/{kid2}", A2, {"action": "submit"})
check("author can resubmit a rejected entry", d["entry"]["status"] == "pending")
c, _, _ = call("DELETE", f"/api/admin/knowledge/{kid2}", A2)
check("author can delete own pending entry", c == 200)
c, d, _ = call("POST", "/api/admin/knowledge", A, {"title": "Super entry", "text": "Published at once."})
check("super admin's own entries are approved immediately", d["entry"]["status"] == "approved")
c, d, _ = call("PATCH", f"/api/admin/users/{hr_admin['id']}", A, {"superAdmin": True})
check("super admin can promote another super admin", d["user"]["superAdmin"])
c, d, _ = call("PATCH", f"/api/admin/users/{boss_id}", A2, {"superAdmin": False})
check("...who can then demote", c == 200 and not d["user"]["superAdmin"])
c, _, _ = call("PATCH", f"/api/admin/users/{hr_admin['id']}", A2, {"superAdmin": False})
check("the last super admin cannot be removed", c == 400)
c, _, _ = call("DELETE", f"/api/admin/users/{hr_admin['id']}", A)
check("the last super admin cannot be deleted", c == 400)
call("PATCH", f"/api/admin/users/{boss_id}", A2, {"superAdmin": True})

# ===================================================================== analytics
print("\nAnalytics")
c, d, _ = call("GET", "/api/admin/analytics", A)
check("analytics shape", c == 200 and d["users"]["total"] == 5 and d["questions"]["total"] > 10 and d["questions"]["last24h"] > 10)
check("most asked questions counted", d["questions"]["top"][0]["count"] >= 2, d["questions"]["top"][:3])
check("unanswered questions listed", any("pizza" in q["question"] for q in d["questions"]["unanswered"]))
check("documents / feedback / requests / tasks / knowledge", d["documents"]["total"] == 3 and d["documents"]["searchable"] == 2
      and d["feedback"]["down"] == 2 and d["requests"]["Approved"] == 1 and d["requests"]["Cancelled"] == 1
      and d["tasks"]["total"] == 2 and d["knowledge"]["approved"] >= 15)
check("active users tracked", d["users"]["active7d"] >= 4 and d["users"]["byDepartment"].get("HR") == 1)
c, _, _ = call("GET", "/api/admin/analytics", S)
check("analytics is admin only", c == 403)

# ===================================================================== misc security
print("\nSecurity and limits")
c, _, _ = call("GET", "/api/notifications")
check("no token -> 401", c == 401)
c, d, _ = call("POST", "/api/chat", S, json=None, data="x" * 300000, content_type="application/json")
check("oversized JSON body rejected", c == 413)
c, d, _ = call("GET", "/api/notifications", S)
unread = [n for n in d["items"] if not n["read"]]
check("(setup) Sara has an unread notification", len(unread) > 0)
call("POST", "/api/notifications/read", O, {"ids": [unread[0]["id"]]})
c, d, _ = call("GET", "/api/notifications", S)
check("cannot mark someone else's notifications read", [n for n in d["items"] if n["id"] == unread[0]["id"]][0]["read"] is False)
call("POST", "/api/notifications/read", S, {"ids": [unread[0]["id"]]})
c, d, _ = call("GET", "/api/notifications", S)
check("...but can mark your own", [n for n in d["items"] if n["id"] == unread[0]["id"]][0]["read"] is True)
c, _, _ = call("DELETE", f"/api/admin/documents/{hr_doc}", S)
check("user cannot delete documents", c == 403)
c, _, _ = call("DELETE", f"/api/admin/documents/{hr_doc}", A)
check("admin deletes a document and its index", c == 200 and db.doc_chunks.count_documents({"docId": __import__('bson').ObjectId(hr_doc)}) == 0)
r = ask(S, "What is the leave policy?")
check("deleted document no longer answers", "25 annual leaves" not in r["answer"])
c, _, _ = call("DELETE", f"/api/admin/users/{sara['id']}", A)
check("deleting a user removes their chats and notifications", db.chats.count_documents({"userId": __import__('bson').ObjectId(sara['id'])}) == 0 and db.notifications.count_documents({"userId": __import__('bson').ObjectId(sara['id'])}) == 0)
c, _, _ = call("POST", "/api/auth/login", json={"email": "sara@org.com", "password": "Password123!"})
check("deleted user cannot sign in", c == 401)
c, _, _ = call("GET", "/api/me", S)
check("deleted user's token stops working", c == 401)

# ===================================================================== migration from the first version
print("\nUpgrade from the first version of the portal")
legacy_user = {"name": "Old Timer", "email": "old@org.com", "role": "user", "jobTitle": "Clerk", "passwordHash": portal.hash_pw("Password123!"),
               "permissions": ["view_reports"], "active": True, "createdAt": dt.datetime(2025, 1, 1),
               "assignments": [{"id": "a1", "title": "Old task", "description": "from v1", "assignedAt": dt.datetime(2025, 2, 2)}]}
db.users.insert_one(legacy_user)
db.knowledge.insert_one({"title": "Legacy note", "text": "Old knowledge without a status.", "audience": "all", "system": False, "createdAt": dt.datetime(2025, 1, 1)})
db.meta.delete_one({"_id": "pages_v1"})
portal.migrate(db)
old = db.users.find_one({"email": "old@org.com"})
check("legacy user gets an employee id", old["employeeId"].startswith("EMP-"))
check("legacy user gets the new pages once", {"view_tasks", "view_announcements", "chat_history", "view_reports"} <= set(old["permissions"]))
check("legacy knowledge counts as approved", db.knowledge.find_one({"title": "Legacy note"})["status"] == "approved")
OLD = login("old@org.com", "Password123!")
c, d, _ = call("GET", "/api/tasks", OLD)
check("legacy tasks get defaults", d["tasks"][0]["priority"] == "Medium" and d["tasks"][0]["status"] == "Assigned" and d["tasks"][0]["progress"] == 0)
r = ask(OLD, "legacy note old knowledge")
check("legacy knowledge is searchable", "Old knowledge" in r["answer"])
c, d, _ = call("GET", "/api/me", OLD)
check("naive datetimes from Mongo are sent as UTC", d["user"]["createdAt"].endswith("+00:00"), d["user"]["createdAt"])
portal.migrate(db)
check("migration is idempotent", db.users.find_one({"email": "old@org.com"})["permissions"].count("view_tasks") == 1)
db.meta.update_one({"_id": "seed"}, {"$set": {"version": 0}})
before = db.knowledge.count_documents({})
portal.sync_seed_knowledge(db)
check("seed refresh does not duplicate or touch admin-written entries", db.knowledge.count_documents({}) == before and db.knowledge.find_one({"title": "Parking rules"})["system"] is False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
