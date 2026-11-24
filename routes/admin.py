"""Admin only: knowledge entries (with approval workflow), analytics, feedback, team tasks."""
import datetime as dt
from collections import Counter

from flask import Blueprint, g, jsonify, request

import core
import constants as C
from core import (as_utc, auth_required, fail, iso, notify, now, oid, recipients, ser_task)

bp = Blueprint("admin", __name__)


# ================================================================ knowledge + approval workflow
#   draft --submit--> pending --approve--> approved        (the assistant only uses "approved")
#                         \\--reject--> rejected --submit--> pending
#   The super admin's own entries are approved immediately.
def ser_k(k):
    return {"id": str(k["_id"]), "title": k["title"], "keywords": k.get("keywords", ""), "text": k["text"],
            "audience": k.get("audience", "all"), "department": k.get("department", "all"),
            "system": k.get("system", False), "status": k.get("status", "approved"),
            "createdByName": k.get("createdByName", ""), "createdBy": k.get("createdBy", ""),
            "reviewedByName": k.get("reviewedByName", ""), "reviewNote": k.get("reviewNote", ""),
            "reviewedAt": iso(k.get("reviewedAt")), "createdAt": iso(k.get("createdAt"))}


@bp.get("/api/admin/knowledge")
@auth_required(admin=True)
def list_knowledge():
    rows = core.db.knowledge.find().sort([("createdAt", 1), ("_id", 1)])
    return jsonify(entries=[ser_k(k) for k in rows])


@bp.post("/api/admin/knowledge")
@auth_required(admin=True)
def add_knowledge():
    d = request.get_json(silent=True) or {}
    title, text = str(d.get("title") or "").strip(), str(d.get("text") or "").strip()
    if not title or not text:
        return fail("Title and text are required.")
    dept = str(d.get("department") or "all")
    if dept != "all" and dept not in C.DEPARTMENTS:
        return fail("Unknown department.")
    submit = bool(d.get("submit"))
    if g.user.get("superAdmin"):
        status = "approved"
    else:
        status = "pending" if submit else "draft"
    doc = {"title": title[:150], "text": text[:4000], "keywords": str(d.get("keywords") or "")[:500],
           "audience": "admin" if d.get("audience") == "admin" else "all", "department": dept,
           "system": False, "status": status, "createdBy": g.user["email"], "createdByName": g.user["name"],
           "createdAt": now()}
    res = core.db.knowledge.insert_one(doc)
    if status == "pending":
        _notify_supers(g.user, f"Knowledge entry waiting for approval: {doc['title']}")
    return jsonify(entry=ser_k(core.db.knowledge.find_one({"_id": res.inserted_id}))), 201


def _notify_supers(actor, text):
    sup = [u["_id"] for u in core.db.users.find({"superAdmin": True, "active": {"$ne": False}}) if u["_id"] != actor["_id"]]
    notify(sup, "knowledge", text, "knowledge")


@bp.patch("/api/admin/knowledge/<kid>")
@auth_required(admin=True)
def review_knowledge(kid):
    k = core.db.knowledge.find_one({"_id": oid(kid)})
    if not k:
        return fail("Entry not found.", 404)
    b = request.get_json(silent=True) or {}
    action, note = b.get("action"), str(b.get("note") or "").strip()[:500]
    status = k.get("status", "approved")
    me = g.user
    creator = core.db.users.find_one({"email": k.get("createdBy")})

    if action == "submit":
        if status not in ("draft", "rejected"):
            return fail("Only drafts and rejected entries can be submitted.")
        if k.get("createdBy") != me["email"] and not me.get("superAdmin"):
            return fail("Only the author can submit this entry.", 403)
        new = "approved" if me.get("superAdmin") else "pending"
        core.db.knowledge.update_one({"_id": k["_id"]}, {"$set": {"status": new}})
        if new == "pending":
            _notify_supers(me, f"Knowledge entry waiting for approval: {k['title']}")
    elif action in ("approve", "reject"):
        if not me.get("superAdmin"):
            return fail("Only the super admin can approve or reject knowledge.", 403)
        if action == "approve" and status not in ("draft", "pending", "rejected"):
            return fail("This entry is already approved.")
        if action == "reject" and status != "pending":
            return fail("Only pending entries can be rejected.")
        new = "approved" if action == "approve" else "rejected"
        core.db.knowledge.update_one({"_id": k["_id"]}, {"$set": {
            "status": new, "reviewedBy": me["email"], "reviewedByName": me["name"], "reviewNote": note, "reviewedAt": now()}})
        if creator and creator["_id"] != me["_id"]:
            notify([creator["_id"]], "knowledge",
                   f"Your knowledge entry \"{k['title']}\" was {new}." + (f" Note: {note}" if note else ""), "knowledge")
    else:
        return fail("Unknown action.")
    return jsonify(entry=ser_k(core.db.knowledge.find_one({"_id": k["_id"]})))


@bp.delete("/api/admin/knowledge/<kid>")
@auth_required(admin=True)
def delete_knowledge(kid):
    k = core.db.knowledge.find_one({"_id": oid(kid)})
    if not k:
        return jsonify(ok=True)
    if not g.user.get("superAdmin"):
        # others may only remove their own entries that are not live yet
        if k.get("createdBy") != g.user["email"] or k.get("status", "approved") == "approved":
            return fail("Only the super admin can delete live knowledge. You can delete your own drafts and pending entries.", 403)
    core.db.knowledge.delete_one({"_id": k["_id"]})
    return jsonify(ok=True)


# ================================================================ feedback
@bp.get("/api/admin/feedback")
@auth_required(admin=True)
def list_feedback():
    q = {"rating": request.args["rating"]} if request.args.get("rating") in ("up", "down") else {}
    rows = list(core.db.feedback.find(q).sort("createdAt", -1).limit(300))
    return jsonify(
        up=core.db.feedback.count_documents({"rating": "up"}), down=core.db.feedback.count_documents({"rating": "down"}),
        items=[{"id": str(f["_id"]), "question": f.get("question", ""), "answer": f.get("answer", ""),
                "sources": f.get("sources", []), "rating": f["rating"], "userName": f.get("userName", ""),
                "department": f.get("department", ""), "createdAt": iso(f["createdAt"])} for f in rows])


# ================================================================ analytics
@bp.get("/api/admin/analytics")
@auth_required(admin=True)
def analytics():
    db = core.db
    t = now()
    day, week = t - dt.timedelta(hours=24), t - dt.timedelta(days=7)
    users = list(db.users.find())
    active_users = [u for u in users if u.get("active", True)]
    seen = lambda u, since: bool(u.get("lastSeenAt")) and as_utc(u["lastSeenAt"]) >= since  # noqa: E731

    qs = list(db.questions.find({"createdAt": {"$gte": t - dt.timedelta(days=90)}}).sort("createdAt", -1).limit(5000))
    asked = Counter(q["norm"] for q in qs if q.get("norm"))
    sample = {}
    for q in qs:
        sample.setdefault(q["norm"], q["text"])
    unanswered = Counter(q["norm"] for q in qs if not q.get("answered"))

    tasks = [ta for u in users for ta in (ser_task(a) for a in u.get("assignments", []))]
    req_counts = Counter(r["status"] for r in db.requests.find())
    know_counts = Counter(k.get("status", "approved") for k in db.knowledge.find())
    docs = list(db.documents.find())
    dept_counts = Counter((u.get("department") or "Unassigned") for u in active_users)
    up, down = db.feedback.count_documents({"rating": "up"}), db.feedback.count_documents({"rating": "down"})

    return jsonify(
        users={"total": len(users), "active": len(active_users), "activeToday": sum(1 for u in active_users if seen(u, day)),
               "active7d": sum(1 for u in active_users if seen(u, week)), "byDepartment": dict(dept_counts)},
        questions={"total": len(qs), "last24h": sum(1 for q in qs if as_utc(q["createdAt"]) >= day),
                   "answeredPct": round(100 * sum(1 for q in qs if q.get("answered")) / len(qs)) if qs else None,
                   "top": [{"question": sample[k], "count": c} for k, c in asked.most_common(10)],
                   "unanswered": [{"question": sample[k], "count": c} for k, c in unanswered.most_common(8)],
                   "times7d": [iso(q["createdAt"]) for q in qs if as_utc(q["createdAt"]) >= week][:3000]},
        documents={"total": len(docs), "searchable": sum(1 for d in docs if d.get("indexed")),
                   "announcements": db.announcements.count_documents({})},
        feedback={"up": up, "down": down, "satisfactionPct": round(100 * up / (up + down)) if up + down else None},
        requests={s: req_counts.get(s, 0) for s in C.REQUEST_STATUSES},
        tasks={"total": len(tasks), **{s: sum(1 for x in tasks if x["status"] == s) for s in C.TASK_STATUSES},
               "overdue": sum(1 for x in tasks if x["overdue"])},
        knowledge={s: know_counts.get(s, 0) for s in C.KNOWLEDGE_STATUSES},
    )


# ================================================================ team tasks
@bp.get("/api/admin/tasks")
@auth_required(admin=True)
def team_tasks():
    rows = []
    for u in core.db.users.find({"active": {"$ne": False}}).sort("name", 1):
        for a in u.get("assignments", []):
            rows.append({**ser_task(a), "userId": str(u["_id"]), "userName": u["name"], "department": u.get("department", "")})
    return jsonify(tasks=rows)
