import { useEffect, useState } from "react";
import { blindPdfUrl, decide, deleteCandidate, formatDate, getCandidate, originalUrl, setStage } from "../api.js";

const PIPELINE = ["Blind screening", "Interview", "Offer", "Hired"];
const NEXT_STAGES = ["Interview", "Offer", "Hired", "Closed"];

function Line({ text }) {
  const bullet = /^[-•*●▪–]\s*/.test(text);
  const clean = bullet ? text.replace(/^[-•*●▪–]\s*/, "") : text;
  const parts = clean.split("[hidden]");
  return (
    <p className={bullet ? "line bullet" : "line"}>
      {parts.map((p, i) => (
        <span key={i}>
          {p}
          {i < parts.length - 1 && <span className="hidden-chip" title="Personal detail hidden for blind review">hidden</span>}
        </span>
      ))}
    </p>
  );
}

function Profile({ candidate }) {
  const { profile } = candidate;
  const hidden = profile.hidden;
  const hiddenList = [
    "name & contact details",
    hidden.photo && "photo",
    ...hidden.sections.map((s) => s.toLowerCase()),
    hidden.institutions && "college names",
    hidden.education_years && "graduation years",
  ].filter(Boolean);

  return (
    <article className="profile">
      <header className="profile-head">
        <p className="eyebrow">Blind profile</p>
        <h1>{candidate.code}</h1>
        {profile.headline && <p className="headline">{profile.headline}</p>}
      </header>

      <div className="hidden-note">
        <b>Hidden for unbiased review:</b> {hiddenList.join(", ")}
        {hidden.inline > 0 && `, plus ${hidden.inline} detail${hidden.inline === 1 ? "" : "s"} inside the text`}.
      </div>
      {profile.warnings.map((w) => (
        <div key={w} className="notice">{w}</div>
      ))}

      {profile.sections.map((s) => (
        <section key={s.title} className="profile-section">
          <h2>{s.title}</h2>
          {s.key === "skills" && profile.skills.length > 0 ? (
            <div className="chips">
              {profile.skills.map((k) => (
                <span key={k} className="chip">{k}</span>
              ))}
            </div>
          ) : (
            s.lines.map((l, i) => <Line key={i} text={l} />)
          )}
        </section>
      ))}
    </article>
  );
}

function Pipeline({ candidate }) {
  const rejected = candidate.status === "rejected";
  const current = rejected ? 0 : Math.max(0, PIPELINE.indexOf(candidate.stage));
  return (
    <ol className="pipeline">
      {PIPELINE.map((s, i) => {
        const state = rejected ? (i === 0 ? "rejected" : "todo") : i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={s} className={state}>
            <span className="dot" />
            {s}
          </li>
        );
      })}
      {(rejected || candidate.stage === "Closed") && <li className="rejected"><span className="dot" />Closed</li>}
    </ol>
  );
}

function DecisionPanel({ candidate, onDecided }) {
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      onDecided(await decide(candidate.code, confirm, note));
      setConfirm(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="side-card decision">
      <h3>Your decision</h3>
      <p className="muted small">Decide on skills and experience alone. The candidate's identity is revealed only if you accept.</p>
      <label className="note-label" htmlFor="note">Reason (optional, kept in the audit log)</label>
      <textarea id="note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Strong Python projects, relevant internship" />
      <div className="decision-buttons">
        <button className="btn danger" onClick={() => setConfirm("reject")}>Reject</button>
        <button className="btn primary" onClick={() => setConfirm("accept")}>Accept &amp; reveal identity</button>
      </div>
      {error && <p className="error">{error}</p>}

      {confirm && (
        <div className="modal" role="dialog" aria-modal="true">
          <div className="modal-card">
            {confirm === "accept" ? (
              <>
                <h3>Accept {candidate.code}?</h3>
                <p>The candidate's name, contact details and original resume will be revealed so you can schedule the <b>interview</b>. This decision is final and recorded.</p>
              </>
            ) : (
              <>
                <h3>Reject {candidate.code}?</h3>
                <p>The candidate's personal data and original resume will be <b>permanently deleted</b>. Only the anonymous profile and your decision are kept. This cannot be undone.</p>
              </>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setConfirm(null)} disabled={busy}>Cancel</button>
              <button className={`btn ${confirm === "accept" ? "primary" : "danger"}`} onClick={submit} disabled={busy}>
                {busy ? "Saving..." : confirm === "accept" ? "Accept & reveal" : "Reject & delete data"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function IdentityCard({ candidate, onChanged }) {
  const id = candidate.identity;
  const [busy, setBusy] = useState(false);
  const move = async (stage) => {
    setBusy(true);
    try {
      onChanged(await setStage(candidate.code, stage));
    } finally {
      setBusy(false);
    }
  };
  const link = (l) => (/^https?:\/\//.test(l) ? l : `https://${l}`);

  return (
    <div className="side-card identity">
      <p className="eyebrow ok">Identity revealed</p>
      <h3 className="name">{id.name || "Name not found"}</h3>
      <dl>
        {id.emails.map((e) => (
          <div key={e}><dt>Email</dt><dd><a href={`mailto:${e}`}>{e}</a></dd></div>
        ))}
        {id.phones.map((p) => (
          <div key={p}><dt>Phone</dt><dd><a href={`tel:${p.replace(/[^\d+]/g, "")}`}>{p}</a></dd></div>
        ))}
        {id.links.map((l) => (
          <div key={l}><dt>Link</dt><dd><a href={link(l)} target="_blank" rel="noreferrer">{l}</a></dd></div>
        ))}
        {id.locations.slice(0, 2).map((l) => (
          <div key={l}><dt>Location</dt><dd>{l}</dd></div>
        ))}
        {id.details.map((d) => (
          <div key={d.label + d.value}><dt>{d.label}</dt><dd>{d.value}</dd></div>
        ))}
      </dl>
      {id.hidden_sections.length > 0 && (
        <details>
          <summary>Sections hidden during review</summary>
          {id.hidden_sections.map((s) => (
            <div key={s.title} className="revealed-section">
              <b>{s.title}</b>
              {s.lines.map((l, i) => <p key={i}>{l}</p>)}
            </div>
          ))}
        </details>
      )}
      <a className="btn block" href={originalUrl(candidate.code)}>Download original resume</a>

      <div className="stage-move">
        <p className="muted small">Current stage: <b>{candidate.stage}</b>. Move to:</p>
        <div className="stage-buttons">
          {NEXT_STAGES.filter((s) => s !== candidate.stage).map((s) => (
            <button key={s} className="btn small" disabled={busy} onClick={() => move(s)}>{s}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function CandidateDetail({ code, onChanged }) {
  const [candidate, setCandidate] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setCandidate(null);
    getCandidate(code).then(setCandidate).catch((e) => setError(e.message));
  }, [code]);

  const update = (c) => {
    setCandidate(c);
    onChanged();
  };

  async function remove() {
    if (!window.confirm(`Delete ${code} and everything stored about this candidate?`)) return;
    await deleteCandidate(code);
    onChanged();
    window.location.hash = "#/";
  }

  if (error) return <section className="page"><a href="#/" className="back">&larr; Candidates</a><p className="error">{error}</p></section>;
  if (!candidate) return <section className="page"><p className="muted">Loading...</p></section>;

  return (
    <section className="page">
      <a href="#/" className="back">&larr; All candidates</a>
      <Pipeline candidate={candidate} />
      <div className="detail">
        <Profile candidate={candidate} />
        <aside className="side">
          {candidate.status === "screening" && <DecisionPanel candidate={candidate} onDecided={update} />}
          {candidate.status === "accepted" && <IdentityCard candidate={candidate} onChanged={update} />}
          {candidate.status === "rejected" && (
            <div className="side-card rejected">
              <h3>Rejected</h3>
              <p className="small">Decided {formatDate(candidate.decided_at)}. The candidate's personal data and original resume were permanently deleted.</p>
              {candidate.note && <p className="small"><b>Reason:</b> {candidate.note}</p>}
            </div>
          )}

          <div className="side-card">
            <h3>Share with interview panel</h3>
            <a className="btn block ghost" href={blindPdfUrl(candidate.code)}>Download blind profile (PDF)</a>
          </div>

          <div className="side-card">
            <h3>Audit trail</h3>
            <ol className="timeline">
              {candidate.events.map((e, i) => (
                <li key={i}>
                  <b>{e.action}</b>
                  <span className="muted small">{formatDate(e.at)}</span>
                  {e.detail && <span className="small">{e.detail}</span>}
                </li>
              ))}
            </ol>
            <button className="link danger-link" onClick={remove}>Delete candidate record</button>
          </div>
        </aside>
      </div>
    </section>
  );
}
