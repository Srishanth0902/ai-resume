"""Write the synthetic demo resumes to ../samples."""
from pathlib import Path

from tests.sample_resumes import make_docx, make_pdf, make_template_pdf

root = Path(__file__).resolve().parent.parent
# samples/ for people, frontend/public/samples/ for the "Try a sample" buttons in the UI
for out in (root / "samples", root / "frontend" / "public" / "samples"):
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample_resume_asha_reddy.pdf").write_bytes(make_pdf())
    (out / "sample_resume_asha_reddy.docx").write_bytes(make_docx())
    (out / "sample_resume_student_template.pdf").write_bytes(make_template_pdf())
    print(f"Wrote sample resumes to {out}")
