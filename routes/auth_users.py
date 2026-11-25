"""Sign-in, my account/profile, and admin user management."""
import time
from collections import defaultdict, deque

import jwt
from flask import Blueprint, g, jsonify, request
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash

import core
import constants as C
from core import (LONG_SESSION, SECRET, SHORT_SESSION, auth_required, clean_assignments, clean_perms, fail,
                  hash_pw, name_map, next_employee_id, notify, now, oid, parse_date, public_user)
from permissions import DEFAULT_PERMS, PERMS

bp = Blueprint("auth_users", __name__)

# ---- tiny login throttle (per IP, in memory) ----
_fails = defaultdict(deque)


def throttled(ip):
    q = _fails[ip]
    while q and time.time() - q[0] > 300:
        q.popleft()
    return len(q) >= 10


def app_config():
    return {"departments": C.DEPARTMENTS, "announcementCategories": C.ANNOUNCEMENT_CATEGORIES,
            "docCategories": C.DOC_CATEGORIES, "requestTypes": C.REQUEST_TYPES,
            "taskPriorities": C.TASK_PRIORITIES, "taskStatuses": C.TASK_STATUSES}


@bp.post("/api/auth/login")
def login():
    d = request.get_json(silent=True) or {}
    ip = request.remote_addr or "?"
    if throttled(ip):
        return fail("Too many failed attempts. Try again in a few minutes.", 429)
    email = str(d.get("email") or "").lower().strip()
    u = core.db.users.find_one({"email": email})
    if not u or not check_password_hash(u["passwordHash"], str(d.get("password") or "")):
        _fails[ip].append(time.time())
        return fail("Email or password is incorrect.", 401)
    if not u.get("active", True):
        return fail("This account is disabled. Contact the admin.", 403)
    _fails.pop(ip, None)
    remember = bool(d.get("remember"))
    exp = now() + (LONG_SESSION if remember else SHORT_SESSION)
    token = jwt.encode({"sub": str(u["_id"]), "exp": exp}, SECRET, algorithm="HS256")
    core.db.users.update_one({"_id": u["_id"]}, {"$set": {"lastLoginAt": now(), "lastSeenAt": now()}})
    return jsonify(token=token, user=public_user(u, name_map()), remember=remember)


@bp.get("/api/me")
@auth_required()
def me():
    return jsonify(user=public_user(g.user, name_map()), permissionCatalog=PERMS,
                   defaultPerms=DEFAULT_PERMS, config=app_config())


@bp.post("/api/me/password")
@auth_required()
def change_password():
    d = request.get_json(silent=True) or {}
    if not check_password_hash(g.user["passwordHash"], str(d.get("currentPassword") or "")):
        return fail("Current password is incorrect.")
    new = str(d.get("newPassword") or "")
    if len(new) < 8:
        return fail("New password must be at least 8 characters.")
    core.db.users.update_one({"_id": g.user["_id"]}, {"$set": {"passwordHash": hash_pw(new), "updatedAt": now()}})
    notify([g.user["_id"]], "password", "Your password was changed. If this was not you, tell the admin.", "account")
    return jsonify(ok=True)


# ---------------------------------------------------------------- admin: users
def _check_manager(manager_id, user_id=None):
    """Return (ObjectId|None, error). A person cannot be their own manager."""
    if not manager_id:
        return None, None
    m = core.db.users.find_one({"_id": oid(manager_id)})
    if not m:
        return None, "That manager does not exist."
    if user_id is not None and m["_id"] == user_id:
        return None, "A person cannot be their own manager."
    return m["_id"], None


def _super_count():
    return core.db.users.count_documents({"superAdmin": True, "role": "admin"})


def _job_role(role_id):
    if not role_id:
        return None
    return core.db.job_roles.find_one({"_id": oid(role_id), "active": {"$ne": False}})


@bp.get("/api/admin/job-roles")
@auth_required(admin=True)
def list_job_roles():
    rows = core.db.job_roles.find().sort("name", 1)
    return jsonify(roles=[{"id": str(r["_id"]), "name": r["name"], "department": r["department"],
                          "permissions": r.get("permissions", []), "active": r.get("active", True)} for r in rows])


@bp.post("/api/admin/job-roles")
@auth_required(admin=True)
def create_job_role():
    d = request.get_json(silent=True) or {}
    name, dept = str(d.get("name") or "").strip(), str(d.get("department") or "").strip()
    if not name or len(name) > 80 or dept not in C.DEPARTMENTS:
        return fail("A role name and a valid department are required.")
    if core.db.job_roles.find_one({"name_lc": name.casefold()}):
        return fail("That job role already exists.", 409)
    doc = {"name": name, "name_lc": name.casefold(), "department": dept,
           "permissions": clean_perms(d.get("permissions")), "active": True,
           "createdBy": g.user["email"], "createdAt": now(), "updatedAt": now()}
    result = core.db.job_roles.insert_one(doc)
    return jsonify(role={"id": str(result.inserted_id), "name": name, "department": dept,
                         "permissions": doc["permissions"], "active": True}), 201


@bp.patch("/api/admin/job-roles/<rid>")
@auth_required(admin=True)
def update_job_role(rid):
    role = core.db.job_roles.find_one({"_id": oid(rid)})
    if not role:
        return fail("Job role not found.", 404)
    d = request.get_json(silent=True) or {}
    upd = {"updatedAt": now()}
    if "name" in d:
        name = str(d.get("name") or "").strip()
        if not name or len(name) > 80:
            return fail("Role name must be 1 to 80 characters.")
        other = core.db.job_roles.find_one({"name_lc": name.casefold()})
        if other and other["_id"] != role["_id"]:
            return fail("That job role already exists.", 409)
        upd.update(name=name, name_lc=name.casefold())
    if "department" in d:
        if d["department"] not in C.DEPARTMENTS:
            return fail("Unknown department.")
        upd["department"] = d["department"]
    if "permissions" in d:
        upd["permissions"] = clean_perms(d["permissions"])
    if isinstance(d.get("active"), bool):
        upd["active"] = d["active"]
    core.db.job_roles.update_one({"_id": role["_id"]}, {"$set": upd})
    r = core.db.job_roles.find_one({"_id": role["_id"]})
    return jsonify(role={"id": str(r["_id"]), "name": r["name"], "department": r["department"],
                         "permissions": r.get("permissions", []), "active": r.get("active", True)})


@bp.delete("/api/admin/job-roles/<rid>")
@auth_required(admin=True)
def delete_job_role(rid):
    role = core.db.job_roles.find_one({"_id": oid(rid)})
    if not role:
        return jsonify(ok=True)
    core.db.job_roles.delete_one({"_id": role["_id"]})
    core.db.users.update_many({"jobRoleId": role["_id"]}, {"$unset": {"jobRoleId": "", "jobRole": ""}})
    return jsonify(ok=True)


@bp.get("/api/admin/users")
@auth_required(admin=True)
def list_users():
    users = list(core.db.users.find().sort("createdAt", 1))
    names = name_map(users)
    return jsonify(users=[public_user(u, names) for u in users])


@bp.post("/api/admin/users")
@auth_required(admin=True)
def create_user():
    d = request.get_json(silent=True) or {}
    name, email, pw = str(d.get("name") or "").strip(), str(d.get("email") or "").lower().strip(), str(d.get("password") or "")
    if not name or not email or len(pw) < 8:
        return fail("Name, email and a password of at least 8 characters are required.")
    dept = str(d.get("department") or "").strip()
    if dept and dept not in C.DEPARTMENTS:
        return fail("Unknown department.")
    job_role = _job_role(d.get("jobRoleId"))
    if d.get("jobRoleId") and not job_role:
        return fail("Choose an active job role.")
    if job_role and dept and dept != job_role["department"]:
        return fail("Department must match the selected job role.")
    if job_role:
        dept = job_role["department"]
    mgr, err = _check_manager(d.get("managerId"))
    if err:
        return fail(err)
    emp = str(d.get("employeeId") or "").strip()[:30] or next_employee_id()
    if core.db.users.find_one({"employeeId": emp}):
        return fail("That employee ID is already used.", 409)
    role = "admin" if d.get("role") == "admin" else "user"
    assignments = clean_assignments(d.get("assignments"))
    doc = {"name": name, "email": email, "passwordHash": hash_pw(pw), "role": role,
           "superAdmin": bool(role == "admin" and d.get("superAdmin") and g.user.get("superAdmin")),
           "jobTitle": job_role["name"] if job_role else str(d.get("jobTitle") or "").strip(),
           "jobRole": job_role["name"] if job_role else "", "jobRoleId": job_role["_id"] if job_role else None,
           "department": dept, "employeeId": emp,
           "managerId": mgr, "joiningDate": parse_date(d.get("joiningDate")),
           "permissions": list(job_role.get("permissions", [])) if job_role else clean_perms(d.get("permissions")), "assignments": assignments,
           "active": True, "createdBy": g.user["email"], "createdAt": now(), "updatedAt": now()}
    try:
        res = core.db.users.insert_one(doc)
    except DuplicateKeyError:
        return fail("A user with this email already exists.", 409)
    for a in assignments:
        notify([res.inserted_id], "task", f"New task assigned: {a['title']}", "tasks")
    u = core.db.users.find_one({"_id": res.inserted_id})
    return jsonify(user=public_user(u, name_map())), 201


@bp.patch("/api/admin/users/<uid>")
@auth_required(admin=True)
def update_user(uid):
    u = core.db.users.find_one({"_id": oid(uid)})
    if not u:
        return fail("User not found.", 404)
    b = request.get_json(silent=True) or {}
    is_self = u["_id"] == g.user["_id"]
    if is_self and ((b.get("role") and b["role"] != "admin") or b.get("active") is False):
        return fail("You cannot remove your own admin role or disable your own account.")
    upd = {"updatedAt": now()}
    if isinstance(b.get("name"), str) and b["name"].strip():
        upd["name"] = b["name"].strip()
    if isinstance(b.get("jobTitle"), str):
        upd["jobTitle"] = b["jobTitle"].strip()
    if "department" in b:
        dept = str(b.get("department") or "").strip()
        if dept and dept not in C.DEPARTMENTS:
            return fail("Unknown department.")
        upd["department"] = dept
    if "jobRoleId" in b:
        job_role = _job_role(b.get("jobRoleId"))
        if b.get("jobRoleId") and not job_role:
            return fail("Choose an active job role.")
        upd["jobRoleId"] = job_role["_id"] if job_role else None
        upd["jobRole"] = job_role["name"] if job_role else ""
        if job_role:
            upd["jobTitle"] = job_role["name"]
            upd["department"] = job_role["department"]
            upd["permissions"] = list(job_role.get("permissions", []))
    if "employeeId" in b:
        emp = str(b.get("employeeId") or "").strip()[:30]
        if emp:
            other = core.db.users.find_one({"employeeId": emp})
            if other and other["_id"] != u["_id"]:
                return fail("That employee ID is already used.", 409)
            upd["employeeId"] = emp
    if "managerId" in b:
        mgr, err = _check_manager(b.get("managerId"), u["_id"])
        if err:
            return fail(err)
        upd["managerId"] = mgr
    if "joiningDate" in b:
        upd["joiningDate"] = parse_date(b.get("joiningDate"))
    new_role = ("admin" if b["role"] == "admin" else "user") if b.get("role") else u["role"]
    upd["role"] = new_role
    # super admin: only a super admin may change it, and there must always be one
    want_super = bool(u.get("superAdmin"))
    if "superAdmin" in b and g.user.get("superAdmin"):
        want_super = bool(b["superAdmin"])
    if new_role != "admin":
        want_super = False
    if u.get("superAdmin") and not want_super and _super_count() <= 1:
        return fail("There must always be at least one super admin.")
    upd["superAdmin"] = want_super
    if isinstance(b.get("active"), bool):
        upd["active"] = b["active"]
    if "permissions" in b and "jobRoleId" not in b:
        upd["permissions"] = clean_perms(b["permissions"])
    if "assignments" in b:
        new_asg = clean_assignments(b["assignments"])
        old_ids = {a.get("id") for a in u.get("assignments", [])}
        for a in new_asg:
            if a["id"] not in old_ids:
                notify([u["_id"]], "task", f"New task assigned: {a['title']}", "tasks")
        upd["assignments"] = new_asg
    if b.get("password"):
        if len(str(b["password"])) < 8:
            return fail("Password must be at least 8 characters.")
        upd["passwordHash"] = hash_pw(str(b["password"]))
        notify([u["_id"]], "password", "The admin set a new password for your account.", "account")
    core.db.users.update_one({"_id": u["_id"]}, {"$set": upd})
    return jsonify(user=public_user(core.db.users.find_one({"_id": u["_id"]}), name_map()))


@bp.delete("/api/admin/users/<uid>")
@auth_required(admin=True)
def delete_user(uid):
    target = core.db.users.find_one({"_id": oid(uid)})
    if not target:
        return jsonify(ok=True)
    if target["_id"] == g.user["_id"]:
        return fail("You cannot delete your own account.")
    if target.get("superAdmin") and _super_count() <= 1:
        return fail("You cannot delete the only super admin.")
    core.db.users.delete_one({"_id": target["_id"]})
    core.db.users.update_many({"managerId": target["_id"]}, {"$set": {"managerId": None}})
    core.db.chats.delete_many({"userId": target["_id"]})
    core.db.notifications.delete_many({"userId": target["_id"]})
    return jsonify(ok=True)
