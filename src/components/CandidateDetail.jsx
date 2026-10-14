import { useEffect, useState } from "react";
import { blindPdfUrl, decide, deleteCandidate, formatDate, getCandidate, originalUrl, setStage } from "../api.js";

const PIPELINE = ["Blind screening", "Interview", "Offer", "Hired"];
const NEXT_STAGES = ["Interview", "Offer", "Hired", "Closed"];

const TOP_BULLET = /^[-•*●▪–]\s*/;
const SUB_BULLET = /^◦\s*/;
// a role/project title: ends with a date in brackets "(Jun 2025)" / "(Sep 2024 – Present)", or with ":"
const ENTRY_TITLE = /(\([^()]*(\d{4}|present|current)[^()]*\)|:)$/i;

function WithHidden({ text }) {
  const parts = text.split("[hidden]");
  return parts.map((p, i) => (
    <span key={i}>
      {p}
      {i < parts.length - 1 && <span className="hidden-chip" title="Personal detail hidden for blind review">hidden</span>}
    </span>
  ));
}

function Line({ text, nested, heads }) {
  let kind = "line";
  let clean = text;
  if (heads) {
    kind = "line entry"; // a plain line with bullet points under it is a project / role title
  } else if (SUB_BULLET.test(text)) {
    kind = "line bullet sub";
    clean = text.replace(SUB_BULLET, "");
  } else if (TOP_BULLET.test(text)) {
    clean = text.replace(TOP_BULLET, "");
    // when a section has sub-points, its top-level bullets are the entry titles they belong to
    kind = nested || ENTRY_TITLE.test(clean) ? "line entry" : "line bullet";
  } else if (ENTRY_TITLE.test(text) && text.length < 140) {
    kind = "line entry";
  }
  return (
    <p className={kind}>
      <WithHidden text={clean} />
    </p>
  );
}

const isTableRow = (l) => (l.match(/ \| /g) || []).length >= 2;
const SKILL_ROW = /^([A-Za-z][\w &/'’+.-]{1,30}?)\s*:\s*(.+)$/;
const splitSkills = (s) => s.split(/[,;|•·]/).map((x) => x.trim().replace(/\.$/, "")).filter(Boolean);

// "Languages: Python, C++" rows keep their labels; an unlabelled list becomes one cloud of chips
function SkillsBody({ lines, chips }) {
  const rows = lines.map((l) => l.replace(TOP_BULLET, "").replace(SUB_BULLET, "").match(SKILL_ROW));
  if (rows.filter(Boolean).length < 2) {
    return (
      <div className="chips">
        {chips.map((k) => <span key={k} className="chip">{k}</span>)}
      </div>
    );
  }
  return (
    <div className="skill-rows">
      {lines.map((l, i) => {
        const m = rows[i];
        const items = splitSkills(m ? m[2] : l.replace(TOP_BULLET, "").replace(SUB_BULLET, ""));
        return (
          <div key={i} className="skill-row">
            <span className="skill-label">{m ? m[1] : ""}</span>
            <div className="chips">
              {items.map((k, j) => <span key={j} className="chip"><WithHidden text={k} /></span>)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Table({ rows }) {
  const cells = rows.map((r) => r.split(" | "));
  const header = !/\d/.test(rows[0]) && cells.length > 1;
  const body = header ? cells.slice(1) : cells;
  return (
    <div className="table-wrap">
      <table>
        {header && (
          <thead>
            <tr>{cells[0].map((c, i) => <th key={i}>{c}</th>)}</tr>
          </thead>
        )}
        <tbody>
          {body.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}><WithHidden text={c} /></td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectionBody({ lines }) {
  const nested = lines.some((l) => SUB_BULLET.test(l));
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    if (isTableRow(lines[i])) {
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) rows.push(lines[i++]);
      i--;
      out.push(<Table key={`t${i}`} rows={rows} />);
    } else {
      const next = lines[i + 1] || "";
      const plain = !TOP_BULLET.test(lines[i]) && !SUB_BULLET.test(lines[i]);
      const heads = plain && lines[i].length < 160 && (TOP_BULLET.test(next) || SUB_BULLET.test(next));
      out.push(<Line key={i} text={lines[i]} nested={nested} heads={heads} />);
    }
  }
  return out;
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
            <SkillsBody lines={s.lines} chips={profile.skills} />
          ) : (
            <SectionBody lines={s.lines} />
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
