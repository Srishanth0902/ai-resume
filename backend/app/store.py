"""Candidate storage (SQLite).

The blind profile is stored as plain JSON because it holds no personal data. The candidate's
identity and the original resume file are encrypted with Fernet (AES-128 + HMAC) and only
decrypted after the reviewer accepts the candidate. Rejecting a candidate deletes both.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

ON_VERCEL = bool(os.environ.get("VERCEL"))
# Vercel functions can only write to /tmp, which is per-instance and temporary.
_default_dir = Path("/tmp/deident-data") if ON_VERCEL else Path(__file__).resolve().parents[1] / "data"
_data_dir = Path(os.environ.get("DEIDENT_DATA_DIR", _default_dir))

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    code          TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'screening',   -- screening | accepted | rejected
    stage         TEXT NOT NULL DEFAULT 'Blind screening',
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    note          TEXT,
    kind          TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    profile_json  TEXT NOT NULL,
    identity_enc  BLOB,
    original_enc  BLOB,
    filename_enc  BLOB
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    code    TEXT NOT NULL,
    at      TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT
);
"""


class NotFound(LookupError):
    pass


class InvalidState(ValueError):
    pass


def configure(data_dir: str | Path) -> None:
    global _data_dir
    _data_dir = Path(data_dir)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    _data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_data_dir / "candidates.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA secure_delete = ON")  # overwrite erased personal data instead of leaving free pages
    conn.executescript(SCHEMA)
    return conn


def _fernet() -> Fernet:
    key = os.environ.get("DEIDENT_KEY")
    if not key and ON_VERCEL:
        # a key generated per instance could not decrypt data written by another instance
        raise RuntimeError("Set the DEIDENT_KEY environment variable (a Fernet key) in the Vercel project.")
    if not key:
        key_file = _data_dir / "secret.key"
        _data_dir.mkdir(parents=True, exist_ok=True)
        if not key_file.exists():
            key_file.write_bytes(Fernet.generate_key())
        key = key_file.read_bytes()
    return Fernet(key)


def _enc(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def _dec(token: bytes) -> bytes:
    return _fernet().decrypt(token)


def _event(conn, code: str, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO events (code, at, action, detail) VALUES (?, ?, ?, ?)", (code, _now(), action, detail))


def _new_code(conn) -> str:
    while True:
        code = "CAND-" + secrets.token_hex(2).upper()
        if not conn.execute("SELECT 1 FROM candidates WHERE code = ?", (code,)).fetchone():
            return code


def find_duplicate(data: bytes) -> str | None:
    digest = hashlib.sha256(data).hexdigest()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT code FROM candidates WHERE file_hash = ?", (digest,)).fetchone()
        return row["code"] if row else None


def create(profile: dict, identity: dict, original: bytes, filename: str, kind: str) -> str:
    with closing(_connect()) as conn, conn:
        code = _new_code(conn)
        conn.execute(
            "INSERT INTO candidates (code, created_at, kind, file_hash, profile_json, identity_enc, original_enc,"
            " filename_enc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code, _now(), kind, hashlib.sha256(original).hexdigest(), json.dumps(profile),
                _enc(json.dumps(identity).encode()), _enc(original), _enc(filename.encode()),
            ),
        )
        _event(conn, code, "uploaded", "Resume received; personal details sealed")
        return code


def _row(conn, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM candidates WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise NotFound(code)
    return row


def _public(row: sqlite3.Row, with_profile: bool = True) -> dict:
    profile = json.loads(row["profile_json"])
    out = {
        "code": row["code"],
        "status": row["status"],
        "stage": row["stage"],
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
        "note": row["note"],
        "kind": row["kind"],
        "headline": profile.get("headline", ""),
        "skills": profile.get("skills", [])[:8],
    }
    if with_profile:
        out["profile"] = profile
    # identity is only ever decrypted for accepted candidates
    if row["status"] == "accepted" and row["identity_enc"]:
        identity = json.loads(_dec(row["identity_enc"]))
        out["identity"] = identity if with_profile else {"name": identity.get("name", "")}
    return out


def list_candidates() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM candidates ORDER BY created_at DESC").fetchall()
        return [_public(r, with_profile=False) for r in rows]


def get(code: str) -> dict:
    with closing(_connect()) as conn:
        row = _row(conn, code)
        out = _public(row)
        out["events"] = [
            dict(e) for e in conn.execute("SELECT at, action, detail FROM events WHERE code = ? ORDER BY id", (code,))
        ]
        return out


def decide(code: str, decision: str, note: str = "") -> dict:
    with closing(_connect()) as conn, conn:
        row = _row(conn, code)
        if row["status"] != "screening":
            raise InvalidState(f"{code} has already been {row['status']}.")
        note = note.strip()[:1000]
        if decision == "accept":
            conn.execute(
                "UPDATE candidates SET status='accepted', stage='Interview', decided_at=?, note=? WHERE code=?",
                (_now(), note, code),
            )
            _event(conn, code, "accepted", note or "Accepted on blind profile")
            _event(conn, code, "identity revealed", "Contact details unsealed for the next stage")
        elif decision == "reject":
            conn.execute(
                "UPDATE candidates SET status='rejected', stage='Closed', decided_at=?, note=?,"
                " identity_enc=NULL, original_enc=NULL, filename_enc=NULL WHERE code=?",
                (_now(), note, code),
            )
            _event(conn, code, "rejected", note or "Rejected on blind profile")
            _event(conn, code, "personal data deleted", "Identity and original file permanently erased")
        else:
            raise InvalidState("Decision must be 'accept' or 'reject'.")
    return get(code)


STAGES = ["Interview", "Offer", "Hired", "Closed"]


def set_stage(code: str, stage: str) -> dict:
    if stage not in STAGES:
        raise InvalidState(f"Stage must be one of {', '.join(STAGES)}.")
    with closing(_connect()) as conn, conn:
        row = _row(conn, code)
        if row["status"] != "accepted":
            raise InvalidState("Only accepted candidates move through later stages.")
        conn.execute("UPDATE candidates SET stage=? WHERE code=?", (stage, code))
        _event(conn, code, "stage changed", stage)
    return get(code)


def original(code: str) -> tuple[bytes, str, str]:
    with closing(_connect()) as conn, conn:
        row = _row(conn, code)
        if row["status"] != "accepted" or not row["original_enc"]:
            raise InvalidState("The original resume is only available after the candidate is accepted.")
        _event(conn, code, "original downloaded")
        return _dec(row["original_enc"]), _dec(row["filename_enc"]).decode(), row["kind"]


def delete(code: str) -> None:
    with closing(_connect()) as conn, conn:
        _row(conn, code)
        conn.execute("DELETE FROM candidates WHERE code = ?", (code,))
        conn.execute("DELETE FROM events WHERE code = ?", (code,))
