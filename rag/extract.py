"""Turn an uploaded file into searchable text chunks that remember their page number.

PDF  -> one page per PDF page (needs the `pypdf` package)
DOCX -> read directly from the file (no extra package); Word has no fixed pages, so no page number
TXT / MD / CSV -> plain text
Other types are stored for download but not searched.
"""
import io
import re
import xml.etree.ElementTree as ET
import zipfile

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_PDF_PAGES = 500
MAX_XML_BYTES = 30 * 1024 * 1024


def extract_pages(filename, data):
    """Return (pages, note). pages = [(page_number_or_None, text), ...]. note explains why a file isn't searchable."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        if ext == "pdf":
            pages, note = _pdf(data)
        elif ext == "docx":
            pages, note = _docx(data)
        elif ext in ("txt", "md", "csv"):
            pages, note = [(None, data.decode("utf-8", errors="replace"))], ""
        else:
            return [], "Stored for download only (this file type is not searchable by the assistant)."
    except Exception:  # noqa: BLE001  - a bad file must never break the upload
        return [], "Stored for download only (the text could not be read from this file)."
    if not any(t.strip() for _, t in pages):
        return [], note or "Stored for download only (no selectable text found; scanned file?)."
    return pages, ""


def _pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], "Stored for download only. Run `pip install pypdf` to make PDFs searchable."
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return [], "Stored for download only (the PDF is password protected)."
    pages = []
    for i, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        pages.append((i, page.extract_text() or ""))
    return pages, ""


def _docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > MAX_XML_BYTES:
            return [], "Stored for download only (the document is too large to index)."
        root = ET.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter(_W + "p"):
        text = "".join(t.text or "" for t in p.iter(_W + "t")).strip()
        if text:
            paras.append(text)
    return [(None, "\n".join(paras))], ""


def chunk_pages(pages, size=80, step=60, max_chunks=600):
    """Sliding word windows (size words, moving `step`), so each chunk is small enough to match one question."""
    chunks = []
    for page, text in pages:
        words = [w for w in re.sub(r"\s+", " ", text).strip().split(" ") if w]
        i = 0
        while words and i < len(words):
            chunks.append({"page": page, "text": " ".join(words[i:i + size])})
            if len(chunks) >= max_chunks:
                return chunks
            if i + size >= len(words):
                break
            i += step
    return chunks
