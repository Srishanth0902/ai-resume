import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.detect import detect_pii
from app.main import app
from app.profile import ProfileOptions, build_profile, classify_heading

from .sample_resumes import KEEP, PII, make_docx, make_pdf

TEMPLATE = (Path(__file__).parent / "template_resume.txt").read_text(encoding="utf-8")
client = TestClient(app)
SAMPLE_PDF = make_pdf()  # generated once: PDF bytes include a timestamp


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DEIDENT_KEY", raising=False)
    store.configure(tmp_path)
    yield tmp_path


def profile_text(profile):
    return "\n".join([profile["headline"]] + [l for s in profile["sections"] for l in [s["title"]] + s["lines"]])


# --------------------------------------------------------------------------- blind profile


def test_template_resume_keeps_only_professional_sections():
    profile, identity = build_profile(TEMPLATE, detect_pii(TEMPLATE))
    keys = [s["key"] for s in profile["sections"]]
    assert keys == ["summary", "skills", "experience", "projects", "education", "certifications"]
    text = profile_text(profile)
    for gone in ["YOUR NAME", "youremail@example.com", "XXXXX", "LinkedIn", "City, India", "Hindi", "declare"]:
        assert gone not in text
    # "Machine Learning" is a skill, not a person
    assert text.count("Machine Learning") >= 3
    assert "Machine Learning Fundamentals" in profile["skills"]
    assert "they presented results to their faculty mentor" in text
    assert "2022" not in text and "2026" not in text            # graduation years hidden (age clue)
    assert profile["headline"] == "AI/ML STUDENT | PYTHON | DATA ANALYTICS"
    assert set(profile["hidden"]["sections"]) == {"Languages", "Declaration"}
    assert identity["emails"] == ["youremail@example.com"]


@pytest.mark.parametrize("kind,maker", [("pdf", make_pdf), ("docx", make_docx)])
def test_sample_profile_hides_identity_and_keeps_qualifications(kind, maker):
    from app.extract import extract

    text = extract(maker(), kind).text
    profile, identity = build_profile(text, detect_pii(text))
    shown = profile_text(profile).lower()
    for value in PII + ["Personal Details", "Date of Birth", "Gender", "Email", "Phone"]:
        assert value.lower() not in shown, f"{value!r} leaked into the blind profile"
    for value in KEEP:
        assert value.lower() in shown, f"{value!r} missing from the blind profile"
    assert "jawaharlal nehru" not in shown                       # college name hidden by default
    assert "jun 2023 - dec 2023" in shown                        # experience dates are kept
    assert identity["name"].lower() == "asha reddy"
    assert "+91 90000 00000" in identity["phones"]


def test_institution_and_year_hiding_can_be_switched_off():
    text = "Jane Roe\nEDUCATION\nB.Sc Physics, Example College of Science, 2019 - 2022\nSKILLS\nPython"
    profile, _ = build_profile(text, detect_pii(text), ProfileOptions(hide_institutions=False, hide_education_years=False))
    assert "Example College of Science, 2019 - 2022" in profile_text(profile)


@pytest.mark.parametrize(
    "line, key",
    [("PROFESSIONAL SUMMARY", "summary"), ("Work Experience:", "experience"), ("Skills: Python, SQL", "skills"),
     ("Personal Details", "personal"), ("HOBBIES & INTERESTS", "hobbies"), ("LEADERSHIP", "other"),
     ("FAMILY DETAILS", "personal")],
)
def test_heading_classification(line, key):
    assert classify_heading(line)[0] == key


@pytest.mark.parametrize("line", ["Sales dashboard - Interactive analytics", "Software Intern, Nimbus Analytics", "Python"])
def test_content_lines_are_not_headings(line):
    assert classify_heading(line) is None


# --------------------------------------------------------------------------- HR workflow API


def upload(data=None, name="resume.pdf"):
    res = client.post("/api/candidates", files={"file": (name, data or SAMPLE_PDF)})
    assert res.status_code == 201, res.text
    return res.json()


def test_no_personal_data_reaches_the_reviewer_before_a_decision():
    code = upload()["code"]
    listing = client.get("/api/candidates").text.lower()
    detail = client.get(f"/api/candidates/{code}").text.lower()
    for value in ["asha", "reddy", "example.com", "90000", "linkedin", "14/08/2002", "female"]:
        assert value not in listing and value not in detail
    assert client.get(f"/api/candidates/{code}/original").status_code == 403
    assert "identity" not in client.get(f"/api/candidates/{code}").json()


def test_personal_data_is_encrypted_at_rest(isolated_store):
    upload()
    # full values only: short strings like "asha" can occur by chance inside base64 ciphertext
    raw = (isolated_store / "candidates.db").read_bytes()
    for value in [b"ASHA REDDY", b"Asha Reddy", b"asha.reddy@example.com", b"+91 90000 00000", b"14/08/2002"]:
        assert value not in raw


def test_accept_reveals_identity_and_moves_to_interview():
    code = upload()["code"]
    res = client.post(f"/api/candidates/{code}/decision", json={"decision": "accept", "note": "Strong projects"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted" and body["stage"] == "Interview"
    assert body["identity"]["name"].lower() == "asha reddy"
    assert "asha.reddy@example.com" in body["identity"]["emails"]
    assert [e["action"] for e in body["events"]] == ["uploaded", "accepted", "identity revealed"]

    original = client.get(f"/api/candidates/{code}/original")
    assert original.status_code == 200 and original.content == SAMPLE_PDF
    assert client.post(f"/api/candidates/{code}/stage", json={"stage": "Offer"}).json()["stage"] == "Offer"
    # a decision is final
    assert client.post(f"/api/candidates/{code}/decision", json={"decision": "reject"}).status_code == 409


def test_reject_permanently_deletes_personal_data(isolated_store):
    code = upload()["code"]
    body = client.post(f"/api/candidates/{code}/decision", json={"decision": "reject"}).json()
    assert body["status"] == "rejected" and "identity" not in body
    assert body["profile"]["skills"]                              # blind profile kept for the audit trail
    assert client.get(f"/api/candidates/{code}/original").status_code == 403
    import sqlite3
    row = sqlite3.connect(isolated_store / "candidates.db").execute(
        "SELECT identity_enc, original_enc, filename_enc FROM candidates WHERE code = ?", (code,)).fetchone()
    assert row == (None, None, None)


def test_duplicate_upload_returns_existing_candidate():
    first = upload()
    second = upload()
    assert second == {"code": first["code"], "duplicate": True}


def test_docx_upload_and_blind_pdf():
    code = upload(make_docx(), "cv.docx")["code"]
    pdf = client.get(f"/api/candidates/{code}/blind.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    import pymupdf
    text = pymupdf.open(stream=pdf.content, filetype="pdf")[0].get_text().lower()
    assert "python" in text and "asha" not in text and "example.com" not in text


def test_unknown_candidate_is_404():
    assert client.get("/api/candidates/CAND-0000").status_code == 404
    assert client.post("/api/candidates/CAND-0000/decision", json={"decision": "accept"}).status_code == 404


def test_wrapped_pdf_lines_are_joined_into_one_paragraph():
    from .sample_resumes import make_template_pdf
    from app.extract import extract

    text = extract(make_template_pdf(), "pdf").text
    profile, identity = build_profile(text, detect_pii(text))
    summary = next(s for s in profile["sections"] if s["key"] == "summary")
    assert len(summary["lines"]) == 1 and summary["lines"][0].endswith("collaborative projects.")
    assert identity["name"] == "YOUR NAME".title()


def test_vercel_mode_requires_an_encryption_key(monkeypatch):
    monkeypatch.setattr(store, "ON_VERCEL", True)
    res = client.post("/api/candidates", files={"file": ("resume.pdf", SAMPLE_PDF)})
    assert res.status_code == 503 and "DEIDENT_KEY" in res.json()["detail"]
