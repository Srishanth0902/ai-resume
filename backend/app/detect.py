"""Personal-information detection for resume text.

Three detectors are combined:
  * regular expressions   -> predictable patterns (email, phone, URLs, IDs, dates)
  * labelled-field rules  -> "Gender: Female", "Date of Birth: ...", "Address: ..."
  * spaCy NER + heuristics -> person names and places that need context to recognise

The output is a list of unique *findings* (term + category) plus every place each
term occurs in the text, so the UI preview matches exactly what will be redacted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

# --------------------------------------------------------------------------- categories

CATEGORIES: dict[str, dict] = {
    "name":         {"label": "Names",                         "tag": "NAME",         "default": True,  "priority": 70},
    "email":        {"label": "Email addresses",               "tag": "EMAIL",        "default": True,  "priority": 100},
    "phone":        {"label": "Phone numbers",                 "tag": "PHONE",        "default": True,  "priority": 85},
    "url":          {"label": "Profile links & URLs",          "tag": "LINK",         "default": True,  "priority": 95},
    "id_number":    {"label": "ID numbers (Aadhaar, PAN ...)", "tag": "ID",           "default": True,  "priority": 90},
    "dob_age":      {"label": "Date of birth & age",           "tag": "DOB/AGE",      "default": True,  "priority": 80},
    "gender":       {"label": "Gender & personal status",      "tag": "PERSONAL",     "default": True,  "priority": 75},
    "location":     {"label": "Address & location",            "tag": "LOCATION",     "default": True,  "priority": 60},
    "organization": {"label": "Colleges & organisations",      "tag": "ORGANIZATION", "default": False, "priority": 40},
    "date":         {"label": "Other dates & years",           "tag": "DATE",         "default": False, "priority": 30},
}

# Words that spaCy sometimes mistakes for people/places/orgs on resumes.
TECH_TERMS = {
    "python", "java", "javascript", "typescript", "react", "react.js", "reactjs", "angular", "vue", "node",
    "node.js", "nodejs", "express", "django", "flask", "fastapi", "spring", "sql", "mysql", "postgresql",
    "postgres", "mongodb", "redis", "sqlite", "oracle", "html", "css", "sass", "tailwind", "bootstrap",
    "aws", "azure", "gcp", "docker", "kubernetes", "git", "github", "gitlab", "linux", "unix", "bash",
    "tableau", "power", "bi", "excel", "pandas", "numpy", "scikit", "sklearn", "tensorflow", "pytorch",
    "keras", "spark", "hadoop", "kafka", "c", "c++", "c#", "kotlin", "swift", "flutter", "dart", "go",
    "golang", "rust", "ruby", "rails", "php", "laravel", "selenium", "matlab", "r", "jira", "figma",
    "agile", "scrum", "devops", "jenkins", "terraform", "ansible", "graphql", "rest", "api", "apis",
    "nlp", "ml", "ai", "opencv", "spacy", "nltk", "hugging", "face", "streamlit", "firebase", "android",
    "ios", "salesforce", "sap", "jquery", "next.js", "nextjs", "vite", "webpack", "postman", "canva",
    "photoshop", "illustrator", "autocad", "solidworks", "arduino", "raspberry", "pi", "ms", "office",
    "word", "powerpoint", "outlook", "windows", "macos", "json", "xml", "yaml", "dsa", "oop", "dbms",
}

HEADING_WORDS = {
    "resume", "curriculum", "vitae", "cv", "profile", "summary", "objective", "career", "skills",
    "technical", "education", "experience", "work", "projects", "project", "certifications",
    "certificates", "achievements", "awards", "contact", "personal", "details", "information",
    "languages", "hobbies", "interests", "references", "declaration", "internship", "internships",
    "professional", "academic", "qualifications", "strengths", "activities", "extracurricular",
    "responsibilities", "publications", "about", "me", "core", "competencies", "tools", "soft",
    "developer", "engineer", "intern", "analyst", "manager", "student", "software", "data",
    "scientist", "designer", "consultant", "fresher", "graduate", "web", "full", "stack", "frontend",
    "backend", "dashboard", "sales", "page", "email", "phone", "mobile", "address", "name",
    "gender", "sex", "marital", "status", "nationality", "religion", "birth", "date", "dob", "age",
    "father's", "mother's", "place", "location", "city", "linkedin", "portfolio", "website", "github",
    "your", "url", "id",
}

# Resume bullets start with action verbs; spaCy sometimes reads "Spearheaded Kindle Corner" as a name.
ACTION_VERBS = {
    "achieved", "addressed", "analyzed", "analysed", "architected", "assisted", "automated", "awarded", "built",
    "championed", "collaborated", "completed", "conducted", "configured", "contributed", "coordinated", "created",
    "delivered", "deployed", "designed", "developed", "directed", "drove", "enabled", "engineered", "enhanced",
    "established", "evaluated", "executed", "facilitated", "founded", "generated", "guided", "handled", "headed",
    "helped", "identified", "implemented", "improved", "increased", "initiated", "integrated", "introduced",
    "launched", "led", "maintained", "managed", "mentored", "migrated", "mobilized", "modelled", "modeled",
    "monitored", "optimized", "optimised", "organized", "organised", "oversaw", "participated", "partnered",
    "planned", "planted", "presented", "produced", "programmed", "published", "ran", "received", "reduced",
    "refactored", "researched", "resolved", "reviewed", "scaled", "secured", "selected", "served", "spearheaded",
    "streamlined", "supervised", "supported", "taught", "tested", "trained", "translated", "volunteered", "won",
    "worked", "wrote",
}

INSTITUTION_ABBRS = {"IIT", "NIT", "IIIT", "BITS", "VIT", "SRM", "IIM", "IISC", "JNTU", "JNTUH", "JNTUK", "MIT", "AIIMS"}

COUNTRIES = {
    "india", "usa", "u.s.", "u.s.a.", "united states", "america", "uk", "united kingdom", "england", "canada",
    "australia", "germany", "france", "japan", "china", "singapore", "uae", "dubai", "nepal", "sri lanka",
    "bangladesh", "pakistan", "europe", "asia", "africa", "ireland", "netherlands", "new zealand",
}

# Ordinary resume vocabulary. spaCy's small model often tags phrases such as "Machine Learning"
# or "Isolation Forest" as PERSON; a real name never contains these words.
COMMON_WORDS = {
    "machine", "learning", "deep", "science", "analytics", "analysis", "artificial", "intelligence",
    "computer", "vision", "natural", "language", "processing", "cloud", "computing", "development",
    "engineering", "management", "business", "marketing", "finance", "design", "research", "system",
    "systems", "network", "networks", "networking", "security", "cyber", "application", "applications",
    "model", "models", "modeling", "modelling", "neural", "statistics", "mathematics", "physics",
    "chemistry", "electronics", "electrical", "mechanical", "civil", "communication", "communications",
    "information", "technology", "technologies", "smart", "meter", "anomaly", "detection", "forest",
    "isolation", "regression", "classification", "prediction", "predictive", "team", "lead", "leader",
    "club", "college", "university", "school", "institute", "hackathon", "workshop", "certificate",
    "course", "bachelor", "master", "degree", "diploma", "b.tech", "m.tech", "bsc", "msc", "mba",
    "basics", "fundamentals", "cleaning", "visualization", "visualisation", "mining", "warehouse",
    "big", "generative", "agent", "agents", "chatbot", "automation", "testing", "quality", "support",
    "operations", "product", "service", "services", "solutions", "platform", "pipeline", "framework",
    "exploratory", "statistical", "academic", "personal", "summer", "winter", "online", "virtual",
    "united", "states", "national", "international", "global", "digital", "student", "students",
    "trainee", "associate", "senior", "junior", "head", "member", "volunteer", "coordinator",
    "president", "secretary", "captain", "public", "private", "limited", "ltd", "pvt", "inc", "llc",
    "labs", "lab", "corp", "corporation", "technologies", "tech", "group", "studio", "studios", "ventures",
    "capital", "consulting", "partners", "foundation", "bank", "motors", "industries", "enterprises", "media",
    "software", "logistics", "pharma", "pharmaceuticals", "infotech", "systems", "global", "holdings",
    "english", "hindi", "telugu", "tamil", "kannada", "malayalam", "marathi", "bengali", "gujarati",
    "punjabi", "urdu", "odia", "french", "german", "spanish", "japanese", "mandarin", "arabic",
}

# --------------------------------------------------------------------------- regexes

_DATE = (
    r"(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}"
    r"|\d{1,2}(?:st|nd|rd|th)?[ \-]+[A-Za-z]{3,9}\.?,?[ \-]+\d{4}"
    r"|[A-Za-z]{3,9}\.?[ ]+\d{1,2}(?:st|nd|rd|th)?,?[ ]+\d{4})"
)
_SEP = r"[ \t]*[:|\-\u2013\u2014=][ \t]*"     # "Label: value", "Label | value", "Label - value"

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RE_URL = re.compile(
    r"(?:https?://|www\.)[^\s|,;()<>\"']+"
    r"|\b(?:linkedin\.com|github\.com|gitlab\.com|bitbucket\.org|behance\.net|dribbble\.com|medium\.com"
    r"|twitter\.com|x\.com|instagram\.com|facebook\.com|kaggle\.com|leetcode\.com|hackerrank\.com"
    r"|codechef\.com|codeforces\.com|stackoverflow\.com|youtube\.com|about\.me)/[^\s|,;()<>\"']+",
    re.IGNORECASE,
)
RE_PHONE = re.compile(r"(?<![\w/@.])(\+?\(?\d[\d \t().\-]{8,18}\d)(?![\w/@])")
RE_AADHAAR = re.compile(r"(?<!\d)\d{4}[ \-]\d{4}[ \-]\d{4}(?!\d)")
RE_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
RE_ID_LABELLED = re.compile(
    r"(?i:passport|aadhaa?r|pan|roll|registration|reg\.?|hall[ \t]*ticket|enrol?ment|employee[ \t]*id"
    r"|driving[ \t]*licen[cs]e|licen[cs]e|voter[ \t]*id|uan|ssn)"
    r"[ \t]*(?i:no\.?|number|num|#|id|card)?" + _SEP + r"([A-Z0-9][A-Z0-9 \-/]{3,22}[A-Z0-9])"
)
RE_DOB = re.compile(
    r"(?i:d\.?[ \t]*o\.?[ \t]*b\.?|date[ \t]+of[ \t]+birth|birth[ \t]*date|born(?:[ \t]+on)?)"
    r"(?:" + _SEP + r"|[ \t]+)(" + _DATE + r")"
)
RE_AGE = re.compile(
    r"(?i:\bage\b)" + _SEP + r"(\d{2}(?:[ \t]*(?i:years|yrs))?)"
    r"|\b(\d{2}[ \t]*(?i:years|yrs)[ \t]+(?i:old))\b"
    r"|\b(?i:aged)[ \t]+(\d{2})\b"
)
RE_PERSONAL_LABELLED = re.compile(
    r"(?im)^[ \t]*(?:[\-\u2022*\u25cf][ \t]*)?"
    r"(gender|sex|marital[ \t]+status|nationality|religion|caste|community|category|blood[ \t]+group)"
    + _SEP + r"([^\n|]{1,40}?)[ \t]*$"
)
RE_RELATIVE_NAME = re.compile(
    r"(?im)^[ \t]*(?:[\-\u2022*\u25cf][ \t]*)?"
    r"(?:father|mother|husband|wife|spouse|guardian|parent)(?:'?s|\u2019s)?[ \t]+name"
    + _SEP + r"([^\n|]{2,60}?)[ \t]*$"
)
RE_RELATION_PREFIX = re.compile(r"\b([SDWC]/[Oo])\.?[ \t]+((?:[A-Z][\w.]*[ \t]?){1,4})")
# not "Sri"/"Shri": they start many Indian company and school names ("Sri Lakshmi Traders")
RE_TITLE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Smt|Kumari|Kum)\.?(?=[ \t]+[A-Z])")
RE_PRONOUN = re.compile(r"\b(?i:he|she|him|her|his|hers|himself|herself)\b")
RE_NAME_LABELLED = re.compile(
    r"(?im)^[ \t]*(?:[\-\u2022*\u25cf][ \t]*)?(?:full[ \t]+|candidate[ \t]+|applicant[ \t]+)?name"
    + _SEP + r"([^\n|]{2,60}?)[ \t]*$"
)
RE_ADDRESS_LABELLED = re.compile(
    r"(?im)^[ \t]*(?:[\-\u2022*\u25cf][ \t]*)?"
    r"(?:(?:permanent|current|present|residential|home|postal|correspondence)[ \t]+)?"
    r"(?:address|location|residence|current[ \t]+city|city|hometown|place)"
    + _SEP + r"([^\n|]{2,120}?)[ \t]*$"
)
RE_PINCODE_CITY = re.compile(r"\b[A-Z][a-zA-Z]+[ \t]*[\-\u2013,][ \t]*\d{3}[ ]?\d{3}\b")
_INSTITUTION_WORDS = ["University", "College", "Institute", "School", "Academy", "Polytechnic", "Vidyalaya",
                      "Vidyalayam", "Kalasala", "Kalashala", "Mahavidyalaya", "Vidyapeeth", "Vidyapith",
                      "Vidyapeetham", "Gurukul"]
RE_INSTITUTION = re.compile(
    r"\b(?:[A-Z][\w&.'\-]*[ \t]+){0,6}"
    # Title Case or ALL CAPS ("CORNELL UNIVERSITY"), but never lowercase "university students"
    r"(?:" + "|".join(w for word in _INSTITUTION_WORDS for w in (word, word.upper())) + r")\b"
    r"(?:[ \t]+(?:of|for|OF|FOR)(?:[ \t]+(?:[A-Z][\w&.'\-]*|and|AND|&)){1,6})?"
    r"(?:,[ \t]*[A-Z][a-z]+\b(?![ \t]*[A-Z][a-z]))?"  # plus a trailing ", City" (a whole word, not "Ph" of "PhD")
)
RE_OTHER_DATE = re.compile(
    r"\b(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?[ \t]+(?:19|20)\d{2}"
    r"|\d{1,2}/(?:19|20)\d{2}"
    r"|(?:19|20)\d{2})\b"
)

# --------------------------------------------------------------------------- data types


@dataclass
class Detection:
    text: str
    category: str
    start: int
    end: int
    source: str

    @property
    def priority(self) -> int:
        return CATEGORIES[self.category]["priority"]


@dataclass
class Finding:
    id: str
    text: str
    category: str
    sources: list[str] = field(default_factory=list)
    default_selected: bool = True
    occurrences: list[tuple[int, int]] = field(default_factory=list)


# --------------------------------------------------------------------------- helpers


def _clean(value: str) -> str:
    return value.strip().strip(".,;:|\u2022*-").strip()


def _add_group(out: list[Detection], m: re.Match, group: int, category: str, source: str) -> None:
    raw = m.group(group)
    if not raw:
        return
    value = _clean(raw)
    if not value:
        return
    start = m.start(group) + raw.find(value)
    out.append(Detection(value, category, start, start + len(value), source))


def _is_tech(token: str) -> bool:
    bare = token.lower().strip(".,()")
    # library-style names such as Chart.js, ASP.NET, scikit-learn
    return bare in TECH_TERMS or bool(re.search(r"\w\.(js|ts|py|net|io)$|^\w+-learn$", bare))


def _looks_like_name(text: str) -> bool:
    tokens = text.split()
    if not 1 <= len(tokens) <= 4 or len(text) > 45:
        return False
    if any(ch.isdigit() or ch in "@/:|&()" for ch in text):
        return False
    for tok in tokens:
        bare = tok.strip(".,'\u2019-")
        if not bare or not bare[0].isalpha() or not bare[0].isupper():
            return False
        if _is_tech(bare) or bare.lower() in HEADING_WORDS:
            return False
    return True


# --------------------------------------------------------------------------- detectors


def _regex_detections(text: str) -> list[Detection]:
    out: list[Detection] = []

    for m in RE_EMAIL.finditer(text):
        out.append(Detection(m.group(0), "email", m.start(), m.end(), "regex"))

    for m in RE_URL.finditer(text):
        value = m.group(0).rstrip(".")
        out.append(Detection(value, "url", m.start(), m.start() + len(value), "regex"))

    for m in RE_AADHAAR.finditer(text):
        out.append(Detection(m.group(0), "id_number", m.start(), m.end(), "regex"))
    for m in RE_PAN.finditer(text):
        out.append(Detection(m.group(0), "id_number", m.start(), m.end(), "regex"))
    for m in RE_ID_LABELLED.finditer(text):
        _add_group(out, m, 1, "id_number", "label")

    for m in RE_PHONE.finditer(text):
        value = m.group(1).strip(" \t.-")
        digits = sum(ch.isdigit() for ch in value)
        if 10 <= digits <= 13 and not re.fullmatch(r"(?:19|20)\d{2}\s*[-\u2013]\s*(?:19|20)\d{2}.*", value):
            start = m.start(1) + m.group(1).find(value)
            out.append(Detection(value, "phone", start, start + len(value), "regex"))

    for m in RE_DOB.finditer(text):
        _add_group(out, m, 1, "dob_age", "label")
    for m in RE_AGE.finditer(text):
        for g in (1, 2, 3):
            if m.group(g):
                _add_group(out, m, g, "dob_age", "label")

    for m in RE_PERSONAL_LABELLED.finditer(text):
        _add_group(out, m, 2, "gender", "label")
    for m in RE_TITLE.finditer(text):
        out.append(Detection(m.group(0), "gender", m.start(), m.end(), "regex"))
    for m in RE_PRONOUN.finditer(text):
        out.append(Detection(m.group(0), "gender", m.start(), m.end(), "regex"))
    for m in RE_RELATION_PREFIX.finditer(text):
        _add_group(out, m, 1, "gender", "regex")
        _add_group(out, m, 2, "name", "regex")

    for m in RE_NAME_LABELLED.finditer(text):
        _add_group(out, m, 1, "name", "label")
    for m in RE_RELATIVE_NAME.finditer(text):
        _add_group(out, m, 1, "name", "label")

    for m in RE_ADDRESS_LABELLED.finditer(text):
        _add_group(out, m, 1, "location", "label")
    for m in RE_PINCODE_CITY.finditer(text):
        out.append(Detection(m.group(0), "location", m.start(), m.end(), "regex"))

    for m in RE_INSTITUTION.finditer(text):
        value = _clean(m.group(0))
        if len(value.split()) >= 2:
            start = m.start() + m.group(0).find(value)
            out.append(Detection(value, "organization", start, start + len(value), "regex"))

    for m in RE_OTHER_DATE.finditer(text):
        out.append(Detection(m.group(0), "date", m.start(), m.end(), "regex"))

    return out


def _header_name(text: str) -> list[Detection]:
    """Resumes almost always start with the candidate's name; check the first few lines."""
    offset = 0
    checked = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            checked += 1
            # A heading like "RESUME" or a name followed by a job title "Asha Reddy | Developer"
            candidate = re.split(r"\s+[|\u2022\u2013\u2014]\s+|\s{3,}", stripped)[0].strip()
            if _looks_like_name(candidate) and len(candidate.split()) >= 2:
                start = offset + line.find(candidate)
                return [Detection(candidate, "name", start, start + len(candidate), "heuristic")]
            if checked >= 5:
                break
        offset += len(line)
    return []


@lru_cache(maxsize=1)
def _load_nlp():
    try:
        import spacy

        return spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "attribute_ruler"])
    except Exception:  # model not installed -> regex/heuristics only
        return None


def nlp_available() -> bool:
    return _load_nlp() is not None


def _spacy_detections(text: str) -> list[Detection]:
    nlp = _load_nlp()
    if nlp is None or not text.strip():
        return []
    out: list[Detection] = []
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ not in {"PERSON", "GPE", "LOC", "ORG"}:
            continue
        # entities can run across a line break or a table separator; split them
        offset = ent.start_char
        for part in re.split(r"(\n|\s\|\s)", ent.text):
            value = _clean(part)
            if value and part not in ("\n", " | "):
                start = offset + part.find(value)
                det = _classify_spacy(value, ent.label_, start)
                if det and det.category == "name" and not _person_context(text, start, value):
                    det = None  # "Ledger Visualiser", "Fintech Labs": title-case words, not a person
                if det:
                    out.append(det)
            offset += len(part)
    return out


RE_PERSON_CUE = re.compile(
    r"(?:\b(?:Prof|Dr|Mr|Mrs|Ms|Miss|Sir|Shri|Smt)\.?|\b(?:advis[eo]r|mentor|guide|supervisor|manager|reference"
    r"|referee|reporting to|reported to|under|with|worked with|guided by|supervised by|by)\b)\s*:?\s*$",
    re.IGNORECASE,
)
RE_INITIALED_NAME = re.compile(r"^(?:[A-Z]\.\s?){1,2}[A-Z][a-z]+|^[A-Z][a-z]+\s(?:[A-Z]\.\s?){1,2}[A-Z][a-z]+")


def _person_context(text: str, start: int, value: str) -> bool:
    """spaCy guesses PERSON for many title-case phrases in resumes (project, company and event names).
    Outside the header, only trust it when something marks a person: a title or role word right
    before ("Prof. ...", "Advisor: ..."), an initial ("A. Jain"), or an author list."""
    if text.count("\n", 0, start) < 2:  # the top lines, where the candidate's own name sits
        return True
    before = text[max(0, start - 30):start]
    if RE_PERSON_CUE.search(before) or RE_INITIALED_NAME.match(value):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    line = text[line_start:line_end if line_end != -1 else len(text)]
    return bool(re.search(r"\b[A-Z]\.\s?[A-Z][a-z]+,?\s+(?:and\s+)?", line) and line.count(",") >= 2)


def _classify_spacy(value: str, label: str, start: int) -> Detection | None:
    tokens = value.split()
    if not tokens or any(_is_tech(t) for t in tokens):
        return None
    if all(t.lower().strip(".,") in HEADING_WORDS for t in tokens):
        return None
    if any(t.strip(".,").upper() in INSTITUTION_ABBRS for t in tokens):
        return None  # "NIT Trichy" is a college, not a person
    if label == "PERSON":
        # one-word PERSON hits on resumes are mostly event or product names ("Techfest")
        if len(tokens) >= 2 and _looks_like_name(value) and not any(t.lower().strip(".,") in COMMON_WORDS | ACTION_VERBS for t in tokens):
            return Detection(value, "name", start, start + len(value), "spacy")
        return None
    if any(ch.isdigit() for ch in value) or len(value) < 3 or not value[0].isupper():
        return None
    if label != "ORG" and value.lower() in COUNTRIES:
        return None  # "across India" identifies nobody; hiding it only hurts readability
    category = "organization" if label == "ORG" else "location"
    return Detection(value, category, start, start + len(value), "spacy")


def _propagate_names(text: str, detections: list[Detection]) -> list[Detection]:
    """If "Asha Reddy" is a name, also catch "ASHA REDDY", "Asha" or "Reddy" elsewhere."""
    tokens: set[str] = set()
    for d in detections:
        # only trusted sources: spreading a wrong spaCy guess would hide ordinary words everywhere
        if d.category == "name" and d.source in ("heuristic", "label"):
            for tok in d.text.split():
                bare = tok.strip(".,'\u2019")
                if len(bare) >= 3 and bare.lower() not in HEADING_WORDS and not _is_tech(bare):
                    tokens.add(bare)
    out: list[Detection] = []
    for tok in tokens:
        for variant in {tok.title(), tok.upper(), tok}:
            for m in re.finditer(rf"(?<![\w@.]){re.escape(variant)}(?![\w@])", text):
                out.append(Detection(m.group(0), "name", m.start(), m.end(), "propagated"))
    return out


def _name_handles(text: str, detections: list[Detection]) -> list[Detection]:
    """Usernames built from the candidate's name: "AshaRao", "asha.rao", "asharao42".

    Icon-based contact lines (a LinkedIn or GitHub logo followed by a username) carry no keyword
    like "linkedin", so the username itself is what has to be recognised."""
    tokens = set()
    for d in detections:
        if d.category == "name" and d.source in ("heuristic", "label"):
            for tok in d.text.split():
                bare = tok.strip(".,'’").lower()
                if len(bare) >= 4 and bare.isalpha() and bare not in HEADING_WORDS:
                    tokens.add(bare)
    if not tokens:
        return []
    pattern = re.compile(
        # an optional leading "@" catches social handles such as "@debarghya_das"
        r"(?<![\w@./-])@?[A-Za-z0-9._\-]*(?:" + "|".join(map(re.escape, sorted(tokens))) + r")[A-Za-z0-9._\-]*(?![\w@])",
        re.IGNORECASE,
    )
    out = []
    for m in pattern.finditer(text):
        word = m.group(0).strip("._-")
        if word.lower() in tokens:
            continue  # the plain name itself is handled by the name detectors
        start = m.start() + m.group(0).find(word)
        out.append(Detection(word, "url", start, start + len(word), "handle"))
    return out


# --------------------------------------------------------------------------- resolution


def _resolve_overlaps(detections: list[Detection]) -> list[Detection]:
    """Keep the highest-priority (then longest) detection wherever spans overlap."""
    ranked = sorted(detections, key=lambda d: (-d.priority, -(d.end - d.start), d.start))
    kept: list[Detection] = []
    taken: list[tuple[int, int]] = []
    for d in ranked:
        if d.end <= d.start:
            continue
        if any(d.start < e and s < d.end for s, e in taken):
            continue
        kept.append(d)
        taken.append((d.start, d.end))
    return sorted(kept, key=lambda d: d.start)


def normalize_term(term: str) -> str:
    return " ".join(term.split()).lower()


def term_regex(term: str) -> str:
    parts = [re.escape(p) for p in term.split()]
    body = r"\s+".join(parts)
    pre = r"(?<![\w@])" if term[:1].isalnum() else ""
    post = r"(?![\w@])" if term[-1:].isalnum() else ""
    return pre + body + post


def build_matcher(terms: list[str]) -> re.Pattern | None:
    uniq = sorted({t.strip() for t in terms if t.strip()}, key=len, reverse=True)
    if not uniq:
        return None
    return re.compile("|".join(f"(?:{term_regex(t)})" for t in uniq), re.IGNORECASE)


def detect_pii(text: str) -> list[Finding]:
    detections = _regex_detections(text) + _header_name(text) + _spacy_detections(text)
    detections += _propagate_names(text, detections)
    detections += _name_handles(text, detections)
    resolved = _resolve_overlaps(detections)

    # collapse to unique terms; a term keeps the category of its highest-priority detection
    findings: dict[str, Finding] = {}
    sources: dict[str, set[str]] = {}
    for d in sorted(resolved, key=lambda d: -d.priority):
        key = normalize_term(d.text)
        if key not in findings:
            findings[key] = Finding(
                id=f"f{len(findings) + 1}",
                text=" ".join(d.text.split()),
                category=d.category,
                default_selected=CATEGORIES[d.category]["default"],
            )
            sources[key] = set()
        sources[key].add(d.source)

    # Locate every occurrence so the preview shows exactly what redaction will touch. Occurrences
    # of different findings may overlap ("Hyderabad" inside a college name); the client resolves
    # that based on which findings are selected, the same way the redactor does.
    for f in findings.values():
        f.sources = sorted(sources[normalize_term(f.text)])
        f.occurrences = [(m.start(), m.end()) for m in re.finditer(term_regex(f.text), text, re.IGNORECASE)]

    result = [f for f in findings.values() if f.occurrences]
    order = list(CATEGORIES)
    result.sort(key=lambda f: (order.index(f.category), f.occurrences[0][0]))
    for i, f in enumerate(result, 1):
        f.id = f"f{i}"
    return result
