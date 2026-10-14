"""Render a blind profile as a PDF that can be shared with an interview panel."""
from __future__ import annotations

import io
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
.note { font-size: 8.5pt; color: #7b8b8e; margin-top: 16pt; }
"""


def render(code: str, profile: dict) -> bytes:
    parts = [f'<p class="code">{escape(code)} &middot; BLIND PROFILE</p>', "<h1>Candidate profile</h1>"]
    if profile.get("headline"):
        parts.append(f'<p class="headline">{escape(profile["headline"])}</p>')
    for section in profile.get("sections", []):
        parts.append(f"<h2>{escape(section['title'])}</h2>")
        parts += [f"<p>{escape(line)}</p>" for line in section["lines"]]
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
