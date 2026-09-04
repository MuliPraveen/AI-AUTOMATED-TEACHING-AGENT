"""Document parsing -> clean, semantically-sized chunks.

PDF via PyMuPDF (fast C parser); txt/md natively. Chunking is section-aware
with a token-budget sliding window and overlap, which measurably improves
retrieval precision over naive fixed-size splits.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.schemas import Chunk

_WS = re.compile(r"[ \t]+")
_MULTINL = re.compile(r"\n{3,}")
_HEADING = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+[A-Z].{2,80}|[A-Z][A-Z \-&/]{4,80}|#{1,4}\s+.{2,90})$"
)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


@dataclass
class Page:
    number: int
    text: str


def _clean(text: str) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _WS.sub(" ", text)
    return _MULTINL.sub("\n\n", text).strip()


def _read_docx(data: bytes) -> list[Page]:
    """DOCX without external deps: unzip document.xml and pull paragraph text.
    Heading styles are recovered so the section splitter still works."""
    import io
    import re as _re
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    paras: list[str] = []
    for p in _re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, _re.S):
        text = "".join(_re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, _re.S))
        text = (text.replace("&amp;", "&").replace("&lt;", "<")
                    .replace("&gt;", ">").replace("&quot;", '"').strip())
        if not text:
            continue
        is_heading = bool(_re.search(r'w:val="(?:Heading|Title)', p))
        paras.append(f"# {text}" if is_heading else text)
    return _paginate("\n\n".join(paras))


def _read_pptx(data: bytes) -> list[Page]:
    """PPTX: one Page per slide, slide title promoted to a heading."""
    import io
    import re as _re
    import zipfile

    pages: list[Page] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(
            (n for n in z.namelist() if _re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(_re.findall(r"\d+", n)[-1]),
        )
        for i, name in enumerate(names):
            xml = z.read(name).decode("utf-8", errors="ignore")
            runs = [t.strip() for t in _re.findall(r"<a:t>(.*?)</a:t>", xml, _re.S)]
            runs = [r.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                    for r in runs if r.strip()]
            if not runs:
                continue
            body = f"# {runs[0]}\n" + "\n".join(runs[1:])
            pages.append(Page(i + 1, _clean(body)))
    return [p for p in pages if p.text]


def _paginate(text: str, size: int = 3000) -> list[Page]:
    parts, buf, n = [], [], 0
    for para in text.split("\n\n"):
        buf.append(para)
        n += len(para)
        if n > size:
            parts.append(_clean("\n\n".join(buf)))
            buf, n = [], 0
    if buf:
        parts.append(_clean("\n\n".join(buf)))
    return [Page(i + 1, t) for i, t in enumerate(parts) if t]


def read_pages(filename: str, data: bytes) -> list[Page]:
    """Dispatch on extension, but always sniff the real container first.

    Office formats are ZIPs and PDFs start with %PDF-; if the extension lies (a
    common real-world case), we fall back to plain-text rather than crashing.
    """
    lower = filename.lower()
    is_zip = data[:2] == b"PK"
    is_pdf = data[:5] == b"%PDF-"

    try:
        if lower.endswith(".docx") and is_zip:
            return _read_docx(data)
        if lower.endswith(".pptx") and is_zip:
            return _read_pptx(data)
        if lower.endswith(".pdf") or is_pdf:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=data, filetype="pdf")
            pages = [Page(i + 1, _clean(p.get_text("text"))) for i, p in enumerate(doc)]
            doc.close()
            pages = [p for p in pages if p.text]
            if pages:
                return pages
        elif is_zip:  # .zip-backed office file with an unexpected extension
            try:
                return _read_docx(data)
            except Exception:
                return _read_pptx(data)
    except Exception:
        pass  # fall through to plain-text extraction

    return _paginate(data.decode("utf-8", errors="ignore"))


def _sections(page: Page) -> list[tuple[str, str]]:
    """Split a page into (section_title, body) pairs using heading heuristics."""
    out: list[tuple[str, str]] = []
    title, body = "", []
    for line in page.text.split("\n"):
        s = line.strip()
        if s and _HEADING.match(s) and len(s.split()) <= 12:
            if body:
                out.append((title, "\n".join(body).strip()))
                body = []
            title = s.lstrip("# ").strip()
        else:
            body.append(line)
    if body:
        out.append((title, "\n".join(body).strip()))
    return [(t, b) for t, b in out if b]


def chunk_document(
    doc_id: str, filename: str, data: bytes, *, target_chars: int = 1100, overlap: int = 150
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in read_pages(filename, data):
        for section, body in _sections(page):
            start = 0
            while start < len(body):
                end = min(len(body), start + target_chars)
                if end < len(body):  # snap to sentence boundary
                    dot = body.rfind(". ", start + target_chars // 2, end)
                    if dot != -1:
                        end = dot + 1
                piece = body[start:end].strip()
                if len(piece) > 60:
                    cid = hashlib.sha1(
                        f"{doc_id}:{page.number}:{start}:{piece[:40]}".encode()
                    ).hexdigest()[:16]
                    chunks.append(
                        Chunk(
                            id=cid,
                            doc_id=doc_id,
                            text=piece,
                            page=page.number,
                            section=section,
                        )
                    )
                if end >= len(body):
                    break
                start = max(end - overlap, start + 1)
    return chunks
