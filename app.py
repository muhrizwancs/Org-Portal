"""Org Portal - Flask + MongoDB Atlas. Start with:  python app.py"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

import gridfs                                                   # noqa: E402  (ships with pymongo)
from flask import Flask, request, send_from_directory           # noqa: E402
from pymongo import MongoClient                                 # noqa: E402
from pymongo.errors import ConfigurationError                   # noqa: E402

import core                                                     # noqa: E402
from core import fail, hash_pw, next_employee_id, now          # noqa: E402
from permissions import UPGRADE_GRANTS                          # noqa: E402
from rag.seed_knowledge import SEED, SEED_VERSION               # noqa: E402
from routes import admin, auth_users, chat, content, work       # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
MAX_JSON_BYTES = 200 * 1024

app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
app.json.sort_keys = False
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
for _bp in (auth_users.bp, chat.bp, content.bp, work.bp, admin.bp):
    app.register_blueprint(_bp)


# ---------------------------------------------------------------- pages & errors
@app.before_request
def limit_json_size():
    # only document uploads (multipart) may be large; JSON bodies stay small
    if request.mimetype == "application/json" and (request.content_length or 0) > MAX_JSON_BYTES:
        return fail("That request is too large.", 413)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return fail("Not found.", 404)
    return e


@app.errorhandler(Exception)
def server_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        if e.code == 413 and request.path.startswith("/api/"):
            return fail(f"That file is too large. The limit is {MAX_UPLOAD_MB} MB.", 413)
        return fail(e.description, e.code) if request.path.startswith("/api/") else e
    app.logger.exception(e)
    return fail("Something went wrong on the server.", 500)


# ---------------------------------------------------------------- startup
def sync_seed_knowledge(db):
    """Load the built-in knowledge on first start; refresh/extend it when SEED_VERSION goes up.
    Entries typed in by an admin (system=False) are never changed."""
    meta = db.meta.find_one({"_id": "seed"}) or {}
    if meta.get("version", 0) >= SEED_VERSION:
        return
    added = updated = 0
    for k in SEED:
        fields = {"title": k["title"], "keywords": k.get("keywords", ""), "text": k["text"],
                  "audience": k.get("audience", "all"), "department": k.get("department", "all"),
                  "status": "approved", "system": True}
        existing = db.knowledge.find_one({"title": k["title"], "system": True})
        if existing:
            db.knowledge.update_one({"_id": existing["_id"]}, {"$set": fields})
            updated += 1
        elif not db.knowledge.find_one({"title": k["title"]}):
            db.knowledge.insert_one({**fields, "createdAt": now()})
            added += 1
    db.meta.update_one({"_id": "seed"}, {"$set": {"version": SEED_VERSION}}, upsert=True)
    if added or updated:
        print(f"Assistant knowledge: {added} added, {updated} refreshed.")


def migrate(db):
    """Upgrade data created by the first version of the portal (safe to run on every start)."""
    # the oldest admin becomes the super admin (approves new knowledge) if nobody is yet
    if db.users.find_one({"superAdmin": True}) is None:
        first = db.users.find_one({"role": "admin"}, sort=[("createdAt", 1)])
        if first:
            db.users.update_one({"_id": first["_id"]}, {"$set": {"superAdmin": True}})
    # accounts without an employee ID (an empty or missing field both match None)
    for u in db.users.find({"employeeId": {"$in": [None, ""]}}).sort("createdAt", 1):
        db.users.update_one({"_id": u["_id"]}, {"$set": {"employeeId": next_employee_id()}})
    # one time: the new pages are switched on for existing users, who could not see them before
    if db.meta.find_one({"_id": "pages_v1"}) is None:
        for u in db.users.find({"role": "user"}):
            perms = list(u.get("permissions") or [])
            merged = perms + [p for p in UPGRADE_GRANTS if p not in perms]
            if merged != perms:
                db.users.update_one({"_id": u["_id"]}, {"$set": {"permissions": merged}})
        db.meta.insert_one({"_id": "pages_v1", "at": now()})
    # knowledge written before the approval workflow existed counts as approved
    db.knowledge.update_many({"status": {"$exists": False}}, {"$set": {"status": "approved"}})


def init_db(client=None, db_name=None):
    """Connect, create indexes, seed the knowledge base and the first admin, upgrade old data."""
    if client is None:
        client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
    if db_name:
        db = client[db_name]
    else:
        try:
            db = client.get_default_database()
        except ConfigurationError:
            db = client["orgportal"]
    core.db = db
    core.fs = gridfs.GridFS(db)
    db.users.create_index("email", unique=True)
    db.chats.create_index([("userId", 1), ("updatedAt", -1)])
    db.notifications.create_index([("userId", 1), ("createdAt", -1)])
    db.questions.create_index("createdAt")
    db.doc_chunks.create_index("docId")
    db.requests.create_index([("userId", 1), ("createdAt", -1)])

    if db.users.find_one({"role": "admin"}) is None:
        email = (os.getenv("ADMIN_EMAIL") or "admin@example.com").lower()
        db.users.insert_one({
            "name": os.getenv("ADMIN_NAME") or "Organization Admin", "email": email, "role": "admin", "superAdmin": True,
            "jobTitle": "Administrator", "department": "Management", "employeeId": "EMP-0001", "managerId": None,
            "joiningDate": None, "permissions": [], "assignments": [], "active": True,
            "passwordHash": hash_pw(os.getenv("ADMIN_PASSWORD") or "ChangeMe123!"),
            "createdBy": "system", "createdAt": now(), "updatedAt": now()})
        print(f"Created first admin: {email}")
    migrate(db)
    sync_seed_knowledge(db)
    return db


if __name__ == "__main__":
    uri = os.getenv("MONGODB_URI", "")
    if not uri or "<password>" in uri or "<cluster>" in uri:
        print("\n[!] Open the .env file and paste your MongoDB Atlas connection string into MONGODB_URI.\n")
        sys.exit(1)
    if core.SECRET.startswith("change-me") or core.SECRET == "dev-secret":
        print("[!] JWT_SECRET is still the default. Set a long random value in .env before real use.")
    try:
        init_db()
        print("Connected to MongoDB.")
    except Exception as e:  # noqa: BLE001
        print(f"\n[!] Could not connect to MongoDB Atlas: {e}")
        print("    Check the connection string in .env, and that your IP is allowed under Atlas > Network Access.\n")
        sys.exit(1)
    port = int(os.getenv("PORT", "3000"))
    print(f"\nPortal running at http://localhost:{port}\n")
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=port, debug=False)
