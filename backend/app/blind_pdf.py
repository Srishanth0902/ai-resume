"""Render a blind profile as a PDF that can be shared with an interview panel."""
from __future__ import annotations

import io
import re
from html import escape

import pymupdf as fitz

CSS = """
* { font-family: sans-serif; }
body { font-size: 10.5pt; color: #17343a; }
h1 { font-size: 18pt; margin: 0 0 2pt 0; color: #1f5f5b; }
.code { font-size: 9pt; color: #c0673e; font-weight: bold; letter-spacing: 1pt; }
.headline { font-size: 11.5pt; color: #4f6468; margin: 2pt 0 10pt 0; }
h2 { font-size: 11pt; color: #1f5f5b; border-bottom: 1px solid #dde5e4; padding-bottom: 2pt; margin: 12pt 0 4pt 0; }
p { margin: 0 0 3pt 0; line-height: 1.35; }
p.entry { font-weight: bold; margin-top: 6pt; }
p.sub { margin-left: 14pt; }
table { border-collapse: collapse; margin: 2pt 0 6pt 0; }
th, td { border-bottom: 1px solid #dde5e4; padding: 2pt 6pt; text-align: left; font-size: 9.5pt; }
th { color: #7b8b8e; }
.note { font-size: 8.5pt; color: #7b8b8e; margin-top: 16pt; }
"""
ENTRY_TITLE = re.compile(r"(\([^()]*(\d{4}|present|current)[^()]*\)|:)$", re.I)


def _section_html(lines: list[str]) -> list[str]:
    out: list[str] = []
    nested = any(l.startswith("◦") for l in lines)
    table: list[list[str]] = []

    def flush_table():
        if table:
            header = not any(ch.isdigit() for ch in " ".join(table[0])) and len(table) > 1
            rows = []
            for i, cells in enumerate(table):
                tag = "th" if header and i == 0 else "td"
                rows.append("<tr>" + "".join(f"<{tag}>{escape(c)}</{tag}>" for c in cells) + "</tr>")
            out.append("<table>" + "".join(rows) + "</table>")
            table.clear()

    for idx, line in enumerate(lines):
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        heads = (not re.match(r"^[-•*●▪–◦]", line) and len(line) < 160 and bool(re.match(r"^[-•*●▪–◦]", nxt)))
        if heads and line.count(" | ") < 2:
            flush_table()
            out.append(f'<p class="entry">{escape(line)}</p>')
            continue
        if line.count(" | ") >= 2:
            table.append(line.split(" | "))
            continue
        flush_table()
        if line.startswith("◦"):
            out.append(f'<p class="sub">&bull; {escape(line[1:].strip())}</p>')
        elif re.match(r"^[-•*●▪–]\s*", line):
            text = re.sub(r"^[-•*●▪–]\s*", "", line)
            if nested or ENTRY_TITLE.search(text):
                out.append(f'<p class="entry">{escape(text)}</p>')
            else:
                out.append(f"<p>&bull; {escape(text)}</p>")
        elif ENTRY_TITLE.search(line) and len(line) < 140:
            out.append(f'<p class="entry">{escape(line)}</p>')
        else:
            out.append(f"<p>{escape(line)}</p>")
    flush_table()
    return out


def render(code: str, profile: dict) -> bytes:
    parts = [f'<p class="code">{escape(code)} &middot; BLIND PROFILE</p>', "<h1>Candidate profile</h1>"]
    if profile.get("headline"):
        parts.append(f'<p class="headline">{escape(profile["headline"])}</p>')
    for section in profile.get("sections", []):
        parts.append(f"<h2>{escape(section['title'])}</h2>")
        if section.get("key") == "skills" and profile.get("skills"):
            parts.append(f"<p>{escape(', '.join(profile['skills']))}</p>")
        else:
            parts += _section_html(section["lines"])
    hidden = profile.get("hidden", {})
    parts.append(
        '<p class="note">Personal details (name, contact, photo, age and gender indicators'
        + (", college names" if hidden.get("institutions") else "")
        + ") were removed for unbiased screening.</p>"
    )

    story = fitz.Story(html="<body>" + "".join(parts) + "</body>", user_css=CSS)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (54, 54, -54, -54)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buf.getvalue()
