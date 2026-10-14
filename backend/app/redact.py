"""Produce an anonymised copy of a resume in its original format.

PDF  -> PyMuPDF redaction annotations, applied so the underlying text is really removed
DOCX -> text replaced inside the XML runs, keeping the original formatting

Besides visible text, both paths also clean places where identity leaks quietly:
hyperlink targets (mailto:, linkedin.com/in/...), document metadata (author, title)
and embedded photos.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from urllib.parse import unquote

import pymupdf as fitz
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn

from .detect import CATEGORIES, build_matcher, normalize_term
from .extract import MC_FALLBACK, _is_photo_sized, paragraph_text_nodes, picture_elements

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass
class RedactItem:
    text: str
    category: str


@dataclass
class RedactStats:
    redactions: int = 0
    photos_removed: int = 0
    links_removed: int = 0
    metadata_cleared: bool = False


class Placeholder:
    def __init__(self, items: list[RedactItem], label_style: str):
        self.style = label_style
        self.by_term = {normalize_term(i.text): i.category for i in items}

    def for_category(self, category: str) -> str:
        if self.style == "category":
            return f"[{CATEGORIES.get(category, {}).get('tag', 'REMOVED')}]"
        return "[REMOVED]"

    def for_match(self, matched: str) -> str:
        return self.for_category(self.by_term.get(normalize_term(matched), ""))


def split_terms(items: list[RedactItem]) -> list[RedactItem]:
    """Text taken from table rows or wrapped lines can't match inside one paragraph/line."""
    out = []
    for item in items:
        for part in re.split(r"\n|\s\|\s", item.text):
            if part.strip():
                out.append(RedactItem(" ".join(part.split()), item.category))
    return out


def redact_text(text: str, items: list[RedactItem], label_style: str = "removed") -> str:
    items = split_terms(items)
    matcher = build_matcher([i.text for i in items])
    if matcher is None:
        return text
    labels = Placeholder(items, label_style)
    return matcher.sub(lambda m: labels.for_match(m.group(0)), text)


def redact_document(data: bytes, kind: str, items: list[RedactItem], label_style: str, remove_photos: bool):
    items = split_terms(items)
    if kind == "pdf":
        return _redact_pdf(data, items, label_style, remove_photos)
    return _redact_docx(data, items, label_style, remove_photos)


# --------------------------------------------------------------------------- PDF

_STRIP = ".,;:()[]{}\"'‘’“”|•"


def _norm_word(word: str) -> str:
    return word.strip(_STRIP).lower()


def _distinctive(term: str) -> bool:
    """Safe to substring-search (emails, phones, links), unlike short words such as 'her'."""
    return len(term) >= 6 and any(not ch.isalpha() and not ch.isspace() for ch in term)


def _overlaps(rect: fitz.Rect, existing: list[fitz.Rect]) -> bool:
    for r in existing:
        inter = fitz.Rect(rect) & r
        if not inter.is_empty and inter.get_area() > 0.4 * min(rect.get_area(), r.get_area()):
            return True
    return False


def _add_redaction(page, rect: fitz.Rect, label: str | None) -> None:
    kwargs = dict(fill=(0.88, 0.9, 0.9), cross_out=False)
    if label:
        width_at_1pt = fitz.get_text_length(label, fontname="helv", fontsize=1)
        size = min(rect.height * 0.78, (rect.width - 1) / width_at_1pt, 10)
        if size >= 4:
            kwargs.update(text=label, fontname="helv", fontsize=size, text_color=(0.2, 0.25, 0.27),
                          align=fitz.TEXT_ALIGN_CENTER)
    page.add_redact_annot(rect, **kwargs)


def _apply(page, remove_images: bool) -> None:
    kwargs = {"images": fitz.PDF_REDACT_IMAGE_REMOVE if remove_images else fitz.PDF_REDACT_IMAGE_NONE}
    if hasattr(fitz, "PDF_REDACT_LINE_ART_NONE"):
        kwargs["graphics"] = fitz.PDF_REDACT_LINE_ART_NONE
    page.apply_redactions(**kwargs)


def _redact_pdf(data: bytes, items: list[RedactItem], label_style: str, remove_photos: bool):
    doc = fitz.open(stream=data, filetype="pdf")
    labels = Placeholder(items, label_style)
    matcher = build_matcher([i.text for i in items])
    stats = RedactStats()
    terms = sorted(items, key=lambda i: len(i.text), reverse=True)

    for page in doc:
        words = page.get_text("words")
        norm = [_norm_word(w[4]) for w in words]
        placed: list[fitz.Rect] = []

        for item in terms:
            label = labels.for_category(item.category)
            tokens = [_norm_word(t) for t in item.text.split()]
            tokens = [t for t in tokens if t]
            n = len(tokens)
            # 1) whole-word sequence match (works for names, pronouns, multi-line hits)
            if n:
                for i in range(len(words) - n + 1):
                    if norm[i:i + n] != tokens:
                        continue
                    lines: dict[tuple, fitz.Rect] = {}
                    for w in words[i:i + n]:
                        key = (w[5], w[6])
                        lines[key] = lines[key] | fitz.Rect(w[:4]) if key in lines else fitz.Rect(w[:4])
                    rects = list(lines.values())
                    if _overlaps(rects[0], placed):
                        continue
                    for j, r in enumerate(rects):
                        _add_redaction(page, r, label if j == 0 else None)
                        placed.append(r)
                    stats.redactions += 1
            # 2) substring search for distinctive values glued to other text ("Email:asha@x.com")
            if _distinctive(item.text):
                for r in page.search_for(item.text):
                    if not _overlaps(r, placed):
                        _add_redaction(page, r, label)
                        placed.append(r)
                        stats.redactions += 1

        # links whose target holds a redacted value, or that sit on a redacted area
        for link in page.get_links():
            uri = unquote(link.get("uri") or "")
            hit_text = bool(uri) and matcher is not None and matcher.search(uri)
            hit_area = any(not (fitz.Rect(link["from"]) & r).is_empty for r in placed)
            if hit_text or hit_area:
                page.delete_link(link)
                stats.links_removed += 1

        _apply(page, remove_images=False)

        if remove_photos:
            photo_rects = [fitz.Rect(i["bbox"]) for i in page.get_image_info()
                           if _is_photo_sized(i["bbox"], page.rect)]
            for r in photo_rects:
                _add_redaction(page, r, "[PHOTO REMOVED]")
            if photo_rects:
                _apply(page, remove_images=True)
                stats.photos_removed += len(photo_rects)

    doc.set_metadata({})
    doc.del_xml_metadata()
    stats.metadata_cleared = True
    out = doc.tobytes(garbage=4, deflate=True, clean=True)
    doc.close()
    return out, stats


# --------------------------------------------------------------------------- DOCX


def _redact_paragraph(p, matcher: re.Pattern, labels: Placeholder) -> int:
    nodes = paragraph_text_nodes(p)
    if not nodes:
        return 0
    texts = [n.text or "" for n in nodes]
    starts, pos = [], 0
    for t in texts:
        starts.append(pos)
        pos += len(t)
    matches = list(matcher.finditer("".join(texts)))
    # right-to-left so earlier offsets stay valid while text is rewritten
    for m in reversed(matches):
        s, e = m.span()
        label, first = labels.for_match(m.group(0)), True
        for idx in range(len(nodes)):
            ns, ne = starts[idx], starts[idx] + len(nodes[idx].text or "")
            if ne <= s or ns >= e:
                continue
            a, b = max(s, ns) - ns, min(e, ne) - ns
            texts[idx] = texts[idx][:a] + (label if first else "") + texts[idx][b:]
            first = False
    for node, text in zip(nodes, texts):
        if node.text != text:
            node.text = text
            node.set(XML_SPACE, "preserve")
    return len(matches)


def _remove_pictures(part, root) -> int:
    removed = 0
    rids: set[str] = set()
    for el in picture_elements(root):
        for blip in el.iter(qn("a:blip")):
            rids.update(v for k, v in blip.attrib.items() if k.startswith(f"{{{R_NS}}}"))
        for img in el.iter("{urn:schemas-microsoft-com:vml}imagedata"):
            rids.update(v for k, v in img.attrib.items() if k.startswith(f"{{{R_NS}}}"))
        if not any(a.tag == MC_FALLBACK for a in el.iterancestors()):
            removed += 1
        el.getparent().remove(el)
    # drop the relationship so the image bytes are not kept inside the .docx package
    xml = None
    for rid in rids:
        if xml is None:
            from lxml import etree
            xml = etree.tostring(root).decode()
        if f'"{rid}"' not in xml and rid in part.rels:
            try:
                part.drop_rel(rid)
            except Exception:
                del part.rels._rels[rid]
    return removed


def _redact_docx(data: bytes, items: list[RedactItem], label_style: str, remove_photos: bool):
    doc = Document(io.BytesIO(data))
    labels = Placeholder(items, label_style)
    matcher = build_matcher([i.text for i in items])
    stats = RedactStats()
    phone_selected = any(i.category == "phone" for i in items)
    email_selected = any(i.category == "email" for i in items)

    for part in list(doc.part.package.iter_parts()):
        root = getattr(part, "_element", None)
        if root is None:
            continue
        if matcher is not None:
            for p in list(root.iter(qn("w:p"))):
                stats.redactions += _redact_paragraph(p, matcher, labels)
            for instr in root.iter(qn("w:instrText")):  # HYPERLINK "mailto:..." field codes
                if instr.text and matcher.search(instr.text):
                    instr.text = matcher.sub("", instr.text)
        if remove_photos and root.tag in (qn("w:document"), qn("w:hdr"), qn("w:ftr")):
            stats.photos_removed += _remove_pictures(part, root)

        for rel in list(part.rels.values()):
            if rel.reltype != RT.HYPERLINK or not rel.is_external:
                continue
            target = unquote(rel.target_ref)
            low = target.lower()
            if (
                (matcher is not None and matcher.search(target))
                or (phone_selected and low.startswith("tel:"))
                or (email_selected and low.startswith("mailto:"))
            ):
                rel._target = "#"
                stats.links_removed += 1

    cp = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "keywords", "comments", "category"):
        setattr(cp, attr, "")
    stats.metadata_cleared = True

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), stats
