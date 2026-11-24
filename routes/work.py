"""My tasks, requests (approval workflow), notifications and the dashboard."""
import datetime as dt

from flask import Blueprint, g, jsonify, request

import core
import constants as C
from core import (admin_ids, as_utc, auth_required, clean_assignments, fail, has_perm, is_admin, iso, notify, now,
                  oid, parse_date, ser_task, visible_announcements, visible_documents)

bp = Blueprint("work", __name__)


# ================================================================ my tasks
@bp.get("/api/tasks")
@auth_required(perm="view_tasks")
def my_tasks():
    return jsonify(tasks=[ser_task(a) for a in g.user.get("assignments", [])])


@bp.patch("/api/tasks/<tid>")
@auth_required(perm="view_tasks")
def update_my_task(tid):
    """A person may change the status and progress of their own tasks. Everything else is the admin's."""
    b = request.get_json(silent=True) or {}
    tasks = [dict(a) for a in g.user.get("assignments", [])]
    task = next((a for a in tasks if a.get("id") == tid), None)
    if not task:
        return fail("Task not found.", 404)
    was_done = task.get("status") == "Completed"
    status = b.get("status") if b.get("status") in C.TASK_STATUSES else None
    progress = None
    if "progress" in b:
        try:
            progress = max(0, min(100, int(b["progress"])))
        except (TypeError, ValueError):
            return fail("Progress must be a number from 0 to 100.")
    cur = int(task.get("progress") or 0)
    if status and progress is None:        # moved to another column: pick a sensible progress
        progress = {"Assigned": 0, "Completed": 100}.get(status, cur if 0 < cur < 100 else 10)
    elif progress is not None and not status:   # moved the slider: pick the matching column
        status = "Completed" if progress == 100 else ("In Progress" if progress > 0 else "Assigned")
    if status:
        task["status"], task["progress"] = status, progress
    cleaned = clean_assignments(tasks)
    core.db.users.update_one({"_id": g.user["_id"]}, {"$set": {"assignments": cleaned, "updatedAt": now()}})
    saved = next(a for a in cleaned if a["id"] == tid)
    if saved["status"] == "Completed" and not was_done:
        notify(admin_ids(exclude=g.user["_id"]), "task", f"{g.user['name']} completed the task: {saved['title']}", "team-tasks")
    return jsonify(task=ser_task(saved))


# ================================================================ requests (approval workflow)
def ser_req(r):
    return {"id": str(r["_id"]), "userId": str(r["userId"]), "userName": r.get("userName", ""),
            "department": r.get("department", ""), "type": r["type"], "title": r["title"],
            "details": r.get("details", ""), "startDate": r.get("startDate"), "endDate": r.get("endDate"),
            "status": r["status"], "adminNote": r.get("adminNote", ""), "decidedByName": r.get("decidedByName", ""),
            "decidedAt": iso(r.get("decidedAt")), "createdAt": iso(r.get("createdAt"))}


@bp.get("/api/requests")
@auth_required(perm="submit_requests")
def my_requests():
    rows = core.db.requests.find({"userId": g.user["_id"]}).sort("createdAt", -1).limit(200)
    return jsonify(requests=[ser_req(r) for r in rows])


@bp.post("/api/requests")
@auth_required(perm="submit_requests")
def submit_request():
    d = request.get_json(silent=True) or {}
    rtype = d.get("type")
    title = str(d.get("title") or "").strip()
    if rtype not in C.REQUEST_TYPES:
        return fail("Choose a request type.")
    if not title:
        return fail("Give the request a short title.")
    start, end = parse_date(d.get("startDate")), parse_date(d.get("endDate"))
    if rtype == "Leave":
        if not start or not end:
            return fail("Leave requests need a start and an end date.")
        if end < start:
            return fail("The end date cannot be before the start date.")
    else:
        start = end = None
    doc = {"userId": g.user["_id"], "userName": g.user["name"], "department": g.user.get("department", ""),
           "type": rtype, "title": title[:120], "details": str(d.get("details") or "").strip()[:1000],
           "startDate": start, "endDate": end, "status": "Pending", "createdAt": now()}
    res = core.db.requests.insert_one(doc)
    notify(admin_ids(exclude=g.user["_id"]), "request", f"New {rtype.lower()} request from {g.user['name']}: {doc['title']}", "requests")
    return jsonify(request=ser_req(core.db.requests.find_one({"_id": res.inserted_id}))), 201


@bp.post("/api/requests/<rid>/cancel")
@auth_required(perm="submit_requests")
def cancel_request(rid):
    r = core.db.requests.find_one({"_id": oid(rid), "userId": g.user["_id"]})
    if not r:
        return fail("Request not found.", 404)
    if r["status"] != "Pending":
        return fail("Only pending requests can be cancelled.")
    core.db.requests.update_one({"_id": r["_id"]}, {"$set": {"status": "Cancelled", "decidedAt": now()}})
    return jsonify(request=ser_req(core.db.requests.find_one({"_id": r["_id"]})))


@bp.get("/api/admin/requests")
@auth_required(admin=True)
def admin_requests():
    q = {}
    if request.args.get("status") in C.REQUEST_STATUSES:
        q["status"] = request.args["status"]
    rows = core.db.requests.find(q).sort("createdAt", -1).limit(300)
    return jsonify(requests=[ser_req(r) for r in rows])


@bp.patch("/api/admin/requests/<rid>")
@auth_required(admin=True)
def decide_request(rid):
    r = core.db.requests.find_one({"_id": oid(rid)})
    if not r:
        return fail("Request not found.", 404)
    b = request.get_json(silent=True) or {}
    if b.get("status") not in ("Approved", "Rejected"):
        return fail("Choose Approved or Rejected.")
    if r["status"] != "Pending":
        return fail(f"This request was already {r['status'].lower()}.")
    note = str(b.get("note") or "").strip()[:500]
    core.db.requests.update_one({"_id": r["_id"]}, {"$set": {
        "status": b["status"], "adminNote": note, "decidedBy": g.user["email"],
        "decidedByName": g.user["name"], "decidedAt": now()}})
    notify([r["userId"]], "request", f"Your request \"{r['title']}\" was {b['status'].lower()}." + (f" Note: {note}" if note else ""), "requests")
    return jsonify(request=ser_req(core.db.requests.find_one({"_id": r["_id"]})))


# ================================================================ notifications
@bp.get("/api/notifications")
@auth_required()
def notifications():
    rows = list(core.db.notifications.find({"userId": g.user["_id"]}).sort("createdAt", -1).limit(50))
    unread = core.db.notifications.count_documents({"userId": g.user["_id"], "read": False})
    return jsonify(unread=unread, items=[{"id": str(n["_id"]), "kind": n["kind"], "text": n["text"], "link": n.get("link"),
                                          "read": bool(n.get("read")), "createdAt": iso(n["createdAt"])} for n in rows])


@bp.post("/api/notifications/read")
@auth_required()
def mark_read():
    b = request.get_json(silent=True) or {}
    q = {"userId": g.user["_id"], "read": False}
    if not b.get("all"):
        ids = [oid(i) for i in (b.get("ids") or []) if oid(i)]
        q["_id"] = {"$in": ids}
    core.db.notifications.update_many(q, {"$set": {"read": True}})
    return jsonify(ok=True)


# ================================================================ dashboard
@bp.get("/api/dashboard")
@auth_required(perm="view_dashboard")
def dashboard():
    u = g.user
    tasks = [ser_task(a) for a in u.get("assignments", [])]
    out = {
        "role": u["role"], "department": u.get("department", ""), "jobTitle": u.get("jobTitle", ""),
        "tasks": {"total": len(tasks),
                  "assigned": sum(1 for t in tasks if t["status"] == "Assigned"),
                  "inProgress": sum(1 for t in tasks if t["status"] == "In Progress"),
                  "completed": sum(1 for t in tasks if t["status"] == "Completed"),
                  "pending": sum(1 for t in tasks if t["status"] != "Completed"),
                  "overdue": sum(1 for t in tasks if t["overdue"])} if has_perm(u, "view_tasks") else None,
        "documents": len(visible_documents(u)) if has_perm(u, "access_documents") else None,
        "announcements": ([{"id": str(a["_id"]), "title": a["title"], "category": a.get("category", ""),
                            "createdAt": iso(a.get("createdAt"))} for a in visible_announcements(u)[:3]]
                          if has_perm(u, "view_announcements") else None),
        "requests": ({"pending": core.db.requests.count_documents({"userId": u["_id"], "status": "Pending"}),
                      "total": core.db.requests.count_documents({"userId": u["_id"]})}
                     if has_perm(u, "submit_requests") else None),
        "unreadNotifications": core.db.notifications.count_documents({"userId": u["_id"], "read": False}),
    }
    if is_admin(u):
        since = now() - dt.timedelta(hours=24)
        out["admin"] = {
            "users": core.db.users.count_documents({}),
            "pendingRequests": core.db.requests.count_documents({"status": "Pending"}),
            "pendingKnowledge": core.db.knowledge.count_documents({"status": "pending"}),
            "questions24h": core.db.questions.count_documents({"createdAt": {"$gte": since}}),
            "helpful": core.db.feedback.count_documents({"rating": "up"}),
            "notHelpful": core.db.feedback.count_documents({"rating": "down"}),
        }
    return jsonify(out)
