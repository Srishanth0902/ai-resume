"""FastAPI service for the AI Resume De-Identifier.

HR workflow:
  upload resume -> blind profile (skills, experience, projects ...) -> reviewer accepts or rejects
  -> accept: identity is revealed and the candidate moves to the interview stage
  -> reject: personal data and the original file are permanently deleted

Privacy approach: personal details are encrypted at rest and never sent to the browser before a
decision. The /api/analyze and /api/redact utilities work purely in memory and store nothing.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import blind_pdf, store
from .detect import CATEGORIES, build_matcher, detect_pii, nlp_available
from .extract import UnsupportedFile, detect_kind, extract
from .profile import ProfileOptions, build_profile
from .redact import RedactItem, redact_document, redact_text, split_terms

MAX_BYTES = 10 * 1024 * 1024
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

app = FastAPI(title="AI Resume De-Identifier", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class ItemIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    category: str


class RedactOptions(BaseModel):
    items: list[ItemIn] = Field(default_factory=list, max_length=2000)
    remove_photos: bool = True
    label_style: Literal["removed", "category"] = "removed"


def _read(file: UploadFile) -> tuple[bytes, str]:
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 10 MB.")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    try:
        return data, detect_kind(file.filename or "", data)
    except UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok", "nlp_model": "en_core_web_sm" if nlp_available() else None}


@app.get("/api/categories")
def categories():
    return [{"key": k, "label": v["label"], "tag": v["tag"], "default": v["default"]} for k, v in CATEGORIES.items()]


@app.post("/api/analyze")
def analyze(file: UploadFile = File(...)):
    data, kind = _read(file)
    try:
        extraction = extract(data, kind)
    except UnsupportedFile as exc:
        raise HTTPException(422, str(exc)) from exc

    warnings = list(extraction.warnings)
    if not nlp_available():
        warnings.append("spaCy model not installed: name detection is limited to rule-based heuristics.")
    findings = detect_pii(extraction.text)
    return {
        "filename": file.filename,
        "kind": kind,
        "page_count": extraction.page_count,
        "image_count": extraction.image_count,
        "text": extraction.text,
        "warnings": warnings,
        "findings": [
            {
                "id": f.id,
                "text": f.text,
                "category": f.category,
                "sources": f.sources,
                "default_selected": f.default_selected,
                "occurrences": f.occurrences,
            }
            for f in findings
        ],
    }


@app.post("/api/redact")
def redact(file: UploadFile = File(...), options: str = Form("{}")):
    data, kind = _read(file)
    try:
        opts = RedactOptions.model_validate_json(options)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid options: {exc.errors()[0]['msg']}") from exc
    unknown = {i.category for i in opts.items} - set(CATEGORIES)
    if unknown:
        raise HTTPException(422, f"Unknown categories: {', '.join(sorted(unknown))}")

    items = [RedactItem(i.text, i.category) for i in opts.items]
    try:
        output, stats = redact_document(data, kind, items, opts.label_style, opts.remove_photos)
    except Exception as exc:
        raise HTTPException(422, f"Could not anonymise this document: {exc}") from exc

    # Validation: read the generated file back and look for anything that should be gone.
    out_text = extract(output, kind).text
    matcher = build_matcher([i.text for i in split_terms(items)])
    residual = sorted({" ".join(m.group(0).split()) for m in matcher.finditer(out_text)}) if matcher else []

    stem = Path(file.filename or "resume").stem
    return {
        "filename": f"{stem}_anonymized.{kind}",
        "media_type": MEDIA_TYPES[kind],
        "file_base64": base64.b64encode(output).decode(),
        "stats": stats.__dict__,
        "output_text": out_text,
        "expected_text": redact_text(extract(data, kind).text, items, opts.label_style),
        "residual": residual,
    }


# --------------------------------------------------------------------------- HR candidate workflow


class Decision(BaseModel):
    decision: Literal["accept", "reject"]
    note: str = Field(default="", max_length=1000)


class StageIn(BaseModel):
    stage: str


def _candidate_or_404(code: str) -> dict:
    try:
        return store.get(code)
    except store.NotFound as exc:
        raise HTTPException(404, f"Candidate {code} not found.") from exc


@app.post("/api/candidates", status_code=201)
def add_candidate(
    file: UploadFile = File(...),
    hide_institutions: bool = Form(True),
    hide_education_years: bool = Form(True),
):
    data, kind = _read(file)
    duplicate = store.find_duplicate(data)
    if duplicate:
        return {"code": duplicate, "duplicate": True}
    try:
        extraction = extract(data, kind)
    except UnsupportedFile as exc:
        raise HTTPException(422, str(exc)) from exc
    if not extraction.text.strip():
        raise HTTPException(422, extraction.warnings[0] if extraction.warnings else "No text found in the file.")

    findings = detect_pii(extraction.text)
    options = ProfileOptions(hide_institutions=hide_institutions, hide_education_years=hide_education_years)
    profile, identity = build_profile(extraction.text, findings, options, extraction.image_count)
    code = store.create(profile, identity, data, file.filename or f"resume.{kind}", kind)
    # Only the code goes back: the uploader's screen never displays who the candidate is.
    return {"code": code, "duplicate": False, "sections": len(profile["sections"]), "warnings": profile["warnings"]}


@app.get("/api/candidates")
def list_candidates():
    return store.list_candidates()


@app.get("/api/candidates/{code}")
def get_candidate(code: str):
    return _candidate_or_404(code)


@app.post("/api/candidates/{code}/decision")
def decide(code: str, body: Decision):
    _candidate_or_404(code)
    try:
        return store.decide(code, body.decision, body.note)
    except store.InvalidState as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/candidates/{code}/stage")
def set_stage(code: str, body: StageIn):
    _candidate_or_404(code)
    try:
        return store.set_stage(code, body.stage)
    except store.InvalidState as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/candidates/{code}/original")
def download_original(code: str):
    _candidate_or_404(code)
    try:
        data, filename, kind = store.original(code)
    except store.InvalidState as exc:
        raise HTTPException(403, str(exc)) from exc
    return Response(data, media_type=MEDIA_TYPES[kind],
                    headers={"Content-Disposition": f'attachment; filename="{Path(filename).name}"'})


@app.get("/api/candidates/{code}/blind.pdf")
def download_blind_profile(code: str):
    candidate = _candidate_or_404(code)
    return Response(blind_pdf.render(code, candidate["profile"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{code}_blind_profile.pdf"'})


@app.delete("/api/candidates/{code}", status_code=204)
def delete_candidate(code: str):
    _candidate_or_404(code)
    store.delete(code)


@app.middleware("http")
async def no_store_html(request, call_next):
    response = await call_next(request)
    # hashed /assets/ files can be cached; the page and API answers must always be fresh
    if not request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Serve the built React app when it exists, so the demo runs from a single server.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
