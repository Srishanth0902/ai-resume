"""Synthetic resumes with the tricky layouts real resumes use. All people and details are fictional."""
from __future__ import annotations

import pymupdf as fitz

from .sample_resumes import _photo_png


class _Writer:
    """Tiny PDF layout helper: wraps text, draws bullets and right-aligned dates like Word does."""

    def __init__(self, page, y, right=545):
        self.page, self.y, self.right = page, y, right

    def text(self, x, y, s, size=10.5, bold=False, font=None, color=(0, 0, 0)):
        self.page.insert_text((x, y), s, fontsize=size, fontname=font or ("hebo" if bold else "helv"), color=color)

    def heading(self, s):
        self.y += 10
        self.text(40, self.y, s, size=13, bold=True)
        start = 40 + fitz.get_text_length(s, "hebo", 13) + 8
        self.page.draw_line((start, self.y - 4), (self.right, self.y - 4), color=(0.75, 0.1, 0.1), width=1.2)
        self.y += 18

    def para(self, x, s, size=10.5, bullet=None, bullet_x=None, date=None, bold=False):
        if bullet:
            self.text(bullet_x, self.y, bullet, size=size, font="cour" if bullet == "o" else None)
        if date:  # right-aligned, its own text run, like a tab stop in Word
            self.text(self.right - fitz.get_text_length(date, "helv", size), self.y, date, size=size)
        width = (self.right - 70 if date else self.right) - x
        font = "hebo" if bold else "helv"
        line = ""
        for word in s.split():
            trial = f"{line} {word}".strip()
            if fitz.get_text_length(trial, font, size) > width:
                self.text(x, self.y, line, size=size, bold=bold)
                self.y += size + 4
                line = word
            else:
                line = trial
        self.text(x, self.y, line, size=size, bold=bold)
        self.y += size + 5


def make_placement_pdf() -> bytes:
    """College placement-cell template: letterhead footer on every page, logo + photo around a name
    block that is written LAST into the PDF, a bordered education table, "•"/"o" bullets as separate
    glyphs, right-aligned dates and labelled skill rows split into two columns."""
    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=595, height=842)
    pages = [doc[0], doc[1]]  # fetch after creating: adding a page invalidates earlier page objects
    for p in pages:  # the letterhead footer comes first in the content stream, like the real template
        p.insert_text((150, 800), "Department of Training and Placement, Example Institute of Technology 600001",
                      fontsize=8, fontname="helv")
        p.insert_text((170, 811), "Telephone : +91-44-2000000    e-mail: placements@example.edu", fontsize=8,
                      fontname="helv")
    p1 = pages[0]
    p1.insert_image(fitz.Rect(30, 60, 110, 140), stream=_photo_png())   # institute logo
    p1.insert_image(fitz.Rect(470, 60, 545, 150), stream=_photo_png())  # candidate photo
    p1.draw_line((30, 165), (565, 165), color=(0, 0, 0), width=0.8)

    w = _Writer(p1, 195)
    w.heading("Educational Qualification")
    cols = [40, 120, 245, 455, 545]
    rows = [("Year", "Degree/Examination", ["Institution/Board"], "CGPA/Percentage"),
            ("2022-Present", "B.Tech - Mechanical", ["Example Institute of Technology"], "9.10"),
            ("2021", "Class XII", ["Lotus Junior College,", "Madurai, CBSE"], "95.20%"),
            ("2019", "Class X", ["Green Valley High School,", "Madurai, CBSE"], "93.00%")]
    y = w.y
    for year, degree, inst, score in rows:
        h = 14 * len(inst) + 6
        p1.draw_rect(fitz.Rect(cols[0], y, cols[-1], y + h), color=(0, 0, 0), width=0.6)
        for c in cols[1:-1]:
            p1.draw_line((c, y), (c, y + h), color=(0, 0, 0), width=0.6)
        mid = y + h / 2 + 3.5
        for x0, cell in ((cols[0], year), (cols[1], degree), (cols[3], score)):
            p1.insert_text((x0 + 6, mid), cell, fontsize=9.5, fontname="helv")
        for i, part in enumerate(inst):
            p1.insert_text((cols[2] + 6, y + 14 + 14 * i), part, fontsize=9.5, fontname="helv")
        y += h
    w.y = y + 18

    w.heading("Academic Achievements")
    w.para(70, "Ranked in the top 2% of 40,000 participants in the National Design Challenge 2024, a competition "
               "recognizing innovative engineering solutions from engineering colleges across the country.",
           bullet="•", bullet_x=55)
    w.heading("Internship Experience")
    w.para(70, "Manufacturing Analytics Internship | Orbit Motors Ltd.:", bullet="•", bullet_x=55, date="May 2025",
           bold=True)
    w.para(95, "Built a Python model that predicts machine downtime from sensor logs, cutting unplanned stoppages "
               "by 12% across the assembly line within the first month.", bullet="o", bullet_x=80)
    w.para(95, "Automated a weekly quality report with SQL and Power BI.", bullet="o", bullet_x=80)
    w.heading("Other Projects")
    w.para(70, "Solar Dryer Thermal Simulation:", bullet="•", bullet_x=55, date="Jan 2026", bold=True)
    w.para(95, "Modelled heat transfer in a solar crop dryer with Python and validated it against field "
               "measurements, improving the drying time by 18% for small farms.", bullet="o", bullet_x=80)

    w = _Writer(pages[1], 70)
    w.heading("Technical Skills and Certifications")
    for label, value in (("Programming Languages", ": Python, C++"), ("Engineering Software", ": SolidWorks, ANSYS"),
                         ("Certifications", ": Six Sigma Green Belt")):
        w.text(55, w.y, "●")
        w.text(70, w.y, label)
        w.text(220, w.y, value)
        w.y += 17
    w.heading("Positions of Responsibility")
    w.para(70, "Head, Robotics Club:", bullet="•", bullet_x=55, date="Aug 2024 - Present", bold=True)
    w.para(95, "Led a team of 30 members to design and build two competition robots.", bullet="o", bullet_x=80)
    w.heading("Extracurricular Activities")
    w.text(55, w.y, "Sport Activities:", bold=True)
    w.y += 16
    w.para(70, "Won the inter-department chess tournament.", bullet="•", bullet_x=55)

    # the name block is drawn last, so plain text extraction would put it at the very end
    block = [("KAVYA MENON", 16, True), ("B.Tech - Mechanical Engineering", 10.5, False),
             ("Gender: Female", 10.5, False), ("Date of Birth: 14/03/2004", 10.5, False),
             ("E-mail : kavya.menon@example.com", 10.5, False), ("Contact : +91 98765 43210", 10.5, False)]
    for i, (s, size, bold) in enumerate(block):
        p1.insert_text((150, 78 if i == 0 else 86 + 14 * i), s, fontsize=size, fontname="hebo" if bold else "helv")
    return doc.tobytes()


def make_two_column_pdf() -> bytes:
    """Sidebar resume: contact, skills and languages on the left, the main story on the right."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 95), color=None, fill=(0.12, 0.2, 0.3))
    page.insert_text((40, 55), "ROHAN DESAI", fontsize=22, fontname="hebo", color=(1, 1, 1))
    page.insert_text((40, 78), "Data Analyst", fontsize=12, fontname="helv", color=(1, 1, 1))

    left = _Writer(page, 130, right=180)
    for head, items in (("CONTACT", ["rohan.desai@example.com", "+91 91234 56789", "Pune, Maharashtra"]),
                        ("SKILLS", ["SQL", "Python", "Tableau", "Excel"]),
                        ("LANGUAGES", ["English", "Marathi"])):
        left.text(30, left.y, head, size=11, bold=True)
        left.y += 16
        for it in items:
            left.text(30, left.y, it, size=10)
            left.y += 14
        left.y += 14

    right = _Writer(page, 130, right=560)
    for head, paras in (
        ("PROFILE", ["Data analyst with two years of experience turning messy operational data into clear "
                     "dashboards and forecasts that business teams actually use every week."]),
        ("EXPERIENCE", ["Data Analyst, Brightline Logistics (2023 - Present)",
                        "Cut weekly reporting time from six hours to forty minutes by rebuilding the pipeline in SQL "
                        "and Python with automated data quality checks.",
                        "Forecast regional demand with a seasonal model that reduced stock-outs by 9%."]),
        ("PROJECTS", ["Retail Churn Dashboard: a Tableau dashboard that flags customers likely to churn using "
                      "purchase recency and frequency."]),
        ("EDUCATION", ["B.Sc Statistics, Riverside College of Science, 2020 - 2023"]),
    ):
        right.text(210, right.y, head, size=11, bold=True)
        right.y += 16
        for text in paras:
            right.para(210, text, size=10)
        right.y += 8
    return doc.tobytes()


def make_caps_entries_pdf() -> bytes:
    """Deedy-style: section headings AND entries are ALL CAPS; only font size/weight tells them apart.
    Also an unknown "LINKS" section full of social handles, an unknown "MY LIFE PHILOSOPHY" section
    in heading style, a superscript ordinal and a word hyphenated at the end of a line."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    w = _Writer(page, 50, right=545)

    def head(s):  # section heading: 15pt regular capitals
        w.y += 8
        w.text(40, w.y, s, size=15)
        w.y += 20

    def entry(s):  # entry title: 10.5pt bold capitals
        w.text(40, w.y, s, size=10.5, bold=True)
        w.y += 15

    w.text(40, w.y, "MEERA IYER", size=24, bold=True)
    w.y += 18
    w.text(40, w.y, "meera.iyer@example.com | +91 90000 11111", size=10)
    w.y += 14
    head("EDUCATION")
    entry("STATE UNIVERSITY OF EXAMPLE")
    w.text(40, w.y, "MSc in Data Science, GPA 3.9/4.0")
    w.y += 16
    head("EXPERIENCE")
    entry("ORBITAL LABS | DATA ENGINEER")
    # a full-width line that ends in a word hyphenated with a soft hyphen ("analyt-" + "ics")
    first = "Built streaming pipelines processing 4 million events a day with Kafka and Spark for the analyt­"
    w.text(42, w.y, "•")
    w.text(55, w.y, first)
    w.y += 14.5
    w.text(55, w.y, "ics team and three downstream products.")
    w.y += 16
    head("AWARDS")
    # "1st" with a raised, smaller "st"
    w.text(40, w.y, "1", size=10.5)
    w.text(46, w.y - 3.5, "st", size=7)
    w.text(56, w.y, "place, Regional Data Hackathon", size=10.5)
    w.y += 16
    head("SKILLS")
    entry("PROGRAMMING")
    w.text(40, w.y, "Python, Scala, SQL")
    w.y += 16
    entry("GRADUATE COURSEWORK")
    w.text(40, w.y, "Distributed Systems, Statistical Learning")
    w.y += 16
    head("LINKS")
    for handle in ("GitHub: @meera_iyer", "Twitter: @meeraiyer42", "Blog: meeraiyer.example.dev"):
        w.text(40, w.y, handle)
        w.y += 14
    head("MY LIFE PHILOSOPHY")
    w.text(40, w.y, "Measure twice, ship once.")
    return doc.tobytes()


def make_date_strip_pdf() -> bytes:
    """Harvard-style: every date sits in a right-aligned strip beside its entry (not a second column)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    w = _Writer(page, 60, right=545)
    w.text(40, w.y, "Arjun Rao", size=20, bold=True)
    w.y += 26
    entries = [
        ("Experience", [("Fintech Labs, Backend Engineer", "June 2023 - present",
                         "Rebuilt the payments ledger in Go, handling 3,000 transactions per second."),
                        ("Cloudlet, Software Intern", "May 2022 - Aug 2022",
                         "Added request tracing across 40 microservices with OpenTelemetry."),
                        ("Datawise, Analytics Intern", "May 2021 - Aug 2021",
                         "Automated weekly KPI reports with Python and SQL.")]),
        ("Projects", [("Ledger Visualiser", "Jan 2023 - present", "Open-source tool to explore double-entry books."),
                      ("Rate Limiter", "Jan 2021", "Token-bucket rate limiter library in Rust.")]),
        ("Education", [("Princeton University, BS in Computer Science - Princeton, NJ", "Sept 2017 - May 2021",
                        "GPA: 3.8/4.0, Fulbright Scholarship recipient")]),
    ]
    for heading, items in entries:
        w.y += 6
        w.text(40, w.y, heading, size=13, bold=True)
        w.y += 18
        for title, date, detail in items:
            w.text(40, w.y, title, bold=True)
            w.text(545 - fitz.get_text_length(date, "helv", 10.5), w.y, date)
            w.y += 15
            w.text(55, w.y, "•")
            w.text(65, w.y, detail)
            w.y += 18
    return doc.tobytes()
