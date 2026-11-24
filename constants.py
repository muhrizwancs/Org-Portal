"""Lists used by the portal. Edit these to match your organization."""

DEPARTMENTS = ["HR", "IT", "Finance", "Sales", "Operations", "Management"]

ANNOUNCEMENT_CATEGORIES = ["New policy", "Holiday notice", "Company update", "Training program"]
HOLIDAY_CATEGORY = "Holiday notice"

DOC_CATEGORIES = ["Handbook", "Policy", "Form", "Guide", "Other"]

REQUEST_TYPES = ["Leave", "Access", "Training", "Equipment", "Other"]
REQUEST_STATUSES = ["Pending", "Approved", "Rejected", "Cancelled"]

TASK_PRIORITIES = ["High", "Medium", "Low"]
TASK_STATUSES = ["Assigned", "In Progress", "Completed"]

KNOWLEDGE_STATUSES = ["draft", "pending", "approved", "rejected"]

# Files the Document Center accepts. Only INDEXABLE types are read by the assistant.
INDEXABLE_EXT = {"pdf", "docx", "txt", "md", "csv"}
ALLOWED_UPLOAD_EXT = INDEXABLE_EXT | {"doc", "xls", "xlsx", "ppt", "pptx", "png", "jpg", "jpeg"}
