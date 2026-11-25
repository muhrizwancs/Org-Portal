"""Announcements and the Document Center."""
import io

from flask import Blueprint, g, jsonify, request, send_file
from werkzeug.utils import secure_filename

import core
import constants as C
from core import (auth_required, fail, iso, notify, now, oid, recipients, visible_announcements, visible_documents)
from rag.extract import chunk_pages, extract_pages

bp = Blueprint("content", __name__)


# ================================================================ announcements
def ser_ann(a):
    return {"id": str(a["_id"]), "title": a["title"], "body": a.get("body", ""), "category": a.get("category", ""),
            "department": a.get("department", "all"), "pinned": bool(a.get("pinned")),
            "createdByName": a.get("createdByName", ""), "createdAt": iso(a.get("createdAt"))}


def _ann_fields(d, existing=None):
    """Validate announcement input. Returns (fields, error)."""
    f = {}
    if existing is None or "title" in d:
        title = str(d.get("title") or "").strip()
        if not title:
            return None, "A title is required."
        f["title"] = title[:150]
    if existing is None or "body" in d:
        body = str(d.get("body") or "").strip()
        if not body:
            return None, "Write the announcement text."
        f["body"] = body[:4000]
    if existing is None or "category" in d:
        cat = d.get("category")
        if cat not in C.ANNOUNCEMENT_CATEGORIES:
            return None, "Choose a category."
        f["category"] = cat
    if existing is None or "department" in d:
        dept = str(d.get("department") or "all")
        if dept != "all" and dept not in C.DEPARTMENTS:
            return None, "Unknown department."
        f["department"] = dept
    if "pinned" in d:
        f["pinned"] = bool(d["pinned"])
    return f, None


@bp.get("/api/announcements")
@auth_required(perm="view_announcements")
def list_announcements():
    return jsonify(announcements=[ser_ann(a) for a in visible_announcements(g.user)])


@bp.post("/api/admin/announcements")
@auth_required(admin=True)
def create_announcement():
    f, err = _ann_fields(request.get_json(silent=True) or {})
    if err:
        return fail(err)
    f.update({"pinned": bool(f.get("pinned")), "createdBy": g.user["email"], "createdByName": g.user["name"],
              "createdAt": now()})
    res = core.db.announcements.insert_one(f)
    notify(recipients("view_announcements", f["department"], exclude=g.user["_id"]), "announcement",
           f"New announcement: {f['title']}", "announcements")
    return jsonify(announcement=ser_ann(core.db.announcements.find_one({"_id": res.inserted_id}))), 201


@bp.patch("/api/admin/announcements/<aid>")
@auth_required(admin=True)
def update_announcement(aid):
    a = core.db.announcements.find_one({"_id": oid(aid)})
    if not a:
        return fail("Announcement not found.", 404)
    f, err = _ann_fields(request.get_json(silent=True) or {}, existing=a)
    if err:
        return fail(err)
    if f:
        core.db.announcements.update_one({"_id": a["_id"]}, {"$set": f})
    return jsonify(announcement=ser_ann(core.db.announcements.find_one({"_id": a["_id"]})))


@bp.delete("/api/admin/announcements/<aid>")
@auth_required(admin=True)
def delete_announcement(aid):
    core.db.announcements.delete_one({"_id": oid(aid)})
    return jsonify(ok=True)


# ================================================================ document center
def ser_doc(d):
    return {"id": str(d["_id"]), "title": d["title"], "category": d.get("category", "Other"),
            "department": d.get("department", "all"), "filename": d["filename"], "size": d.get("size", 0),
            "jobRoleIds": [str(rid) for rid in d.get("jobRoleIds", [])],
            "jobRoles": [r["name"] for r in core.db.job_roles.find({"_id": {"$in": d.get("jobRoleIds", [])}})],
            "version": d.get("version", 1), "indexed": bool(d.get("indexed")), "indexNote": d.get("indexNote", ""),
            "chunkCount": d.get("chunkCount", 0), "uploadedByName": d.get("uploadedByName", ""),
            "createdAt": iso(d.get("createdAt")), "updatedAt": iso(d.get("updatedAt"))}


@bp.get("/api/documents")
@auth_required(perm="access_documents")
def list_documents():
    return jsonify(documents=[ser_doc(d) for d in visible_documents(g.user)])


@bp.get("/api/documents/<did>/download")
@auth_required(perm="access_documents")
def download_document(did):
    d = core.db.documents.find_one({"_id": oid(did)})
    if not d or d not in visible_documents(g.user):
        return fail("Document not found.", 404)
    try:
        data = core.fs.get(d["fileId"]).read()
    except Exception:  # noqa: BLE001
        return fail("The stored file is missing. Ask the admin to upload it again.", 404)
    resp = send_file(io.BytesIO(data), mimetype=d.get("contentType") or "application/octet-stream",
                     as_attachment=True, download_name=d["filename"])
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _read_upload():
    """Return (filename, bytes) or (None, None) when no file was sent. Raises ValueError for a bad file."""
    f = request.files.get("file")
    if not f or not f.filename:
        return None, None
    name = secure_filename(f.filename) or "document"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in C.ALLOWED_UPLOAD_EXT:
        raise ValueError("This file type is not allowed. Allowed: " + ", ".join(sorted(C.ALLOWED_UPLOAD_EXT)) + ".")
    data = f.read()
    if not data:
        raise ValueError("The file is empty.")
    return name, data


def _meta_fields(form, allow_inactive_roles=False):
    title = str(form.get("title") or "").strip()
    cat = form.get("category") or "Other"
    dept = form.get("department") or "all"
    if cat not in C.DOC_CATEGORIES:
        return None, "Choose a category."
    if dept != "all" and dept not in C.DEPARTMENTS:
        return None, "Unknown department."
    raw_role_ids = form.getlist("jobRoleIds") if hasattr(form, "getlist") else form.get("jobRoleIds", [])
    if isinstance(raw_role_ids, str):
        raw_role_ids = [raw_role_ids]
    role_ids = []
    for raw_id in raw_role_ids or []:
        role_id = oid(raw_id)
        role_filter = {"_id": role_id}
        if not allow_inactive_roles:
            role_filter["active"] = {"$ne": False}
        role = core.db.job_roles.find_one(role_filter) if role_id else None
        if not role:
            return None, "Choose active job roles for document access."
        if role["_id"] not in role_ids:
            role_ids.append(role["_id"])
    return {"title": title[:150], "category": cat, "department": dept, "jobRoleIds": role_ids}, None


def _index(doc_id, filename, data):
    """Extract text, split into chunks and store them. Returns (indexed, note, chunk_count)."""
    core.db.doc_chunks.delete_many({"docId": doc_id})
    pages, note = extract_pages(filename, data)
    chunks = chunk_pages(pages)
    if chunks:
        core.db.doc_chunks.insert_many([{"docId": doc_id, "page": c["page"], "n": i, "text": c["text"]}
                                        for i, c in enumerate(chunks)])
    return bool(chunks), note, len(chunks)


@bp.post("/api/admin/documents")
@auth_required(admin=True)
def upload_document():
    meta, err = _meta_fields(request.form)
    if err:
        return fail(err)
    try:
        name, data = _read_upload()
    except ValueError as e:
        return fail(str(e))
    if not name:
        return fail("Choose a file to upload.")
    meta["title"] = meta["title"] or name.rsplit(".", 1)[0].replace("_", " ")
    file_id = core.fs.put(data, filename=name, content_type=request.files["file"].mimetype)
    doc = {**meta, "filename": name, "contentType": request.files["file"].mimetype, "size": len(data),
           "fileId": file_id, "version": 1, "uploadedBy": g.user["email"], "uploadedByName": g.user["name"],
           "createdAt": now(), "updatedAt": now()}
    res = core.db.documents.insert_one(doc)
    indexed, note, n = _index(res.inserted_id, name, data)
    core.db.documents.update_one({"_id": res.inserted_id}, {"$set": {"indexed": indexed, "indexNote": note, "chunkCount": n}})
    notify(recipients("access_documents", meta["department"], exclude=g.user["_id"]), "document",
           f"New document: {meta['title']}", "documents")
    return jsonify(document=ser_doc(core.db.documents.find_one({"_id": res.inserted_id}))), 201


@bp.patch("/api/admin/documents/<did>")
@auth_required(admin=True)
def update_document(did):
    d = core.db.documents.find_one({"_id": oid(did)})
    if not d:
        return fail("Document not found.", 404)
    meta, err = _meta_fields({"title": request.form.get("title", d["title"]),
                              "category": request.form.get("category", d.get("category", "Other")),
                              "department": request.form.get("department", d.get("department", "all")),
                              "jobRoleIds": request.form.getlist("jobRoleIds")}, allow_inactive_roles=True)
    if err:
        return fail(err)
    meta["title"] = meta["title"] or d["title"]
    upd = {**meta, "updatedAt": now()}
    try:
        name, data = _read_upload()
    except ValueError as e:
        return fail(str(e))
    if name:   # a new file replaces the old one and becomes the next version
        new_id = core.fs.put(data, filename=name, content_type=request.files["file"].mimetype)
        try:
            core.fs.delete(d["fileId"])
        except Exception:  # noqa: BLE001
            pass
        indexed, note, n = _index(d["_id"], name, data)
        upd.update({"filename": name, "contentType": request.files["file"].mimetype, "size": len(data), "fileId": new_id,
                    "version": d.get("version", 1) + 1, "indexed": indexed, "indexNote": note, "chunkCount": n})
    core.db.documents.update_one({"_id": d["_id"]}, {"$set": upd})
    notify(recipients("access_documents", meta["department"], exclude=g.user["_id"]), "document",
           f"Document updated: {meta['title']}" + (f" (version {upd['version']})" if name else ""), "documents")
    return jsonify(document=ser_doc(core.db.documents.find_one({"_id": d["_id"]})))


@bp.delete("/api/admin/documents/<did>")
@auth_required(admin=True)
def delete_document(did):
    d = core.db.documents.find_one({"_id": oid(did)})
    if d:
        try:
            core.fs.delete(d["fileId"])
        except Exception:  # noqa: BLE001
            pass
        core.db.doc_chunks.delete_many({"docId": d["_id"]})
        core.db.documents.delete_one({"_id": d["_id"]})
    return jsonify(ok=True)
