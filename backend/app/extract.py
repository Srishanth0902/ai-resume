"""Read resume text from PDF (PyMuPDF) and DOCX (python-docx). Everything stays in memory."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pymupdf as fitz
from docx import Document
from docx.oxml.ns import qn

MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


class UnsupportedFile(ValueError):
    pass


@dataclass
class Extraction:
    text: str
    kind: str
    page_count: int = 1
    image_count: int = 0
    warnings: list[str] = field(default_factory=list)


def detect_kind(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if data[:5] == b"%PDF-" or name.endswith(".pdf"):
        if data[:5] != b"%PDF-":
            raise UnsupportedFile("The file has a .pdf extension but is not a valid PDF.")
        return "pdf"
    if name.endswith(".docx") or data[:2] == b"PK":
        if data[:2] != b"PK":
            raise UnsupportedFile("The file has a .docx extension but is not a valid Word document.")
        return "docx"
    if name.endswith(".doc"):
        raise UnsupportedFile("Legacy .doc files are not supported. Save the resume as .docx or PDF.")
    raise UnsupportedFile("Unsupported file type. Upload a PDF or DOCX resume.")


def extract(data: bytes, kind: str) -> Extraction:
    if kind == "pdf":
        return _extract_pdf(data)
    if kind == "docx":
        return _extract_docx(data)
    raise UnsupportedFile(kind)


# --------------------------------------------------------------------------- PDF


def _extract_pdf(data: bytes) -> Extraction:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UnsupportedFile(f"Could not open the PDF: {exc}") from exc
    if doc.needs_pass:
        raise UnsupportedFile("The PDF is password protected. Remove the password and try again.")

    pages, images = [], 0
    for page in doc:
        pages.append(page.get_text("text").strip())
        images += sum(1 for info in page.get_image_info() if _is_photo_sized(info["bbox"], page.rect))
    text = "\n\n".join(p for p in pages if p)

    result = Extraction(text=text, kind="pdf", page_count=doc.page_count, image_count=images)
    if not text.strip():
        result.warnings.append(
            "No selectable text was found. This looks like a scanned PDF, which needs OCR before "
            "personal details can be detected. Only photo removal can be applied."
        )
    elif len(text) < 150 * doc.page_count:
        result.warnings.append("Very little text was extracted; parts of this PDF may be images.")
    if images:
        result.warnings.append(f"{images} image(s) found that may be a photo of the candidate.")
    doc.close()
    return result


def _is_photo_sized(bbox, page_rect) -> bool:
    r = fitz.Rect(bbox)
    # ignore tiny icons and full-page backgrounds
    return r.width >= 30 and r.height >= 30 and r.get_area() < 0.5 * page_rect.get_area()


# --------------------------------------------------------------------------- DOCX


def _extract_docx(data: bytes) -> Extraction:
    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise UnsupportedFile(f"Could not open the Word document: {exc}") from exc

    lines: list[str] = []
    for section in doc.sections:
        if not section.header.is_linked_to_previous:
            lines += docx_lines(section.header._element)
    lines += docx_lines(doc.element.body)
    for section in doc.sections:
        if not section.footer.is_linked_to_previous:
            lines += docx_lines(section.footer._element)

    images = count_docx_pictures(doc.element.body)
    text = "\n".join(line for line in lines if line.strip())
    result = Extraction(text=text, kind="docx", image_count=images)
    if not text.strip():
        result.warnings.append("No text was found in this document.")
    if images:
        result.warnings.append(f"{images} picture(s) found that may be a photo of the candidate.")
    return result


def _owner_paragraph(node):
    return next(node.iterancestors(qn("w:p")), None)


def paragraph_text_nodes(p) -> list:
    """w:t nodes that belong to this paragraph (not to a text box nested inside it)."""
    return [t for t in p.iter(qn("w:t")) if _owner_paragraph(t) is p]


def docx_lines(root) -> list[str]:
    """Paragraph text in document order; table rows are joined with ' | '."""
    lines: list[str] = []
    current_row, row_cells = None, {}
    for p in root.iter(qn("w:p")):
        if any(a.tag == MC_FALLBACK for a in p.iterancestors()):
            continue  # duplicate copy of a text box kept for old Word versions
        text = "".join(t.text or "" for t in paragraph_text_nodes(p))
        row = next(p.iterancestors(qn("w:tr")), None)
        if row is not current_row and current_row is not None:
            lines.append(" | ".join(c.strip() for c in row_cells.values() if c.strip()))
            row_cells = {}
        current_row = row
        if row is None:
            lines.append(text)
        else:
            cell = next(p.iterancestors(qn("w:tc")))
            row_cells[id(cell)] = (row_cells.get(id(cell), "") + " " + text).strip()
    if current_row is not None:
        lines.append(" | ".join(c.strip() for c in row_cells.values() if c.strip()))
    return lines


def picture_elements(root) -> list:
    """Drawings/VML pictures that hold an image and are not text boxes."""
    found = []
    for el in list(root.iter(qn("w:drawing"))) + list(root.iter(qn("w:pict"))):
        has_image = any(True for _ in el.iter(qn("a:blip"))) or any(
            True for _ in el.iter("{urn:schemas-microsoft-com:vml}imagedata")
        )
        has_textbox = any(True for _ in el.iter(qn("w:txbxContent")))
        if has_image and not has_textbox:
            found.append(el)
    return found


def count_docx_pictures(root) -> int:
    return sum(
        1 for el in picture_elements(root) if not any(a.tag == MC_FALLBACK for a in el.iterancestors())
    )
