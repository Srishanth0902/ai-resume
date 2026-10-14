import { useRef, useState } from "react";
import { uploadResume } from "../api.js";

const ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const SAMPLES = [
  ["sample_resume_asha_reddy.pdf", "Developer (PDF)"],
  ["sample_resume_asha_reddy.docx", "Developer (DOCX)"],
  ["sample_resume_student_template.pdf", "Student template (PDF)"],
];

export default function AddResumes({ onAdded }) {
  const input = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState([]);
  const [options, setOptions] = useState({ hide_institutions: true, hide_education_years: true });

  async function process(files) {
    setBusy(true);
    for (const file of files) {
      const id = `${file.name}-${Date.now()}-${Math.random()}`;
      setResults((r) => [{ id, file: file.name, state: "working" }, ...r]);
      try {
        const res = await uploadResume(file, options);
        setResults((r) => r.map((x) => (x.id === id ? { ...x, state: "done", ...res } : x)));
        onAdded();
      } catch (e) {
        setResults((r) => r.map((x) => (x.id === id ? { ...x, state: "error", error: e.message } : x)));
      }
    }
    setBusy(false);
  }

  const loadSample = async (name) => {
    const blob = await (await fetch(`/samples/${name}`)).blob();
    process([new File([blob], name, { type: blob.type })]);
  };

  return (
    <section className="page narrow">
      <h1>Add resumes</h1>
      <p className="lead">
        Each resume becomes a <b>blind profile</b> showing only skills, experience, projects and education.
        Name, contact details, photo, age and gender clues are sealed and encrypted until a reviewer accepts the candidate.
      </p>

      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onClick={() => input.current.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          process([...e.dataTransfer.files]);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current.click()}
      >
        <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => process([...e.target.files])} />
        <div className="drop-icon" aria-hidden>
          <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
            <path d="M14 3v5h5M12 17v-6M9.5 13.5 12 11l2.5 2.5" />
          </svg>
        </div>
        <p className="drop-title">{busy ? "Processing..." : "Drop resumes here or click to browse"}</p>
        <p className="muted">PDF or DOCX, up to 10 MB each. You can select several files.</p>
      </div>

      <div className="options">
        <label>
          <input type="checkbox" checked={options.hide_institutions} onChange={(e) => setOptions({ ...options, hide_institutions: e.target.checked })} />
          Hide college and university names <span className="muted">(avoids bias towards prestigious institutions)</span>
        </label>
        <label>
          <input type="checkbox" checked={options.hide_education_years} onChange={(e) => setOptions({ ...options, hide_education_years: e.target.checked })} />
          Hide graduation years <span className="muted">(they reveal age; work experience dates stay visible)</span>
        </label>
      </div>

      <p className="samples muted">
        No resume handy? Add a synthetic sample:{" "}
        {SAMPLES.map(([file, label], i) => (
          <span key={file}>
            {i > 0 && " · "}
            <button className="link" disabled={busy} onClick={() => loadSample(file)}>{label}</button>
          </span>
        ))}
      </p>

      {results.length > 0 && (
        <ul className="upload-results">
          {results.map((r) => (
            <li key={r.id} className={r.state}>
              <span className="file">{r.file}</span>
              {r.state === "working" && <span className="muted">Building blind profile...</span>}
              {r.state === "error" && <span className="error">{r.error}</span>}
              {r.state === "done" && (
                <span>
                  {r.duplicate ? "Already added as " : "Added as "}
                  <a href={`#/c/${r.code}`} className="code">{r.code}</a>
                  {r.warnings?.length > 0 && <span className="warn-text">{" · "}{r.warnings[0]}</span>}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
