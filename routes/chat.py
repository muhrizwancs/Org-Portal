"""Assistant chat, saved conversations (chat history) and thumbs-up/down feedback."""
import uuid

from flask import Blueprint, g, jsonify, request

import core
from core import (auth_required, fail, has_perm, is_admin, iso, norm_question, now, oid, visible_announcements,
                  visible_documents)
from rag.engine import answer

bp = Blueprint("chat", __name__)
MAX_MESSAGES_PER_CHAT = 200


def rag_context(user):
    """Everything the assistant may use for THIS person, filtered before retrieval.
    A page the person has no access to is passed as None so the assistant says so instead of leaking it."""
    ctx = {"manager": None, "announcements": None, "documents": None, "chunks": []}
    if user.get("managerId"):
        m = core.db.users.find_one({"_id": user["managerId"]})
        if m:
            ctx["manager"] = {"name": m["name"], "email": m["email"], "jobTitle": m.get("jobTitle", "")}
    if has_perm(user, "view_announcements"):
        ctx["announcements"] = visible_announcements(user)
    if has_perm(user, "access_documents"):
        docs = visible_documents(user)
        ctx["documents"] = [{"title": d["title"], "category": d.get("category", ""), "filename": d["filename"],
                             "department": d.get("department", "all")} for d in docs]
        ids = [d["_id"] for d in docs if d.get("indexed")]
        if ids:
            by_id = {d["_id"]: d for d in docs}
            for c in core.db.doc_chunks.find({"docId": {"$in": ids}}):
                d = by_id[c["docId"]]
                ctx["chunks"].append({"title": d["title"], "file": d["filename"], "page": c.get("page"),
                                      "text": c["text"], "department": d.get("department", "all")})
    return ctx


def _chat_summary(c):
    return {"id": str(c["_id"]), "title": c.get("title", "Chat"), "updatedAt": iso(c.get("updatedAt")),
            "count": len(c.get("messages", []))}


def _ser_msg(m):
    return {"id": m["id"], "role": m["role"], "text": m["text"], "sources": m.get("sources", []),
            "feedback": m.get("feedback"), "ts": iso(m.get("ts"))}


@bp.post("/api/chat")
@auth_required()
def chat():
    d = request.get_json(silent=True) or {}
    message = str(d.get("message") or "").strip()[:500]
    if not message:
        return fail("Type a question first.")
    user = g.user
    knowledge = list(core.db.knowledge.find())
    all_users = list(core.db.users.find()) if is_admin(user) else None
    res = answer(message, user, knowledge, all_users, rag_context(user))

    # analytics log (always, even when this person has no chat history)
    core.db.questions.insert_one({"userId": user["_id"], "department": user.get("department", ""),
                                 "text": message, "norm": norm_question(message), "confidence": res["confidence"],
                                 "answered": res["confidence"] > 0, "createdAt": now()})
    out = {**res, "messageId": uuid.uuid4().hex, "chatId": None}

    if has_perm(user, "chat_history"):
        t = now()
        umsg = {"id": uuid.uuid4().hex, "role": "user", "text": message, "ts": t}
        bmsg = {"id": out["messageId"], "role": "bot", "text": res["answer"], "sources": res["sources"], "ts": t}
        chat_doc = core.db.chats.find_one({"_id": oid(d.get("chatId")), "userId": user["_id"]}) if d.get("chatId") else None
        if chat_doc:
            msgs = (chat_doc.get("messages", []) + [umsg, bmsg])[-MAX_MESSAGES_PER_CHAT:]
            core.db.chats.update_one({"_id": chat_doc["_id"]}, {"$set": {"messages": msgs, "updatedAt": t}})
            out["chatId"] = str(chat_doc["_id"])
        else:
            r = core.db.chats.insert_one({"userId": user["_id"], "title": message[:60], "messages": [umsg, bmsg],
                                          "createdAt": t, "updatedAt": t})
            out["chatId"] = str(r.inserted_id)
    return jsonify(out)


@bp.get("/api/chats")
@auth_required(perm="chat_history")
def list_chats():
    chats = list(core.db.chats.find({"userId": g.user["_id"]}).sort("updatedAt", -1).limit(100))
    return jsonify(chats=[_chat_summary(c) for c in chats])


@bp.get("/api/chats/<cid>")
@auth_required(perm="chat_history")
def get_chat(cid):
    c = core.db.chats.find_one({"_id": oid(cid), "userId": g.user["_id"]})
    if not c:
        return fail("Chat not found.", 404)
    return jsonify(chat={**_chat_summary(c), "messages": [_ser_msg(m) for m in c.get("messages", [])]})


@bp.delete("/api/chats/<cid>")
@auth_required(perm="chat_history")
def delete_chat(cid):
    core.db.chats.delete_one({"_id": oid(cid), "userId": g.user["_id"]})
    return jsonify(ok=True)


@bp.post("/api/feedback")
@auth_required()
def feedback():
    d = request.get_json(silent=True) or {}
    rating = d.get("rating")
    if rating not in ("up", "down"):
        return fail("Rating must be up or down.")
    msg_id = str(d.get("messageId") or "")[:64]
    chat_id = d.get("chatId")
    doc = {"userId": g.user["_id"], "userName": g.user["name"], "department": g.user.get("department", ""),
           "question": str(d.get("question") or "")[:500], "answer": str(d.get("answer") or "")[:800],
           "sources": [str(s)[:150] for s in (d.get("sources") or [])[:5]], "rating": rating,
           "comment": str(d.get("comment") or "")[:500], "messageId": msg_id, "createdAt": now()}
    existing = core.db.feedback.find_one({"userId": g.user["_id"], "messageId": msg_id}) if msg_id else None
    if existing:   # changing your mind replaces the earlier vote
        core.db.feedback.update_one({"_id": existing["_id"]}, {"$set": {"rating": rating, "createdAt": now()}})
    else:
        core.db.feedback.insert_one(doc)
    # remember the vote inside the saved chat so it still shows when the chat is reopened
    c = core.db.chats.find_one({"_id": oid(chat_id), "userId": g.user["_id"]}) if chat_id else None
    if c and msg_id:
        for m in c.get("messages", []):
            if m["id"] == msg_id:
                m["feedback"] = rating
        core.db.chats.update_one({"_id": c["_id"]}, {"$set": {"messages": c["messages"]}})
    return jsonify(ok=True)
