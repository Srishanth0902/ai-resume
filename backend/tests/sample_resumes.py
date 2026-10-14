"""Synthetic resumes for demos and tests. All people and contact details are fictional."""
from __future__ import annotations

import io

import pymupdf as fitz
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

# Identifiers that must disappear, and qualifications that must survive.
PII = [
    "Asha Reddy", "asha.reddy@example.com", "+91 90000 00000", "linkedin.com/in/asha-reddy-dev",
    "github.com/ashareddy", "14/08/2002", "Female", "Ravi Kumar Reddy", "Banjara Hills",
]
KEEP = [
    "Python", "SQL", "React", "FastAPI", "Software Intern", "Sales dashboard", "B.Tech in Computer Science",
    "CGPA 8.7", "PostgreSQL", "Docker",
]

HEADER = "ASHA REDDY"
SUBTITLE = "Python Developer"
CONTACT = [
    "Email: asha.reddy@example.com | Phone: +91 90000 00000",
    "linkedin.com/in/asha-reddy-dev | github.com/ashareddy",
    "Address: 12-3-45, Banjara Hills, Hyderabad - 500034",
]
SECTIONS = [
    ("SUMMARY", [
        "Software developer with internship experience building data dashboards using Python, SQL and React.",
    ]),
    ("SKILLS", ["Python, SQL, React, FastAPI, Pandas, Git, Docker, PostgreSQL"]),
    ("EXPERIENCE", [
        "Software Intern, Nimbus Analytics (Jun 2023 - Dec 2023)",
        "- Built a Sales dashboard in React and FastAPI used by 40 analysts.",
        "- Automated weekly reports with Python and PostgreSQL, saving 6 hours per week.",
    ]),
    ("PROJECTS", [
        "Sales dashboard - Interactive analytics dashboard with React, Chart.js and FastAPI.",
        "Resume Parser - NLP pipeline that extracts skills from job descriptions.",
    ]),
    ("EDUCATION", [
        "B.Tech in Computer Science, 2020 - 2024, CGPA 8.7",
        "Jawaharlal Nehru Technological University Hyderabad",
    ]),
]
PERSONAL = [
    ("Date of Birth", "14/08/2002"),
    ("Gender", "Female"),
    ("Marital Status", "Single"),
    ("Nationality", "Indian"),
    ("Father's Name", "Ravi Kumar Reddy"),
]
DECLARATION = "I hereby declare that the above information is true to the best of my knowledge."
SIGNATURE = "Place: Hyderabad"
SIGNED = "Asha Reddy"


def _photo_png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 90, 110), False)
    pix.set_rect(pix.irect, (176, 196, 200))
    pix.set_rect(fitz.IRect(30, 20, 60, 55), (120, 90, 80))   # a very abstract "face"
    pix.set_rect(fitz.IRect(15, 65, 75, 110), (60, 95, 110))
    return pix.tobytes("png")


def make_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 60

    def line(text, size=10.5, bold=False, gap=15, x=50):
        nonlocal y
        page.insert_text((x, y), text, fontsize=size, fontname="hebo" if bold else "helv")
        y += gap

    line(HEADER, size=22, bold=True, gap=22)
    line(SUBTITLE, size=12, gap=20)
    for c in CONTACT:
        line(c)
    email_rect = page.search_for("asha.reddy@example.com")[0]
    page.insert_link({"kind": fitz.LINK_URI, "from": email_rect, "uri": "mailto:asha.reddy@example.com"})
    li_rect = page.search_for("linkedin.com/in/asha-reddy-dev")[0]
    page.insert_link({"kind": fitz.LINK_URI, "from": li_rect, "uri": "https://linkedin.com/in/asha-reddy-dev"})
    page.insert_image(fitz.Rect(470, 40, 545, 132), stream=_photo_png())
    y += 8
    for title, body in SECTIONS:
        line(title, size=12, bold=True, gap=16)
        for b in body:
            line(b)
        y += 8
    line("PERSONAL DETAILS", size=12, bold=True, gap=16)
    for k, v in PERSONAL:
        line(f"{k}: {v}")
    y += 8
    line("DECLARATION", size=12, bold=True, gap=16)
    line(DECLARATION)
    line(SIGNATURE)
    line(SIGNED, x=420)

    doc.set_metadata({"author": "Asha Reddy", "title": "Asha Reddy - Resume"})
    return doc.tobytes()


def _add_hyperlink(paragraph, url: str, text: str) -> None:
    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1F5F5B")
    rpr.append(color)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def make_docx() -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)

    doc.sections[0].header.paragraphs[0].text = "Asha Reddy - Curriculum Vitae"

    doc.add_picture(io.BytesIO(_photo_png()), width=Inches(0.9))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    title = doc.add_paragraph()
    run = title.add_run(HEADER)
    run.bold, run.font.size = True, Pt(22)
    doc.add_paragraph(SUBTITLE)

    # email split over several runs on purpose: redaction must handle run boundaries
    p = doc.add_paragraph("Email: ")
    _add_hyperlink(p, "mailto:asha.reddy@example.com", "asha.reddy@example.com")
    p.add_run(" | Phone: +91 ")
    p.add_run("90000 ").bold = True
    p.add_run("00000")
    p = doc.add_paragraph()
    _add_hyperlink(p, "https://linkedin.com/in/asha-reddy-dev", "linkedin.com/in/asha-reddy-dev")
    p.add_run(" | github.com/ashareddy")
    doc.add_paragraph(CONTACT[2])

    for heading, body in SECTIONS:
        h = doc.add_paragraph()
        r = h.add_run(heading)
        r.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x5F, 0x5B)
        for b in body:
            doc.add_paragraph(b)

    h = doc.add_paragraph()
    h.add_run("PERSONAL DETAILS").bold = True
    table = doc.add_table(rows=0, cols=2)
    for k, v in PERSONAL:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = k, v

    h = doc.add_paragraph()
    h.add_run("DECLARATION").bold = True
    doc.add_paragraph(DECLARATION)
    doc.add_paragraph(SIGNATURE)
    doc.add_paragraph(SIGNED).alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.core_properties.author = "Asha Reddy"
    doc.core_properties.title = "Asha Reddy Resume"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_template_pdf() -> bytes:
    """The fill-in-the-blanks student resume template (tests/template_resume.txt) as a PDF."""
    from pathlib import Path

    lines = (Path(__file__).parent / "template_resume.txt").read_text(encoding="utf-8").splitlines()
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    font = fitz.Font("helv")
    bold = fitz.Font("hebo")
    y = 60
    for i, line in enumerate(lines):
        heading = i == 0 or (line.isupper() and len(line) < 40)
        size = 20 if i == 0 else (11.5 if heading else 10)
        writer = fitz.TextWriter(page.rect)
        # wrap long paragraphs
        words, current = line.split(), ""
        rows = []
        for w in words:
            trial = f"{current} {w}".strip()
            if font.text_length(trial, size) > 495:
                rows.append(current)
                current = w
            else:
                current = trial
        rows.append(current)
        y += 8 if heading and i else 0
        for row in rows:
            writer.append((50, y), row, font=bold if heading else font, fontsize=size)
            y += size + 5
        writer.write_text(page)
    return doc.tobytes()
