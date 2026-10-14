import { useCallback, useEffect, useState } from "react";
import { listCandidates } from "./api.js";
import AddResumes from "./components/AddResumes.jsx";
import CandidateList from "./components/CandidateList.jsx";
import CandidateDetail from "./components/CandidateDetail.jsx";

function useHashRoute() {
  const read = () => window.location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setRoute(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export default function App() {
  const route = useHashRoute();
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("screening");

  const refresh = useCallback(() => {
    listCandidates()
      .then((c) => {
        setCandidates(c);
        setError("");
      })
      .catch(() => setError("Cannot reach the backend. Is the API running on port 8000?"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(refresh, [refresh]);

  const detail = route.match(/^\/c\/([\w-]+)$/);
  const pending = candidates.filter((c) => c.status === "screening").length;

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="bar" aria-hidden />
          <span>AI Resume De-Identifier</span>
        </a>
        <nav>
          <a href="#/" className={route === "/" || detail ? "active" : ""}>
            Candidates{pending > 0 && <span className="nav-count">{pending}</span>}
          </a>
          <a href="#/add" className={route === "/add" ? "active" : ""}>Add resumes</a>
        </nav>
      </header>

      {error && <p className="error banner">{error}</p>}

      <main>
        {route === "/add" ? (
          <AddResumes onAdded={refresh} />
        ) : detail ? (
          <CandidateDetail code={detail[1]} onChanged={refresh} />
        ) : (
          <CandidateList candidates={candidates} tab={tab} setTab={setTab} loading={loading} />
        )}
      </main>

      <p className="privacy">
        Personal details are encrypted and stay sealed until a candidate is accepted. Rejected candidates' personal data is permanently deleted.
      </p>
    </div>
  );
}
