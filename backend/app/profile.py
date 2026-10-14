"""Build a *blind profile* from resume text.

Instead of masking values in place ("Email: [REMOVED]"), the resume is split into sections and
only professional sections are kept: summary, skills, experience, projects, education,
certifications, achievements. The contact header, personal-details block, declaration, hobbies,
languages and references are dropped completely, labels and all. Inside the kept sections any
remaining identifier (a name, link, location, pronoun ...) is still scrubbed.

What was dropped is returned separately as the candidate's *identity*, which the HR reviewer
only gets to see after accepting the candidate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .detect import CATEGORIES, RE_INSTITUTION, Finding, build_matcher, normalize_term

HIDDEN = "[hidden]"

SECTION_ALIASES = {
    "summary": ["summary", "professional summary", "profile", "professional profile", "career objective",
                "objective", "about me", "about", "career summary", "executive summary", "profile summary"],
    "skills": ["skills", "technical skills", "key skills", "core skills", "core competencies", "skills and tools",
               "tools and technologies", "technologies", "skill set", "skillset", "technical expertise",
               "competencies", "tech stack", "soft skills", "skills summary", "areas of expertise", "expertise"],
    "experience": ["experience", "work experience", "professional experience", "employment history",
                   "work history", "internship", "internships", "internship experience", "relevant experience",
                   "employment", "experience and internships", "work"],
    "projects": ["projects", "academic projects", "personal projects", "key projects", "project experience",
                 "major projects", "project", "project work", "projects undertaken"],
    "education": ["education", "academic qualifications", "academic qualification", "educational qualifications",
                  "educational qualification", "qualifications", "academics", "academic background",
                  "education and training", "educational background", "academic details", "academic profile"],
    "certifications": ["certifications", "certificates", "certification", "courses", "trainings", "training",
                       "licenses and certifications", "online courses", "courses and certifications",
                       "certifications and courses", "relevant coursework", "coursework"],
    "achievements": ["achievements", "awards", "honors", "honours", "accomplishments", "awards and achievements",
                     "achievements and awards", "awards and honors", "key achievements"],
    "publications": ["publications", "research", "research papers", "papers"],
    "strengths": ["strengths", "key strengths", "personal strengths"],
    # dropped during blind review
    "personal": ["personal details", "personal information", "personal profile", "personal data", "personal info",
                 "other details", "additional information", "additional details", "biodata"],
    "contact": ["contact", "contact information", "contact details", "contact info", "contacts"],
    "declaration": ["declaration", "signature"],
    "hobbies": ["hobbies", "interests", "hobbies and interests", "interests and hobbies", "personal interests"],
    "languages": ["languages", "languages known", "language proficiency", "linguistic proficiency"],
    "references": ["references", "referees", "reference"],
    "activities": ["extracurricular activities", "extra curricular activities", "extracurricular",
                   "extra curricular", "co curricular activities", "activities", "volunteering",
                   "volunteer experience", "positions of responsibility"],
}
TITLES = {
    "summary": "Summary", "skills": "Skills", "experience": "Experience", "projects": "Projects",
    "education": "Education", "certifications": "Certifications", "achievements": "Achievements",
    "publications": "Publications", "strengths": "Strengths",
}
KEPT = set(TITLES) | {"other"}
ORDER = list(TITLES) + ["other"]
ALIAS_TO_KEY = {alias: key for key, aliases in SECTION_ALIASES.items() for alias in aliases}
PERSONAL_WORDS = re.compile(
    r"personal|contact|family|declaration|hobb|interest|language|reference|signature|photo|detail|religio|caste",
    re.I,
)
TITLE_ONLY = {"resume", "curriculum vitae", "cv", "biodata", "bio data", "resume of", "profile"}
CONTACT_HINT = re.compile(
    r"@|https?://|www\.|\.com\b|\.in\b|\b(?:e-?mail|phone|mobile|mob|tel|contact|linkedin|github|address|city"
    r"|location|portfolio|dob|born|whatsapp|url)\b",
    re.I,
)
SCRUB_CATEGORIES = {"name", "email", "phone", "url", "id_number", "dob_age", "gender", "location"}
PRONOUNS = {"he": "they", "she": "they", "him": "them", "her": "their", "his": "their", "hers": "theirs",
            "himself": "themselves", "herself": "themselves"}
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
RE_YEAR_RANGE = re.compile(
    rf"(?:{_MONTH}[ \t]+)?(?:19|20)\d{{2}}[ \t]*(?:[-–—]|to)[ \t]*"
    rf"(?:(?:{_MONTH}[ \t]+)?(?:19|20)\d{{2}}|[Pp]resent|[Cc]urrent|[Nn]ow|[Tt]ill [Dd]ate)\b"
)
RE_SINGLE_YEAR = re.compile(rf"\b(?:{_MONTH}[ \t]+)?(?:19|20)\d{{2}}\b|\b\d{{1,2}}/(?:19|20)\d{{2}}\b")
RE_INSTITUTION_ABBR = re.compile(r"\b(?:IIT|NIT|IIIT|BITS|VIT|SRM|IIM|IISc|JNTU|JNTUH|JNTUK|MIT)\b(?:[ ,\-]+[A-Z][a-z]+)?")


@dataclass
class ProfileOptions:
    hide_institutions: bool = True      # college prestige is a common source of bias
    hide_education_years: bool = True   # graduation years reveal age


def _norm_heading(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z ]", " ", text)
    return " ".join(text.split())


def classify_heading(line: str):
    """Return (key, title, rest-of-line) if the line starts a section."""
    stripped = line.strip().strip("•*#=_●▪").strip()
    if not stripped or len(stripped) > 70:
        return None
    candidates = [(stripped, "")]
    m = re.match(r"^([A-Za-z &/'’]{3,40}?)[ \t]*(?::|\||[\-–—][ \t])[ \t]*(.*)$", stripped)
    if m:
        candidates.append((m.group(1), m.group(2)))
    for head, rest in candidates:
        key = ALIAS_TO_KEY.get(_norm_heading(head))
        if key:
            return key, head.strip(" :"), rest.strip()
    # an unrecognised ALL-CAPS heading such as "LEADERSHIP"
    if re.fullmatch(r"[A-Z][A-Z &/'’]{2,40}:?", stripped) and len(stripped.split()) <= 4:
        title = stripped.rstrip(":").title()
        return ("personal" if PERSONAL_WORDS.search(stripped) else "other"), title, ""
    return None


def split_sections(text: str):
    """-> (header_lines, [ {key, title, lines} ])"""
    header: list[str] = []
    sections: list[dict] = []
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not header and current is None:
            # the very first line is the candidate's name (or "RESUME"), never a section heading
            if _norm_heading(line) in TITLE_ONLY:
                continue
            header.append(line)
            continue
        heading = classify_heading(line)
        if heading and heading[0] == "other" and current is None:
            heading = None  # an ALL-CAPS line in the header block is a name or title, not a section
        if heading:
            key, title, rest = heading
            title = title.title() if title.isupper() else title
            current = {"key": key, "title": TITLES.get(key, title), "lines": []}
            sections.append(current)
            if rest:
                current["lines"].append(rest)
        elif current is None:
            header.append(line)
        elif current["lines"] and re.match(r"[a-z(&,]", line):
            current["lines"][-1] += " " + line  # a sentence wrapped onto the next PDF line
        else:
            current["lines"].append(line)
    return header, sections


class Scrubber:
    def __init__(self, text: str, findings: list[Finding], options: ProfileOptions):
        terms = {f.text: f.category for f in findings if f.category in SCRUB_CATEGORIES}
        if options.hide_institutions:
            for rx in (RE_INSTITUTION, RE_INSTITUTION_ABBR):
                for m in rx.finditer(text):
                    value = m.group(0).strip(" ,-")
                    if len(value.split()) >= 2 or rx is RE_INSTITUTION_ABBR:
                        terms.setdefault(value, "organization")
        self.categories = {normalize_term(t): c for t, c in terms.items()}
        self.matcher = build_matcher(list(terms))
        self.count = 0

    def _replace(self, m: re.Match) -> str:
        word = m.group(0)
        self.count += 1
        neutral = PRONOUNS.get(word.lower())
        if neutral and self.categories.get(normalize_term(word)) == "gender":
            return neutral.capitalize() if word[0].isupper() else neutral
        return HIDDEN

    def __call__(self, line: str, hide_years: bool = False) -> str:
        if self.matcher is not None:
            line = self.matcher.sub(self._replace, line)
        if hide_years:
            line, n1 = RE_YEAR_RANGE.subn(HIDDEN, line)
            line, n2 = RE_SINGLE_YEAR.subn(HIDDEN, line)
            self.count += n1 + n2
        # collapse leftovers such as "[hidden], [hidden]" or "| [hidden] |"
        line = re.sub(r"(\[hidden\])(?:[ \t]*[,|/]?[ \t]*\[hidden\])+", HIDDEN, line)
        return line.strip()


def _split_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for line in lines:
        if ":" in line and len(line.split(":", 1)[0]) < 30:
            line = line.split(":", 1)[1]
        for part in re.split(r"[,•|;·●▪\t]|\s{2,}|\s[-–]\s", line):
            part = part.strip(" .*-")
            if part and len(part) <= 40 and HIDDEN not in part and part.lower() not in {s.lower() for s in skills}:
                skills.append(part)
    return skills


def build_profile(text: str, findings: list[Finding], options: ProfileOptions | None = None,
                  image_count: int = 0):
    """-> (profile, identity). The profile is safe to show before a decision; identity is not."""
    options = options or ProfileOptions()
    header, sections = split_sections(text)
    scrub = Scrubber(text, findings, options)

    # The header holds name + contact lines; keep only a job headline such as "Python Developer".
    headline_parts, header_hidden = [], []
    for i, line in enumerate(header):
        has_pii = scrub.matcher is not None and scrub.matcher.search(line)
        digits = sum(ch.isdigit() for ch in line)
        if i == 0 or has_pii or CONTACT_HINT.search(line) or digits >= 5:
            header_hidden.append(line)
        else:
            headline_parts.append(scrub(line))

    kept, hidden_sections = {}, []
    for s in sections:
        if s["key"] in KEPT:
            hide_years = options.hide_education_years and s["key"] == "education"
            lines = [scrub(l, hide_years) for l in s["lines"]]
            lines = [l for l in lines if l and l != HIDDEN]
            if not lines:
                continue
            if s["key"] == "other":
                kept.setdefault(("other", s["title"]), []).extend(lines)
            else:
                kept.setdefault((s["key"], s["title"]), []).extend(lines)
        else:
            hidden_sections.append({"title": s["title"], "lines": s["lines"]})

    profile_sections = [
        {"key": key, "title": title, "lines": lines}
        for (key, title), lines in sorted(kept.items(), key=lambda kv: ORDER.index(kv[0][0]))
    ]
    warnings = []
    if not sections:
        warnings.append("No section headings were recognised; the profile may be incomplete.")
        body = [scrub(l) for l in text.splitlines()[1:] if l.strip() and not CONTACT_HINT.search(l)]
        profile_sections = [{"key": "other", "title": "Resume", "lines": [l for l in body if l]}]

    skills_section = next((s for s in profile_sections if s["key"] == "skills"), None)
    profile = {
        "headline": " · ".join(p for p in headline_parts if p and p != HIDDEN)[:160],
        "skills": _split_skills(skills_section["lines"]) if skills_section else [],
        "sections": profile_sections,
        "hidden": {
            "header_lines": len(header_hidden),
            "sections": [h["title"] for h in hidden_sections],
            "inline": scrub.count,
            "photo": image_count > 0,
            "institutions": options.hide_institutions,
            "education_years": options.hide_education_years,
        },
        "warnings": warnings,
    }
    identity = _identity(findings, header, header_hidden, hidden_sections)
    return profile, identity


def _identity(findings: list[Finding], header: list[str], header_hidden: list[str], hidden_sections: list[dict]):
    def values(category, sources=None):
        return [f.text for f in findings if f.category == category and (not sources or set(f.sources) & sources)]

    trusted_names = values("name", {"heuristic"}) or values("name", {"label"})
    name = trusted_names[0] if trusted_names else (header[0] if header else "")
    if name.isupper():
        name = name.title()  # "ASHA REDDY" -> "Asha Reddy"
    # personal details not already visible in a hidden section (e.g. a DOB inside the summary)
    hidden_text = "\n".join(header_hidden + [l for s in hidden_sections for l in s["lines"]]).lower()
    others = []
    for f in findings:
        if (f.category in {"dob_age", "gender", "id_number"} and f.text.lower() not in PRONOUNS
                and f.text.lower() not in hidden_text):
            others.append({"label": CATEGORIES[f.category]["label"], "value": f.text})
    return {
        "name": name,
        "emails": values("email"),
        "phones": values("phone"),
        "links": values("url"),
        "locations": [v for v in values("location") if len(v) > 2],
        "details": others,
        "header": header_hidden,
        "hidden_sections": hidden_sections,
    }
