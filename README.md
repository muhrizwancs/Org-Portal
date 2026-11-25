# Org Portal (Flask) with a role-aware RAG assistant

A web app for an organization: **admins** and **users**. A built-in assistant (RAG) answers each person
according to their role, department, tasks and the company documents they may open, and shows the
**file and page** it used.

* **Backend:** Python + Flask, JWT login, hashed passwords
* **Database:** MongoDB Atlas (uploaded files are stored in Atlas too, using GridFS)
* **RAG:** runs fully inside the app. No OpenAI/Claude/other API calls and no external data.
* **UI:** plain HTML/CSS/JS (no build step), light and dark mode, works on phones

## Run it

1. Install Python 3.9 or newer.
2. Open `.env` and paste your Atlas string into `MONGODB_URI`
   (Atlas > Database > Connect > Drivers). Replace `<password>`, and keep a database name such as `/orgportal`.
   In Atlas > Network Access, allow your IP address.
3. In this folder run:
   ```
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
4. Open http://localhost:3000 and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`
   (the first admin is created automatically and becomes the **super admin**).

**Upgrading from the first version?** Just `pip install -r requirements.txt` again (adds `pypdf`) and start the app.
Your users, passwords, knowledge and assignments are kept. On first start the app adds employee IDs,
makes your oldest admin the super admin, and switches on *My Tasks*, *Announcements* and *Chat history* once for existing users.

**Try it without a database:** `python tests/demo_server.py` starts the portal with sample data in memory.
Sign in as `boss@org.com` / `BossPass123!` (admin) or `sara@org.com` / `Password123!` (HR user).

## Pages and who can open them

Admins define reusable job roles under **Job roles**, including a department and default page access. When creating a non-admin user, the admin selects a defined job role; its title, department, and access are assigned together. User creation does not offer separate permission checkboxes.

| Page | Access setting | What it does |
|---|---|---|
| Dashboard | Dashboard | Role, department, assigned/pending tasks, documents available, latest announcements (admins also see org numbers) |
| Assistant | always | Chat with suggested questions, source chips, thumbs up/down. Saved chats on the left if *Chat history* is on |
| My Tasks | My Tasks | Board (Assigned / In Progress / Completed) with priority, due date, progress. People update their own status |
| Announcements | Announcements | Policies, holiday notices, company updates, training. Can target one department and be pinned |
| Documents | Document Center | Search and download handbooks, policies, forms. Admin uploads, replaces (new version), deletes |
| Requests | Requests | Leave / access / training / equipment requests with a Submitted > Admin review > Approved/Rejected flow |
| Profile | always | Name, employee ID, role, department, manager, joining date (admin edits them) |
| Account | always | Change password |
| Notifications (bell) | always | New task, announcement, document update, password change, request decisions |

Admin only: **Approvals** (decide requests), **Team tasks**, **Users**, **Knowledge**, **Feedback**, **Analytics**.

## Roles

Job roles (for example, **AI Engineer** in **IT**) are organization-defined templates. They are separate from account types and supply a user's job title, department, and default feature access when assigned.

* **Super admin:** the first admin. Approves or rejects knowledge entries written by other admins, and can promote
  other super admins (there is always at least one).
* **Admin:** manages users, access, tasks, announcements, documents and requests. Knowledge entries start as
  *draft* or *pending* until the super admin approves them.
* **User:** uses the pages the admin switched on.

## How the RAG works (`rag/engine.py`)

1. For every question a corpus is built for that person only, **before** any matching happens:
   * approved knowledge entries (audience `all`, or `admin` for admins)
   * live records: profile, manager and department, tasks, announcements and holidays, documents available
   * text pieces of uploaded documents they are allowed to see (their department's and company-wide ones),
     only if they have *Document Center* access
   * admins also get a live organization overview
2. The question and documents are embedded with a concept-aware TF-IDF vector (synonyms collapse to shared concepts).
3. The closest pieces by cosine similarity are returned. Entries for the asker's **own department are boosted**
   and other departments' entries are down-weighted, so an HR employee asking about leave gets the HR answer first.
4. Answers from files end with `Source: HR_Policy_2026.pdf, page 12` and show a source chip.

Documents: PDF (needs `pypdf`, already in `requirements.txt`), Word `.docx` and `.txt/.md/.csv` are read.
Word files have no fixed pages, so they are cited by file name only. Other types (xlsx, pptx, images) can be
downloaded but are not searched. Scanned PDFs without selectable text are stored but not searchable.

"Ask about me" works because tasks, manager, department, documents and announcements are read live from the database
on every question.

## Knowledge approval workflow

`draft` > `pending` > `approved` / `rejected`. Only **approved** entries are used by the assistant.
The super admin's own entries are approved immediately. Authors are notified of decisions.

## Customize

* Pages/features users can be granted: `permissions.py`
* Departments, announcement/document/request categories, task priorities: `constants.py`
* Starting knowledge: `rag/seed_knowledge.py` (bump `SEED_VERSION` to refresh built-in entries on the next start)
* Synonyms and matching: `GROUPS` in `rag/engine.py`

## Tests

`python tests/run_tests.py` runs 148 end-to-end checks of the real routes (access control, department
isolation, citations, approvals, upgrade from v1) against an in-memory stand-in for MongoDB. No database needed.
`python rag/selftest.py` prints retrieval results for sample questions.

## Notes

* Start with `python app.py` (not `flask run`), because startup connects to Atlas and creates the first admin.
* "Questions (24 h)" in Analytics is a rolling 24 hours, so it does not depend on time zones. The daily chart uses
  the browser's local days.
* Each question loads the visible document pieces and re-scores them in memory. This is fine for a company
  handbook library (thousands of pieces). For very large libraries move retrieval to a vector database.
* *View reports, Edit reports, Manage projects, Billing* are still access flags only; no pages exist for them.
* Free Atlas clusters hold 512 MB, which includes uploaded files.
* For production: serve over HTTPS (for example behind nginx or a host such as Render), use a strong
  `JWT_SECRET`, and run with a production server such as `gunicorn` instead of the built-in one.
