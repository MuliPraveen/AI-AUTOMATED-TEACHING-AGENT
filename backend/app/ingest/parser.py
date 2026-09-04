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


def read_pages(filename: str, data: bytes) -> list[Page]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("PyMuPDF required for PDF ingest") from e
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [Page(i + 1, _clean(p.get_text("text"))) for i, p in enumerate(doc)]
        doc.close()
        return [p for p in pages if p.text]
    text = data.decode("utf-8", errors="ignore")
    # Split plain text into pseudo-pages of ~3000 chars on paragraph bounds.
    parts, buf, n = [], [], 0
    for para in text.split("\n\n"):
        buf.append(para)
        n += len(para)
        if n > 3000:
            parts.append(_clean("\n\n".join(buf)))
            buf, n = [], 0
    if buf:
        parts.append(_clean("\n\n".join(buf)))
    return [Page(i + 1, t) for i, t in enumerate(parts) if t]


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
