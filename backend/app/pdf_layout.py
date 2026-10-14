"""Rebuild readable text from a PDF page using its geometry.

`page.get_text()` returns text in the order it was written into the PDF, which for many
resume templates is not reading order: a name block drawn last, a letterhead footer drawn
first, table cells one per line, bullets and right-aligned dates on their own lines.
This module puts the page back together:

  * tables (via PyMuPDF's table finder) become one line per row: "cell | cell | cell"
  * text on the same visual row is joined left to right; a large gap becomes " | "
  * two-column layouts (a sidebar next to the main column) are read column by column
  * a trailing date cell is attached to its line: "Software Intern (Jun 2025)"
  * bullet glyphs (•, ●, o, , ...) are normalised to "• "
  * lines that wrap inside a paragraph are joined back together
  * headers/footers repeated on every page (letterheads, page numbers) are removed
"""
from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field

import pymupdf as fitz

BULLET_CHARS = "•●○◦▪▫■□►▶➢➤✓✔★☐-–—*·⁃∙"
RE_BULLET_ALONE = re.compile(rf"^[{re.escape(BULLET_CHARS)}o‣]$")
RE_BULLET_PREFIX = re.compile(rf"^(?:[{re.escape(BULLET_CHARS)}‣]|o(?=\s+\S))\s*")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_POINT = rf"(?:{_MONTH}\s*'?\d{{2,4}}|\d{{1,2}}/\d{{2,4}}|(?:19|20)\d{{2}}|[Pp]resent|[Cc]urrent|[Nn]ow|[Oo]ngoing|[Tt]ill\s+[Dd]ate)"
RE_DATE_CELL = re.compile(rf"^\(?{_POINT}(?:\s*(?:[-–—]|to)\s*{_POINT})?\)?$")


@dataclass
class Item:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float = 10.0
    table: bool = False

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1.0)


@dataclass
class Row:
    items: list[Item]
    text: str = ""
    table: bool = False
    bullet: bool = False
    text_x0: float = 0.0
    x0: float = 0.0
    x1: float = 0.0
    y0: float = 0.0
    y1: float = 0.0
    size: float = 10.0
    furniture_key: str = field(default="", repr=False)


# --------------------------------------------------------------------------- items


def _span_items(page) -> list[Item]:
    items = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            if line.get("dir", (1, 0))[1] not in (0, 0.0):
                continue  # rotated text (watermarks, vertical labels)
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            # split a line where spans are far apart (e.g. title ...... right-aligned date)
            group = [spans[0]]
            for s in spans[1:]:
                prev = group[-1]
                if s["bbox"][0] - prev["bbox"][2] > 2.5 * max(prev["size"], 6):
                    items.append(_item_from_spans(group))
                    group = [s]
                else:
                    group.append(s)
            items.append(_item_from_spans(group))
    return items


def _item_from_spans(spans) -> Item:
    parts = []
    for i, s in enumerate(spans):
        text = s["text"]
        if i and s["bbox"][0] - spans[i - 1]["bbox"][2] > 0.15 * s["size"] and not parts[-1].endswith(" ") \
                and not text.startswith(" "):
            parts.append(" ")
        parts.append(text)
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)
    size = max(s["size"] for s in spans)
    # a run of spaces inside one span is a visual gap ("Department:          May 2026 – Present")
    text = re.sub(r"\s{4,}", " | ", "".join(parts).strip())
    return Item(x0, y0, x1, y1, " ".join(text.split()), size)


def _table_items(page) -> tuple[list[Item], list[fitz.Rect]]:
    items, boxes = [], []
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # PyMuPDF prints an advert for an add-on here
            tables = page.find_tables().tables
    except Exception:
        return items, boxes
    for t in tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue  # a decorative rule mistaken for a table
        boxes.append(fitz.Rect(t.bbox))
        for r_idx, cells in enumerate(rows):
            texts = [" ".join((c or "").split()) for c in cells]
            texts = [c for c in texts if c]
            if not texts:
                continue
            try:
                rb = t.rows[r_idx].bbox
            except Exception:
                rb = (t.bbox[0], t.bbox[1] + r_idx, t.bbox[2], t.bbox[1] + r_idx + 1)
            items.append(Item(rb[0], rb[1], rb[2], rb[3], " | ".join(texts), table=True))
    return items, boxes


# --------------------------------------------------------------------------- ordering


def _group_rows(items: list[Item]) -> list[Row]:
    rows: list[Row] = []
    for it in sorted(items, key=lambda i: (i.yc, i.x0)):
        if it.table:
            rows.append(Row([it]))
            continue
        target = None
        for row in reversed(rows[-3:]):
            if row.items[0].table:
                continue
            ref = row.items
            top = min(i.y0 for i in ref)
            bottom = max(i.y1 for i in ref)
            overlap = min(bottom, it.y1) - max(top, it.y0)
            if overlap >= 0.5 * min(it.h, bottom - top):
                target = row
                break
        if target:
            target.items.append(it)
        else:
            rows.append(Row([it]))
    for row in rows:
        row.items.sort(key=lambda i: i.x0)
        _finish_row(row)
    rows.sort(key=lambda r: (r.y0, r.x0))
    return rows


def _finish_row(row: Row) -> None:
    items = row.items
    row.table = items[0].table
    row.x0, row.x1 = min(i.x0 for i in items), max(i.x1 for i in items)
    row.y0, row.y1 = min(i.y0 for i in items), max(i.y1 for i in items)
    row.size = max(i.size for i in items)
    if row.table:
        row.text, row.text_x0 = items[0].text, row.x0
        return

    cells = [i.text for i in items]
    row.text_x0 = items[0].x0
    if RE_BULLET_ALONE.match(cells[0]) and len(items) > 1:
        row.bullet, row.text_x0 = True, items[1].x0
        cells = cells[1:]
        items = items[1:]
    elif RE_BULLET_PREFIX.match(cells[0]) and len(cells[0]) > 2:
        row.bullet = True
        cells[0] = RE_BULLET_PREFIX.sub("", cells[0], count=1)
        row.text_x0 = items[0].x0 + 0.6 * items[0].size + 3

    # join cells: close together -> space, far apart -> " | "
    out = cells[0]
    for prev, it, cell in zip(items, items[1:], cells[1:]):
        gap = it.x0 - prev.x1
        out += (" | " if gap > 2.5 * max(it.size, 6) else " ") + cell
    if " | " in out:                                  # "... Ltd.: | Jun 2025" -> "... Ltd. (Jun 2025)"
        head, _, tail = out.rpartition(" | ")
        if RE_DATE_CELL.match(tail.strip()) and head.strip():
            out = f"{head.rstrip(' :|')} ({tail.strip().strip('()')})"
    out = re.sub(r"\s*\|\s*:\s*", ": ", out)          # "Languages | : Python" -> "Languages: Python"
    out = re.sub(r":\s*\|\s*", ": ", out)             # "Skills: | Python"     -> "Skills: Python"
    out = re.sub(r"\s+:\s+", ": ", out)               # "Languages : Python"   -> "Languages: Python"
    if not row.bullet and len(items) > 1 and RE_DATE_CELL.match(cells[-1]):
        head = " ".join(cells[:-1]).rstrip(" :")
        if head and "|" not in head:
            out = f"{head} ({cells[-1].strip('()')})"
    row.text = ("• " if row.bullet else "") + " ".join(out.split())


def _gutter(items: list[Item], width: float):
    """x position of a vertical gap that splits the page into two columns, or None."""
    text_items = [i for i in items if not i.table]
    if len(text_items) < 10:
        return None
    best = None
    for x in range(int(width * 0.22), int(width * 0.78), 3):
        crossing = sum(1 for i in text_items if i.x0 < x - 1 and i.x1 > x + 1)
        left = [i for i in text_items if i.x1 <= x]
        right = [i for i in text_items if i.x0 >= x]
        if len(left) < 4 or len(right) < 4:
            continue
        if best is None or crossing < best[0]:
            best = (crossing, x, left, right)
    if best is None:
        return None
    crossing, x, left, right = best
    if crossing > 0.06 * len(text_items):
        return None

    def span(group):
        return max(i.y1 for i in group) - min(i.y0 for i in group)

    total = span(text_items)
    # both columns must run down a good part of the page (not just a row of contact details)
    if span(left) < 0.35 * total or span(right) < 0.35 * total:
        return None
    return x


def _ordered_rows(items: list[Item], width: float) -> list[Row]:
    gutter = _gutter(items, width)
    if gutter is None:
        return _group_rows(items)
    # Read band by band: full-width items (a name banner, a heading across both columns)
    # separate bands; inside a band read the left column, then the right one.
    rows: list[Row] = []
    left: list[Item] = []
    right: list[Item] = []

    def flush():
        rows.extend(_group_rows(left))
        rows.extend(_group_rows(right))
        left.clear()
        right.clear()

    for it in sorted(items, key=lambda i: i.y0):
        if it.x0 < gutter - 1 and it.x1 > gutter + 1:
            flush()
            rows.extend(_group_rows([it]))
        elif it.x1 <= gutter + 1:
            left.append(it)
        else:
            right.append(it)
    flush()
    return rows


# --------------------------------------------------------------------------- paragraphs


def _join_wrapped(rows: list[Row], width: float) -> list[Row]:
    """Merge a row into the previous one when it is the wrapped tail of the same paragraph."""
    if not rows:
        return rows
    text_rows = [r for r in rows if not r.table]

    def column_bounds(row: Row) -> tuple[float, float]:
        # the column this row sits in (sidebars, name blocks and main columns differ)
        same = [r for r in text_rows if row.x0 - 30 <= r.x0 <= row.x0 + 60]
        return min(r.x0 for r in same), max(r.x1 for r in same)

    def wrapped(prev: Row, row: Row) -> bool:
        if re.match(r"^[A-Za-z][\w .'/&-]{0,25}\s*:", row.text):
            return False  # "Gender: Female", "E-mail : ..." are separate detail lines
        left, right = column_bounds(prev)
        if right - left < 0.4 * width:
            return False  # narrow blocks (name block, sidebar) hold lists, not paragraphs
        # the line wrapped if the next line's first word would not have fitted after it
        first_word = row.text.split(" ", 1)[0]
        needed = (len(first_word) + 1) * 0.45 * row.size
        return prev.x1 + needed >= right - 2

    out: list[Row] = []
    for row in rows:
        prev = out[-1] if out else None
        if (
            prev is not None
            and not row.table and not prev.table and not row.bullet
            and abs(row.size - prev.size) <= 0.6
            and -0.5 * row.size <= row.y0 - prev.y1 <= 1.2 * row.size
            and wrapped(prev, row)                                     # previous line ran to the margin
            and prev.x0 - 2 <= row.x0 <= prev.text_x0 + 1.5 * row.size  # continues at the text indent
            and not re.search(r"\([^)]*\)$|\|", prev.text)            # not a title row with a date
        ):
            prev.text = f"{prev.text} {row.text}"
            prev.x1 = row.x1  # the merged paragraph now ends where its last line ends
            prev.y1 = row.y1
            continue
        out.append(row)
    return out


# --------------------------------------------------------------------------- document


def _furniture_key(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


RE_PAGE_NUMBER = re.compile(r"^(?:page\s*)?#(?:\s*(?:of|/)\s*#)?$")


def document_lines(doc) -> list[str]:
    """Reading-order lines for the whole document, page breaks as blank lines."""
    pages: list[tuple[fitz.Rect, list[Row]]] = []
    for page in doc:
        table_items, boxes = _table_items(page)
        text_items = [
            it for it in _span_items(page)
            if not any(fitz.Rect(it.x0, it.y0, it.x1, it.y1).intersects(b) for b in boxes)
        ]
        rows = _ordered_rows(text_items + table_items, page.rect.width)
        pages.append((page.rect, rows))

    # Header/footer furniture: rows in the top or bottom 12% that repeat on several pages.
    counts: dict[str, int] = {}
    for rect, rows in pages:
        for r in rows:
            if r.y1 < rect.height * 0.12 or r.y0 > rect.height * 0.88:
                r.furniture_key = _furniture_key(r.text)
                counts[r.furniture_key] = counts.get(r.furniture_key, 0) + 1
    repeated = {k for k, n in counts.items() if n >= 2 and len(pages) >= 2}

    lines: list[str] = []
    for rect, rows in pages:
        kept = [
            r for r in rows
            if not (r.furniture_key and (r.furniture_key in repeated or RE_PAGE_NUMBER.match(r.furniture_key)))
        ]
        kept = _join_wrapped(kept, rect.width)
        # nested bullets (indented further than the outermost bullets) become "◦ " sub-points
        bullet_x = [r.x0 for r in kept if r.bullet]
        if bullet_x:
            outer = min(bullet_x)
            for r in kept:
                if r.bullet and r.x0 > outer + 8 and r.text.startswith("• "):
                    r.text = "◦ " + r.text[2:]
        if lines:
            lines.append("")
        lines.extend(r.text for r in kept if r.text.strip())
    return lines
