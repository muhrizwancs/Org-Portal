"""
Local RAG engine - no external APIs, no external data.

 1. Build a corpus for THIS request:
      - knowledge entries from MongoDB, filtered by the asker's role (audience)
      - "live" documents generated from the asker's own records (profile, access, assignments)
      - for admins only: an organization overview generated from all accounts
 2. Embed query + documents into a concept-aware TF-IDF space (synonyms collapse to shared
    concepts, so "position" matches "role", "tasks" matches "assignments", etc.).
 3. Retrieve the closest documents by cosine similarity and compose the answer from them.

Because role filtering happens BEFORE retrieval, a regular user can never retrieve admin-only text.

Extra context (`ctx`, built per request by the app and already filtered for this person):
  announcements, documents, chunks (text pieces of uploaded files, with file name and page), manager.
Knowledge entries and documents carry a department; entries for the asker's own department are
boosted and other departments' entries are down-weighted, so an HR employee asking about "leave"
gets the HR answer first.
"""
import datetime as dt
import math
import re

from constants import HOLIDAY_CATEGORY
from permissions import PERMS

# concept groups: first word is the canonical concept
GROUPS = [
    ["c_role", "role", "roles", "position", "title", "designation", "job", "who", "identity", "profile", "account", "status", "level", "about"],
    ["c_perm", "permission", "permissions", "access", "allow", "allowed", "can", "able", "use", "used", "uses", "using", "usable", "privilege", "privileges", "right", "rights", "authorize", "authorized", "feature", "features", "capability", "capabilities", "do", "entitled", "granted", "grant", "open", "unlock"],
    ["c_assign", "assign", "assigned", "assignment", "assignments", "task", "tasks", "duty", "duties", "work", "responsibility", "responsibilities", "project", "projects", "given", "allocated", "todo", "handle", "handling"],
    ["c_admin", "admin", "administrator", "control", "manage", "administer", "owner"],
    ["c_mgr", "manager", "managers", "supervisor", "boss", "reporting", "lead", "superior"],
    ["c_dept", "department", "departments", "dept", "division"],
    ["c_doc", "document", "documents", "doc", "docs", "file", "files", "handbook", "form", "forms", "download", "sop", "guideline", "guidelines", "manual", "pdf"],
    ["c_news", "announcement", "announcements", "news", "notice", "notices", "circular", "update", "updates", "latest", "recent"],
    ["c_holiday", "holiday", "holidays", "festival", "festivals", "vacation"],
    ["c_taskstat", "pending", "overdue", "deadline", "due", "progress", "completed", "complete", "priority", "urgent", "unfinished", "remaining"],
    ["c_team", "user", "users", "member", "members", "employee", "employees", "staff", "people", "colleague", "colleagues", "team", "everyone", "organization", "organisation", "org", "company", "overview", "many"],
    ["c_pass", "password", "passwords", "login", "signin", "credential", "credentials", "reset", "forgot", "forget"],
    ["c_hello", "hello", "hi", "hey", "greetings", "help", "assistant", "bot", "chatbot", "rag", "ai", "start"],
]
STOP = set("a an the is am are was be i me my mine myself to of for and or in on it what whats does this that with you your please tell show give we our have has at as by there any all if so how".split())
FIRST_PERSON = {"my", "me", "mine", "myself", "am"}
FIRST_PERSON_RE = re.compile(r"\b(what (can|could|do|am|should) i|can i|who am i|am i)\b")


def stem(w):
    if len(w) > 4:
        for s in ("ing", "ed", "es", "s", "ly"):
            if w.endswith(s) and len(w) - len(s) >= 3:
                return w[: -len(s)]
    return w


CONCEPT = {}
for _g in GROUPS:
    for _w in _g:
        CONCEPT[_w] = _g[0]
        CONCEPT[stem(_w)] = _g[0]


def tokenize(text):
    words = re.sub(r"[^a-z0-9\s]", " ", str(text).lower()).split()
    out = []
    for w in words:
        if w in CONCEPT:
            out.append(CONCEPT[w])
            continue
        if w in STOP:
            continue
        s = stem(w)
        out.append(CONCEPT.get(s, s))
    return out


def fmt_date(d):
    if isinstance(d, (dt.datetime, dt.date)):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, str) and d:
        return d[:10]
    return "unknown date"


def build_live_docs(user, all_users, ctx=None):
    ctx = ctx or {}
    is_admin = user.get("role") == "admin"
    granted = list(PERMS) if is_admin else [p for p in (user.get("permissions") or []) if p in PERMS]
    denied = [p for p in PERMS if p not in granted]
    dept = user.get("department") or ""
    manager = ctx.get("manager")
    docs = []

    profile = f"You are **{user.get('name')}** ({user.get('email')}).\nYour role: **{'Admin' if is_admin else 'User'}**."
    if user.get("jobTitle"):
        profile += f"\nYour job title: **{user['jobTitle']}**."
    profile += f"\nYour department: **{dept}**." if dept else "\nYour department: not set yet (the admin can set it in your profile)."
    if user.get("employeeId"):
        profile += f"\nYour employee ID: **{user['employeeId']}**."
    if manager:
        profile += f"\nYour manager: **{manager['name']}**."
    if user.get("joiningDate"):
        profile += f"\nYou joined on {fmt_date(user['joiningDate'])}."
    profile += "\n" + (
        "As the admin you control accounts, access and assignments for the whole organization."
        if is_admin else
        "As a user you can use the features the admin has granted to you and you work on the assignments the admin gives you."
    )
    profile += f"\nYour account was created on {fmt_date(user.get('createdAt'))} and is {'active' if user.get('active', True) else 'disabled'}."
    docs.append({"title": "Your profile and role", "personal": True,
                 "keywords": "my role who am i profile position title job account identity what am i status employee id joining date joined", "text": profile})

    if manager:
        mtext = f"Your manager is **{manager['name']}**" + (f", {manager['jobTitle']}" if manager.get("jobTitle") else "") + f" ({manager['email']})."
    else:
        mtext = "No manager has been set for you yet. The admin can set one in your profile."
    mtext += f"\nYou belong to the **{dept}** department." if dept else "\nYou have not been placed in a department yet."
    docs.append({"title": "Your manager and department", "personal": True,
                 "keywords": "my manager supervisor boss reports to reporting department team who is my manager which department", "text": mtext})

    if is_admin:
        head = "As admin you have access to **every** feature:"
    elif granted:
        head = "The admin has granted you access to:"
    else:
        head = "The admin has not granted you access to any features yet."
    perm_text = head
    if granted:
        perm_text += "\n" + "\n".join(f"- **{PERMS[p]['label']}**: {PERMS[p]['description']}" for p in granted)
    if not is_admin and denied:
        perm_text += f"\n\nNot granted to you: {', '.join(PERMS[p]['label'] for p in denied)}. Ask the admin if you need any of these."
    docs.append({"title": "Your access and permissions", "personal": True,
                 "keywords": "my access permissions what can i use do allowed features granted rights capabilities available pages", "text": perm_text})

    asg = user.get("assignments") or []
    if asg:
        today = dt.date.today().isoformat()
        done = sum(1 for a in asg if a.get("status") == "Completed")
        prog = sum(1 for a in asg if a.get("status") == "In Progress")
        pending = len(asg) - done
        overdue = sum(1 for a in asg if a.get("dueDate") and a["dueDate"] < today and a.get("status") != "Completed")
        s = "s" if len(asg) > 1 else ""
        asg_text = (f"You have {len(asg)} task{s}: {pending} pending ({prog} in progress), {done} completed"
                    + (f", {overdue} overdue" if overdue else "") + ".\n")
        lines = []
        for a in asg:
            bit = f"- **{a.get('title')}** [{a.get('priority') or 'Medium'} priority] - {a.get('status') or 'Assigned'}, {int(a.get('progress') or 0)}%"
            if a.get("dueDate"):
                bit += f", due {a['dueDate']}" + (" (overdue)" if a["dueDate"] < today and a.get("status") != "Completed" else "")
            if a.get("description"):
                bit += f". {a['description']}"
            lines.append(bit)
        asg_text += "\n".join(lines)
    else:
        asg_text = "Nothing has been assigned to you yet. The admin will add assignments when there is work for you."
    docs.append({"title": "Your assignments and tasks", "personal": True,
                 "keywords": "my assignments tasks assigned work duties responsibilities projects given by admin todo pending completed due deadline priority progress status overdue", "text": asg_text})

    # announcements / holidays / documents: None in ctx means the person has no access to that page
    if "announcements" in ctx:
        ann = ctx["announcements"]
        if ann is None:
            docs.append({"title": "Announcements", "personal": False, "keywords": "announcements news notices updates holidays",
                         "text": "The Announcements page has not been enabled for you. Ask the admin if you need it."})
        else:
            if ann:
                atext = "Latest announcements:\n" + "\n".join(
                    f"- **{a['title']}** ({a.get('category', 'Update')}, {fmt_date(a.get('createdAt'))})" for a in ann[:5])
            else:
                atext = "No announcements have been posted yet."
            docs.append({"title": "Recent announcements", "personal": False,
                         "keywords": "announcements announcement news notice notices updates latest recent company circular training policy", "text": atext})
            hol = [a for a in ann if a.get("category") == HOLIDAY_CATEGORY]
            if hol:
                htext = "Holiday notices:\n" + "\n".join(
                    f"- **{a['title']}** ({fmt_date(a.get('createdAt'))}): {str(a.get('body', ''))[:240]}" for a in hol[:5])
            else:
                htext = "No holiday notices have been posted yet. Check Announcements again later or ask the admin."
            docs.append({"title": "Company holidays", "personal": False,
                         "keywords": "holidays holiday company festival vacation days off calendar notice", "text": htext})

    if "documents" in ctx:
        dl = ctx["documents"]
        if dl is None:
            dtext = "The Document Center has not been enabled for you. Ask the admin if you need it."
        elif dl:
            ordered = sorted(dl, key=lambda d: 0 if dept and d.get("department") == dept else 1)
            dtext = (f"{len(dl)} document{'s' if len(dl) != 1 else ''} available to you" + (f", starting with those for **{dept}**" if dept else "") + ":\n"
                     + "\n".join(f"- **{d['title']}** ({d.get('category', 'Document')}"
                                  + (f", {d['department']} department" if d.get("department") not in (None, '', 'all') else ", everyone")
                                  + f") - {d['filename']}" for d in ordered[:15])
                     + "\nOpen **Documents** in the menu to download them.")
        else:
            dtext = "No documents have been uploaded for you yet."
        docs.append({"title": "Documents for you and your department", "personal": True,
                     "keywords": "documents relevant department my files policies handbook forms available download library", "text": dtext})

    for ch in ctx.get("chunks") or []:
        docs.append({"title": ch["title"], "personal": False, "keywords": "", "text": ch["text"],
                     "file": ch["file"], "page": ch.get("page"), "department": ch.get("department", "all")})

    if is_admin and all_users is not None:
        active = sum(1 for u in all_users if u.get("active", True))
        lines = []
        for u in all_users:
            admin_u = u.get("role") == "admin"
            lines.append(
                f"- **{u.get('name')}** - {'Admin' if admin_u else 'User'}"
                + (f", {u['jobTitle']}" if u.get("jobTitle") else "")
                + (f", {u['department']}" if u.get("department") else "")
                + f"; {'all access' if admin_u else str(len(u.get('permissions') or [])) + ' feature(s)'}"
                + f"; {len(u.get('assignments') or [])} assignment(s)"
                + ("" if u.get("active", True) else " [disabled]"))
        n = len(all_users)
        docs.append({"title": "Organization overview (live)", "personal": False, "team_doc": True,
                     "keywords": "organization team users members staff people employees list overview who how many accounts",
                     "text": f"The organization has **{n}** account{'' if n == 1 else 's'} ({active} active).\n" + "\n".join(lines)})
    return docs


def embed(tokens, idf):
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    vec, norm = {}, 0.0
    for t, c in tf.items():
        v = (1 + math.log(c)) * idf.get(t, 1)
        vec[t] = v
        norm += v * v
    norm = math.sqrt(norm) or 1.0
    return {t: v / norm for t, v in vec.items()}


def cosine(a, b):
    return sum(v * b[t] for t, v in a.items() if t in b)


def answer(query, user, knowledge, all_users=None, ctx=None):
    is_admin = user.get("role") == "admin"
    dept = (user.get("department") or "").strip().lower()
    # Role-scoped corpus (security boundary: filtering happens before retrieval).
    # Knowledge entries that are not approved are never searched.
    static_docs = [
        {"title": k["title"], "keywords": k.get("keywords", ""), "text": k["text"], "personal": False,
         "department": k.get("department", "all")}
        for k in knowledge
        if k.get("status", "approved") == "approved"
        and (k.get("audience", "all") == "all" or (k.get("audience") == "admin" and is_admin))
    ]
    docs = build_live_docs(user, all_users if is_admin else None, ctx) + static_docs

    # Personal records carry long lists of details (names, dates, task lines). Those are data, not matching
    # terms, so only the first line of their text is embedded; otherwise longer records would score lower.
    doc_tokens = [tokenize(f"{d['title']} {d['title']} {d['keywords']} {d['text'].split(chr(10))[0][:200] if d['personal'] else d['text']}")
                  for d in docs]
    df = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n = len(docs)
    idf = {t: math.log(1 + n / (1 + c)) + 0.5 for t, c in df.items()}

    q = str(query).lower()
    q_words = re.sub(r"[^a-z\s]", " ", q).split()
    first_person = any(w in FIRST_PERSON for w in q_words) or bool(FIRST_PERSON_RE.search(q))
    q_tokens = tokenize(query)
    asks_team = "c_team" in q_tokens
    q_vec = embed(q_tokens, idf)

    scored = []
    for d, toks in zip(docs, doc_tokens):
        s = cosine(q_vec, embed(toks, idf))
        if first_person and d["personal"]:
            s *= 1.6
        # questions about "the users/team" (not "me") should not be answered with the asker's own profile
        if not first_person and asks_team and d["personal"]:
            s *= 0.55
        if asks_team and d.get("team_doc"):
            s *= 1.4
        # department-aware knowledge: own department first, other departments' entries down-weighted
        d_dept = str(d.get("department") or "all").strip().lower()
        if d_dept not in ("all", ""):
            s *= 1.3 if d_dept == dept else 0.7
        scored.append((s, d))
    scored.sort(key=lambda x: x[0], reverse=True)

    THRESH = 0.12
    if not scored or scored[0][0] < THRESH:
        return {"answer": "I could not find anything about that in the portal's records. Try asking about your role, your access, your assignments, your documents, or how something works in this organization.",
                "sources": [], "confidence": 0}
    picked, seen_loc = [], set()
    for s, d in scored[:6]:
        if s < THRESH or (picked and s < scored[0][0] * 0.8) or len(picked) >= 3:
            break
        loc = (d.get("file"), d.get("page"))
        if d.get("file") and loc in seen_loc:        # overlapping chunks of the same page: show once
            continue
        seen_loc.add(loc)
        picked.append((s, d))

    def body(d):
        if d.get("file"):
            where = f", page {d['page']}" if d.get("page") else ""
            return f"From **{d['file']}**{where}:\n{d['text']}"
        return d["text"]

    cited = [d for _, d in picked if d.get("file")]
    text = "\n\n".join(body(d) for _, d in picked)
    if cited:
        text += "\n\nSource: " + "; ".join(f"{d['file']}" + (f", page {d['page']}" if d.get("page") else "") for d in cited)
    return {
        "answer": text,
        "sources": [{"title": d["title"], "personal": bool(d["personal"]), "score": round(s, 2),
                     "file": d.get("file"), "page": d.get("page")} for s, d in picked],
        "confidence": round(scored[0][0], 2),
    }
