# Catalog of things an admin can grant to users. Admins implicitly have all of them.
# Entries marked "page" switch a whole page on or off for a user.
PERMS = {
    "view_dashboard":     {"label": "Dashboard",          "description": "Page: landing dashboard with your role, tasks, documents and announcements."},
    "view_tasks":         {"label": "My Tasks",           "description": "Page: see assigned tasks and update their status and progress."},
    "view_announcements": {"label": "Announcements",      "description": "Page: read company announcements and get notified about new ones."},
    "access_documents":   {"label": "Document Center",    "description": "Page: download shared documents. The assistant can also quote them with sources."},
    "chat_history":       {"label": "Chat history",       "description": "Keep and reopen previous assistant conversations."},
    "submit_requests":    {"label": "Requests",           "description": "Page: send leave, access, training and equipment requests for approval."},
    "view_reports":       {"label": "View reports",       "description": "Open and read reports published in the organization."},
    "edit_reports":       {"label": "Edit reports",       "description": "Create, change and publish reports."},
    "manage_projects":    {"label": "Manage projects",    "description": "Create projects, update their status and organize project work."},
    "access_billing":     {"label": "Billing",            "description": "See invoices, budgets and billing information."},
}

# Pre-ticked when the admin creates a new user (the admin can untick any of them).
DEFAULT_PERMS = ["view_dashboard", "view_tasks", "view_announcements", "access_documents", "chat_history", "submit_requests"]

# Added automatically (once) to existing non-admin accounts when upgrading from the first version.
UPGRADE_GRANTS = ["view_tasks", "view_announcements", "chat_history"]
