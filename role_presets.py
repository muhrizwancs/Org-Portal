"""Starter job-role templates for a small software house."""
from permissions import DEFAULT_PERMS


_BASE = list(DEFAULT_PERMS)

PREDEFINED_JOB_ROLES = [
    {"name": "Software Engineer", "department": "IT",
     "permissions": _BASE + ["view_reports", "manage_projects"]},
    {"name": "QA Engineer", "department": "IT",
     "permissions": _BASE + ["view_reports", "manage_projects"]},
    {"name": "DevOps Engineer", "department": "IT",
     "permissions": _BASE + ["view_reports", "manage_projects"]},
    {"name": "Project Manager", "department": "Operations",
     "permissions": _BASE + ["view_reports", "edit_reports", "manage_projects"]},
    {"name": "UI/UX Designer", "department": "Operations",
     "permissions": _BASE + ["manage_projects"]},
    {"name": "HR Specialist", "department": "HR",
     "permissions": _BASE + ["view_reports"]},
    {"name": "Finance Officer", "department": "Finance",
     "permissions": _BASE + ["view_reports", "access_billing"]},
    {"name": "Sales Executive", "department": "Sales",
     "permissions": _BASE + ["view_reports", "manage_projects"]},
]
