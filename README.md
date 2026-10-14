# AI Resume De-Identifier

A blind-screening tool for HR. Each resume becomes a **blind profile** that shows only the
professional content: summary, skills, experience, projects, education, certifications and
achievements. The candidate's name, contact details, photo, personal-details section, age and gender
clues are sealed. The reviewer decides on merit alone:

- **Accept**: the identity is revealed (name, email, phone, links, original resume) and the
  candidate moves to the next stage: Interview, then Offer, then Hired.
- **Reject**: the candidate's personal data and original file are permanently deleted. Only the
  anonymous profile and the decision are kept for the audit trail.

| Layer      | Tool                   | Purpose                                                       |
|------------|------------------------|---------------------------------------------------------------|
| Frontend   | React (Vite)           | Upload, candidate dashboard, blind review, accept/reject      |
| Processing | Python / FastAPI       | Extraction, detection, blind profile, decisions               |
| AI / NLP   | spaCy + regex          | Names and places (NER); emails, phones, IDs, dates (rules)    |
| Documents  | PyMuPDF + python-docx  | Read PDF and DOCX resumes; render the blind profile PDF       |
| Storage    | SQLite + Fernet        | Candidates; personal data encrypted until acceptance          |

## Running it

Requires Python 3.10+ and Node 18+.

```bash
# backend (one time)
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# frontend (one time)
cd ../frontend
npm install
npm run build
```

Start the app from the `backend` folder. It also serves the built frontend:

```bash
uvicorn app.main:app --port 8000
```

Open http://localhost:8000, go to **Add resumes**, and upload a file or click one of the synthetic
samples. Then open the candidate from **Candidates** to review it.

For frontend development with hot reload, run the backend as above, then run `npm run dev` in
`frontend` and open http://localhost:5173.

Run the tests from `backend`: `python -m pytest`

## How it works

```
Upload ─► Extract text ─► Detect PII ─► Split into sections ─► Blind profile ──► Reviewer
                                         keep: summary, skills,   (identity        │
                                         experience, projects,     encrypted)   Accept ─► identity revealed ─► Interview ─► Offer ─► Hired
                                         education, certs ...                   Reject ─► personal data deleted
                                         drop: contact header, personal
                                         details, declaration, hobbies,
                                         languages, references
```

1. **Extract** (`app/extract.py`): text from the PDF text layer or the DOCX paragraphs, tables,
   headers and footers.
2. **Detect** (`app/detect.py`): regex for emails, phones, URLs, Aadhaar/PAN-style IDs; labelled-field
   rules for `Date of Birth:`, `Gender:`, `Father's Name:`, `Address:` and so on; spaCy NER for names
   and places. Common resume vocabulary ("Machine Learning", "Isolation Forest", "Hindi") is never
   treated as a person's name.
3. **Blind profile** (`app/profile.py`): the resume is split at its section headings.
   - Only professional sections are kept. The header block (name and contact line) and the
     personal, declaration, hobbies, languages, references and extracurricular sections are dropped
     entirely, labels and all.
   - Inside kept sections, any remaining identifier is replaced with a **hidden** marker. Pronouns
     become neutral ("she presented to her mentor" becomes "they presented to their mentor").
   - College names and graduation years are hidden by default, because prestige and age are common
     sources of bias. Both can be switched off at upload. Work-experience dates stay visible.
   - A job headline such as "AI/ML Student | Python | Data Analytics" is kept.
4. **Store** (`app/store.py`): the blind profile is stored as plain JSON. The identity and original
   file are encrypted with Fernet (key in `backend/data/secret.key`, or the `DEIDENT_KEY` env var).
   The API never sends identity data to the browser before acceptance. Rejection erases it, with
   SQLite `secure_delete` on.
5. **Decide**: Accept or Reject, with an optional reason. Every action is written to the audit trail
   (uploaded, accepted or rejected, identity revealed, personal data deleted, stage changes,
   original downloaded).
6. **Share**: the blind profile can be downloaded as a PDF for an interview panel.

## API

| Method | Path                                  | Description                                           |
|--------|---------------------------------------|-------------------------------------------------------|
| POST   | `/api/candidates`                     | Upload a resume (+ `hide_institutions`, `hide_education_years`) → candidate code only |
| GET    | `/api/candidates`                     | List candidates (codes, headline, skills, status)     |
| GET    | `/api/candidates/{code}`              | Blind profile, status, audit trail; identity only if accepted |
| POST   | `/api/candidates/{code}/decision`     | `{"decision": "accept" \| "reject", "note": "..."}`   |
| POST   | `/api/candidates/{code}/stage`        | Move an accepted candidate: Interview, Offer, Hired, Closed |
| GET    | `/api/candidates/{code}/original`     | Original resume (accepted candidates only, else 403)  |
| GET    | `/api/candidates/{code}/blind.pdf`    | Blind profile as PDF                                  |
| DELETE | `/api/candidates/{code}`              | Erase the candidate record completely                 |
| POST   | `/api/analyze`, `/api/redact`         | Stateless utilities: detect PII / produce a redacted copy of a file in its original format |

## Evaluation

46 tests in `backend/tests/` run on synthetic resumes: a developer resume (PDF and DOCX, with a
photo, links and metadata) and a student template resume. They check that:

- the blind profile keeps exactly the professional sections, with skills, projects and experience intact;
- the contact header, personal details, declaration and languages never appear, labels included;
- "Machine Learning" and similar skills are not mistaken for names;
- the list and detail API responses contain no personal data before a decision, and the database
  holds none in plain text;
- accept reveals the identity and original file; reject deletes them; decisions are final;
- duplicate uploads are detected, and the blind PDF contains no personal data.

## Known limitations

- **Section detection relies on headings.** Unusual headings fall back to an "Other" section, which is
  still scrubbed. If no headings are found at all, the profile shows a warning.
- **Scanned PDFs** need OCR (for example Tesseract) before text can be read.
- **NER is imperfect.** `en_core_web_sm` can miss unusual names inside the text. Names in the
  header and labelled fields are removed anyway, because those whole blocks are dropped.
- **Indirect clues** such as a women's college, community organisations or project links that include
  a GitHub username need human judgement. Links are hidden by default.
- **No login yet.** In production the uploader and reviewer should be separate authenticated roles,
  so the reviewer cannot see the original file before deciding.
