import { formatDate } from "../api.js";

export const TABS = [
  { key: "screening", label: "Blind review" },
  { key: "accepted", label: "Accepted" },
  { key: "rejected", label: "Rejected" },
];

export default function CandidateList({ candidates, tab, setTab, loading }) {
  const shown = candidates.filter((c) => c.status === tab);

  return (
    <section className="page">
      <div className="page-head">
        <h1>Candidates</h1>
        <a className="btn primary" href="#/add">Add resumes</a>
      </div>

      <div className="tabs big" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
            <span className="tab-count">{candidates.filter((c) => c.status === t.key).length}</span>
          </button>
        ))}
      </div>

      {loading && <p className="muted">Loading...</p>}
      {!loading && shown.length === 0 && (
        <div className="empty">
          {tab === "screening" ? (
            <>
              <p>No candidates waiting for blind review.</p>
              <a className="btn" href="#/add">Add resumes</a>
            </>
          ) : (
            <p>No {tab} candidates yet.</p>
          )}
        </div>
      )}

      <div className="cards">
        {shown.map((c) => (
          <a key={c.code} className="card" href={`#/c/${c.code}`}>
            <div className="card-top">
              <span className="code">{c.code}</span>
              <span className={`badge ${c.status}`}>{c.status === "screening" ? "Awaiting decision" : c.stage}</span>
            </div>
            {c.identity?.name ? <p className="who">{c.identity.name}</p> : <p className="who sealed">Identity sealed</p>}
            {c.headline && <p className="headline">{c.headline}</p>}
            <div className="chips">
              {c.skills.slice(0, 6).map((s) => (
                <span key={s} className="chip">{s}</span>
              ))}
              {c.skills.length > 6 && <span className="chip more">+{c.skills.length - 6}</span>}
            </div>
            <p className="muted small">
              Added {formatDate(c.created_at)}
              {c.decided_at && ` · decided ${formatDate(c.decided_at)}`}
            </p>
          </a>
        ))}
      </div>
    </section>
  );
}
