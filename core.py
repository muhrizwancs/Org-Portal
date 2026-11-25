"""Shared helpers used by every route module: database handle, auth, notifications, serializers."""
import datetime as dt
import os
import re
import uuid
from functools import wraps

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from flask import g, jsonify, request
from werkzeug.security import generate_password_hash

from constants import TASK_PRIORITIES, TASK_STATUSES
from permissions import PERMS

load_dotenv()
SECRET = os.getenv("JWT_SECRET") or "dev-secret"
SHORT_SESSION = dt.timedelta(hours=12)      # "Keep me signed in" unticked
LONG_SESSION = dt.timedelta(days=30)        # "Keep me signed in" ticked

db = None   # set by app.init_db()
fs = None   # GridFS bucket for uploaded documents, set by app.init_db()


# ---------------------------------------------------------------- small helpers
def now():
    return dt.datetime.now(dt.timezone.utc)


def as_utc(d):
    """MongoDB hands datetimes back without a timezone; they are always UTC."""
    if isinstance(d, dt.datetime) and d.tzinfo is None:
        return d.replace(tzinfo=dt.timezone.utc)
    return d


def iso(d):
    d = as_utc(d)
    return d.isoformat() if isinstance(d, dt.datetime) else d


def parse_dt(v):
    if isinstance(v, dt.datetime):
        return as_utc(v)
    if isinstance(v, str) and v:
        try:
            return as_utc(dt.datetime.fromisoformat(v.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def parse_date(v):
    """Return 'YYYY-MM-DD' or None."""
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


def oid(s):
    try:
        return ObjectId(str(s))
    except (InvalidId, TypeError):
        return None


def fail(msg, code=400):
    return jsonify(error=msg), code


def hash_pw(pw):
    return generate_password_hash(pw, method="pbkdf2:sha256")


def norm_question(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", str(text).lower())).strip()


def is_admin(u):
    return u.get("role") == "admin"


def has_perm(u, perm):
    return is_admin(u) or perm in (u.get("permissions") or [])


# ---------------------------------------------------------------- auth
def auth_required(admin=False, perm=None, super_admin=False):
    """admin=True: admins only. super_admin=True: the super admin only. perm='x': needs that access."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            token = (request.headers.get("Authorization") or "").replace("Bearer ", "")
            try:
                payload = jwt.decode(token, SECRET, algorithms=["HS256"])
            except jwt.PyJWTError:
                return fail("Please sign in again.", 401)
            # fresh from the DB on every request: role/access changes apply instantly
            u = db.users.find_one({"_id": oid(payload.get("sub"))})
            if not u or not u.get("active", True):
                return fail("This account is disabled or no longer exists.", 401)
            if (admin or super_admin) and not is_admin(u):
                return fail("Admin access required.", 403)
            if super_admin and not u.get("superAdmin"):
                return fail("Only the super admin can do this.", 403)
            if perm and not has_perm(u, perm):
                return fail(f"You do not have access to {PERMS[perm]['label']}. Ask the admin to enable it.", 403)
            seen = as_utc(u.get("lastSeenAt"))
            if not seen or (now() - seen).total_seconds() > 300:
                db.users.update_one({"_id": u["_id"]}, {"$set": {"lastSeenAt": now()}})
            g.user = u
            return fn(*a, **kw)
        return wrapper
    return deco


# ---------------------------------------------------------------- notifications
def notify(user_ids, kind, text, link=None):
    """Create one bell notification per user id. `link` is the page the bell opens."""
    ids = [i for i in user_ids if i]
    if not ids:
        return
    t = now()
    db.notifications.insert_many([{"userId": i, "kind": kind, "text": str(text)[:300], "link": link,
                                   "read": False, "createdAt": t} for i in ids])


def recipients(perm=None, dept=None, exclude=None):
    """Active accounts that hold `perm` and (if dept is given and not 'all') belong to that department.
    Admins always qualify."""
    out = []
    for u in db.users.find({"active": {"$ne": False}}):
        if exclude is not None and u["_id"] == exclude:
            continue
        admin = is_admin(u)
        if perm and not admin and perm not in (u.get("permissions") or []):
            continue
        if dept and dept != "all" and not admin and (u.get("department") or "") != dept:
            continue
        out.append(u["_id"])
    return out


def admin_ids(exclude=None):
    return [u["_id"] for u in db.users.find({"role": "admin", "active": {"$ne": False}}) if u["_id"] != exclude]


# ---------------------------------------------------------------- tasks (stored inside the user record)
def clean_assignments(lst):
    out = []
    for a in lst if isinstance(lst, list) else []:
        if not isinstance(a, dict):
            continue
        title = str(a.get("title") or "").strip()
        if not title:
            continue
        status = a.get("status") if a.get("status") in TASK_STATUSES else "Assigned"
        try:
            progress = max(0, min(100, int(a.get("progress") or 0)))
        except (TypeError, ValueError):
            progress = 0
        if status == "Completed":
            progress = 100
        elif progress == 100:
            status = "Completed"
        elif progress > 0 and status == "Assigned":
            status = "In Progress"
        completed_at = (parse_dt(a.get("completedAt")) or now()) if status == "Completed" else None
        out.append({
            "id": str(a.get("id") or uuid.uuid4().hex), "title": title[:120],
            "description": str(a.get("description") or "").strip()[:500],
            "assignedAt": parse_dt(a.get("assignedAt")) or now(),
            "dueDate": parse_date(a.get("dueDate")),
            "priority": a.get("priority") if a.get("priority") in TASK_PRIORITIES else "Medium",
            "status": status, "progress": progress, "completedAt": completed_at,
        })
    return out


def ser_task(a):
    today = dt.date.today().isoformat()
    due = a.get("dueDate")
    status = a.get("status") or "Assigned"
    return {"id": a.get("id"), "title": a.get("title", ""), "description": a.get("description", ""),
            "assignedAt": iso(a.get("assignedAt")), "dueDate": due,
            "priority": a.get("priority") or "Medium", "status": status,
            "progress": int(a.get("progress") or 0), "completedAt": iso(a.get("completedAt")),
            "overdue": bool(due and due < today and status != "Completed")}


# ---------------------------------------------------------------- users
def clean_perms(lst):
    seen, out = set(), []
    for p in lst if isinstance(lst, list) else []:
        if p in PERMS and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def name_map(users=None):
    return {str(u["_id"]): u["name"] for u in (users if users is not None else db.users.find())}


def public_user(u, names=None):
    admin = is_admin(u)
    mid = str(u["managerId"]) if u.get("managerId") else None
    return {
        "id": str(u["_id"]), "name": u["name"], "email": u["email"], "role": u["role"],
        "superAdmin": bool(u.get("superAdmin")),
        "jobTitle": u.get("jobTitle", ""), "department": u.get("department", ""),
        "jobRoleId": str(u["jobRoleId"]) if u.get("jobRoleId") else None,
        "jobRole": u.get("jobRole", ""),
        "employeeId": u.get("employeeId", ""), "joiningDate": u.get("joiningDate"),
        "managerId": mid, "managerName": (names or {}).get(mid, "") if mid else "",
        "permissions": list(PERMS) if admin else u.get("permissions", []),
        "assignments": [ser_task(a) for a in u.get("assignments", [])],
        "active": u.get("active", True), "createdAt": iso(u.get("createdAt")),
        "lastSeenAt": iso(u.get("lastSeenAt")),
    }


def next_employee_id():
    """EMP-0001, EMP-0002 ... one higher than the highest in use (numbers of deleted people are not reused)."""
    nums = []
    for u in db.users.find():
        m = re.fullmatch(r"EMP-(\d+)", u.get("employeeId") or "")
        if m:
            nums.append(int(m.group(1)))
    return f"EMP-{max(nums, default=0) + 1:04d}"


# ---------------------------------------------------------------- what a person may see (shared by pages and the assistant)
def visible_documents(user):
    """Documents the person may see: 'all' ones plus their own department's. Admins see everything."""
    dept = user.get("department") or ""
    out = []
    for d in db.documents.find().sort("createdAt", -1):
        if is_admin(user) or d.get("department", "all") in ("all", "", dept):
            out.append(d)
    return out


def visible_announcements(user):
    dept = user.get("department") or ""
    out = []
    for a in db.announcements.find().sort("createdAt", -1):
        if is_admin(user) or a.get("department", "all") in ("all", "", dept):
            out.append(a)
    out.sort(key=lambda a: (not a.get("pinned"), -as_utc(a["createdAt"]).timestamp()))
    return out
