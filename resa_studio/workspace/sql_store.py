"""Workspace in a SQL database: SQLite (stdlib) or PostgreSQL (psycopg v3).

Tables resa_projects / resa_designs / resa_versions; config, kpis and
derived_from are JSON text. One short transaction per operation; a new
connection each time keeps it serverless-friendly (Vercel + Neon).
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .store import (
    DEFAULT_STATUS,
    Conflict,
    NotFound,
    WorkspaceStore,
    check_config,
    check_id,
    check_kpis,
    check_status,
    clean_author,
    clean_description,
    clean_message,
    clean_name,
    design_summary,
    now_iso,
    slugify,
    sort_designs,
    sort_projects,
    to_json,
    unique_id,
    version_full,
    version_summary,
)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS resa_projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS resa_designs (
        project_id TEXT NOT NULL REFERENCES resa_projects(id) ON DELETE CASCADE,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL,
        revision INTEGER NOT NULL,
        config TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        derived_from TEXT,
        is_baseline INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (project_id, id)
    )""",
    """CREATE TABLE IF NOT EXISTS resa_versions (
        project_id TEXT NOT NULL,
        design_id TEXT NOT NULL,
        number INTEGER NOT NULL,
        message TEXT NOT NULL,
        author TEXT NOT NULL,
        created_at TEXT NOT NULL,
        kpis TEXT NOT NULL,
        config TEXT NOT NULL,
        PRIMARY KEY (project_id, design_id, number),
        FOREIGN KEY (project_id, design_id) REFERENCES resa_designs(project_id, id) ON DELETE CASCADE
    )""",
)

_DESIGN_WITH_HEAD = """
    SELECT d.*, v.number AS head_number, v.kpis AS head_kpis, v.config AS head_config
    FROM resa_designs d
    LEFT JOIN resa_versions v
      ON v.project_id = d.project_id AND v.design_id = d.id
     AND v.number = (SELECT MAX(x.number) FROM resa_versions x
                     WHERE x.project_id = d.project_id AND x.design_id = d.id)
"""

_ID_RETRIES = 8


def _import_psycopg() -> Any:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "PostgreSQL workspace storage needs psycopg v3: pip install 'psycopg[binary]'"
        ) from exc
    return psycopg


class _Db:
    """Thin cursor wrapper: `?` placeholders everywhere, dict rows."""

    def __init__(self, conn: Any, dialect: str) -> None:
        self._conn = conn
        self.dialect = dialect
        self.for_update = " FOR UPDATE" if dialect == "postgres" else ""

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        return self._conn.execute(self._sql(sql), params).rowcount

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute(self._sql(sql), params).fetchall()]

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = self._conn.execute(self._sql(sql), params).fetchone()
        return dict(row) if row is not None else None


def _design_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "derived_from": json.loads(row["derived_from"]) if row.get("derived_from") else None,
        "is_baseline": bool(row["is_baseline"]),
    }


def _head(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("head_number") is None:
        return None
    return {"number": row["head_number"], "kpis": json.loads(row["head_kpis"]), "config": json.loads(row["head_config"])}


def _version(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "kpis": json.loads(row["kpis"]), "config": json.loads(row["config"])}


class SqlStore(WorkspaceStore):
    kind = "database"

    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self._path = url[len("sqlite:///"):]
            if not self._path or self._path == ":memory:":
                raise ValueError("sqlite workspace needs a file path: sqlite:///path/to/workspace.db")
        elif url.startswith(("postgresql://", "postgres://")):
            self.dialect = "postgres"
            self._path = ""
        else:
            raise ValueError("workspace database URL must be sqlite:///… or postgresql://…")
        self._url = url
        self._ready = False
        self._integrity_errors: tuple[type[BaseException], ...] = (sqlite3.IntegrityError,)

    @property
    def location(self) -> str:
        if self.dialect == "sqlite":
            return f"SQLite database ({Path(self._path).name})"
        return "PostgreSQL database"

    # ── connection / transactions ────────────────────────────────────────────

    @contextmanager
    def _connect(self, write: bool) -> Iterator[_Db]:
        if self.dialect == "sqlite":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys = ON")
                # IMMEDIATE takes the write lock up front, serializing writers
                # (unique version numbers, revision checks).
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    yield _Db(conn, "sqlite")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
            finally:
                conn.close()
        else:
            psycopg = _import_psycopg()
            from psycopg.rows import dict_row

            self._integrity_errors = (psycopg.IntegrityError,)
            # The connection context commits on success and rolls back on error.
            with psycopg.connect(self._url, row_factory=dict_row) as conn:
                yield _Db(conn, "postgres")

    @contextmanager
    def _tx(self, write: bool = False) -> Iterator[_Db]:
        if not self._ready:
            with self._connect(write=True) as db:
                for ddl in _SCHEMA:
                    db.run(ddl)
            self._ready = True
        with self._connect(write) as db:
            yield db

    # ── row helpers (inside a transaction) ───────────────────────────────────

    def _project_row(self, db: _Db, project_id: str, lock: bool = False) -> dict[str, Any]:
        row = db.one(
            "SELECT * FROM resa_projects WHERE id = ?" + (db.for_update if lock else ""),
            (check_id(project_id, "project id"),),
        )
        if row is None:
            raise NotFound(f"project not found: {project_id}")
        return row

    def _project(self, db: _Db, project_id: str) -> dict[str, Any]:
        row = self._project_row(db, project_id)
        count = db.one("SELECT COUNT(*) AS n FROM resa_designs WHERE project_id = ?", (project_id,))
        return {**row, "design_count": int(count["n"]) if count else 0}

    def _design_row(self, db: _Db, project_id: str, design_id: str, lock: bool = False) -> dict[str, Any]:
        check_id(design_id, "design id")
        row = db.one(
            "SELECT * FROM resa_designs WHERE project_id = ? AND id = ?" + (db.for_update if lock else ""),
            (check_id(project_id, "project id"), design_id),
        )
        if row is None:
            self._project_row(db, project_id)
            raise NotFound(f"design not found: {project_id}/{design_id}")
        return row

    def _design(self, db: _Db, project_id: str, design_id: str) -> dict[str, Any]:
        self._design_row(db, project_id, design_id)
        row = db.one(_DESIGN_WITH_HEAD + " WHERE d.project_id = ? AND d.id = ?", (project_id, design_id))
        assert row is not None
        config = json.loads(row["config"])
        return {**design_summary(project_id, _design_meta(row), config, _head(row)), "config": config}

    def _touch_project(self, db: _Db, project_id: str, now: str) -> None:
        db.run("UPDATE resa_projects SET updated_at = ? WHERE id = ?", (now, project_id))

    def _latest_version(self, db: _Db, project_id: str, design_id: str) -> dict[str, Any] | None:
        row = db.one(
            "SELECT * FROM resa_versions WHERE project_id = ? AND design_id = ? ORDER BY number DESC LIMIT 1",
            (project_id, design_id),
        )
        return _version(row) if row else None

    def _with_id_retry(self, fn: Any) -> Any:
        """Run *fn* in a fresh transaction, retrying when a concurrent insert took the id."""
        for attempt in range(_ID_RETRIES):
            try:
                with self._tx(write=True) as db:
                    return fn(db)
            except self._integrity_errors:
                if attempt == _ID_RETRIES - 1:
                    raise
        raise AssertionError("unreachable")

    def _new_project_id(self, db: _Db, name: str) -> str:
        taken = {r["id"] for r in db.all("SELECT id FROM resa_projects")}
        return unique_id(slugify(name), taken)

    def _insert_project(self, db: _Db, name: str, description: str, author: str, now: str) -> str:
        project_id = self._new_project_id(db, name)
        db.run(
            "INSERT INTO resa_projects (id, name, description, created_at, created_by, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, description, now, author, now),
        )
        return project_id

    def _insert_design_row(self, db: _Db, project_id: str, record: dict[str, Any]) -> None:
        db.run(
            "INSERT INTO resa_designs (project_id, id, name, description, status, revision, config,"
            " created_at, created_by, updated_at, updated_by, derived_from, is_baseline)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id, record["id"], record["name"], record["description"], record["status"],
                record["revision"], to_json(record["config"]), record["created_at"], record["created_by"],
                record["updated_at"], record["updated_by"],
                to_json(record["derived_from"]) if record["derived_from"] else None,
                1 if record["is_baseline"] else 0,
            ),
        )

    def _insert_version_row(self, db: _Db, project_id: str, design_id: str, version: dict[str, Any]) -> None:
        db.run(
            "INSERT INTO resa_versions (project_id, design_id, number, message, author, created_at, kpis, config)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id, design_id, version["number"], version["message"], version["author"],
                version["created_at"], to_json(version["kpis"]), to_json(version["config"]),
            ),
        )

    # ── projects ─────────────────────────────────────────────────────────────

    def list_projects(self) -> list[dict[str, Any]]:
        with self._tx() as db:
            rows = db.all(
                "SELECT p.*, (SELECT COUNT(*) FROM resa_designs d WHERE d.project_id = p.id) AS design_count"
                " FROM resa_projects p"
            )
        return sort_projects([{**r, "design_count": int(r["design_count"])} for r in rows])

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._tx() as db:
            return self._project(db, project_id)

    def create_project(self, name: str, description: str = "", author: str | None = None) -> dict[str, Any]:
        name, description, author = clean_name(name), clean_description(description), clean_author(author)

        def create(db: _Db) -> dict[str, Any]:
            project_id = self._insert_project(db, name, description, author, now_iso())
            return self._project(db, project_id)

        return self._with_id_retry(create)

    def update_project(
        self, project_id: str, *, name: str | None = None, description: str | None = None,
    ) -> dict[str, Any]:
        with self._tx(write=True) as db:
            row = self._project_row(db, project_id, lock=True)
            new_name = clean_name(name) if name is not None else row["name"]
            new_description = clean_description(description) if description is not None else row["description"]
            db.run(
                "UPDATE resa_projects SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (new_name, new_description, now_iso(), project_id),
            )
            return self._project(db, project_id)

    def delete_project(self, project_id: str) -> None:
        with self._tx(write=True) as db:
            self._project_row(db, project_id, lock=True)
            db.run("DELETE FROM resa_versions WHERE project_id = ?", (project_id,))
            db.run("DELETE FROM resa_designs WHERE project_id = ?", (project_id,))
            db.run("DELETE FROM resa_projects WHERE id = ?", (project_id,))

    # ── designs ──────────────────────────────────────────────────────────────

    def list_designs(self, project_id: str) -> list[dict[str, Any]]:
        with self._tx() as db:
            self._project_row(db, project_id)
            rows = db.all(_DESIGN_WITH_HEAD + " WHERE d.project_id = ?", (project_id,))
        return sort_designs([
            design_summary(project_id, _design_meta(r), json.loads(r["config"]), _head(r)) for r in rows
        ])

    def get_design(self, project_id: str, design_id: str) -> dict[str, Any]:
        with self._tx() as db:
            return self._design(db, project_id, design_id)

    def _insert_design(
        self,
        project_id: str,
        name: str,
        description: str,
        config: dict[str, Any],
        author: str,
        derived_from: dict[str, Any] | None,
    ) -> dict[str, Any]:
        def create(db: _Db) -> dict[str, Any]:
            self._project_row(db, project_id)
            taken = {r["id"] for r in db.all("SELECT id FROM resa_designs WHERE project_id = ?", (project_id,))}
            design_id = unique_id(slugify(name), taken)
            now = now_iso()
            self._insert_design_row(db, project_id, {
                "id": design_id, "name": name, "description": description, "status": DEFAULT_STATUS,
                "revision": 1, "config": config, "created_at": now, "created_by": author,
                "updated_at": now, "updated_by": author, "derived_from": derived_from, "is_baseline": False,
            })
            self._touch_project(db, project_id, now)
            return self._design(db, project_id, design_id)

        return self._with_id_retry(create)

    def update_design(
        self,
        project_id: str,
        design_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        is_baseline: bool | None = None,
        author: str | None = None,
    ) -> dict[str, Any]:
        with self._tx(write=True) as db:
            if is_baseline:
                # Lock the project row so two concurrent "make baseline" calls serialize.
                self._project_row(db, project_id, lock=True)
            row = self._design_row(db, project_id, design_id, lock=True)
            now = now_iso()
            if is_baseline:
                db.run(
                    "UPDATE resa_designs SET is_baseline = 0 WHERE project_id = ? AND id <> ?",
                    (project_id, design_id),
                )
            db.run(
                "UPDATE resa_designs SET name = ?, description = ?, status = ?, is_baseline = ?,"
                " updated_at = ?, updated_by = ? WHERE project_id = ? AND id = ?",
                (
                    clean_name(name) if name is not None else row["name"],
                    clean_description(description) if description is not None else row["description"],
                    check_status(status) if status is not None else row["status"],
                    (1 if is_baseline else 0) if is_baseline is not None else row["is_baseline"],
                    now, clean_author(author), project_id, design_id,
                ),
            )
            self._touch_project(db, project_id, now)
            design = self._design(db, project_id, design_id)
        design.pop("config")
        return design

    def delete_design(self, project_id: str, design_id: str) -> None:
        with self._tx(write=True) as db:
            self._design_row(db, project_id, design_id, lock=True)
            db.run("DELETE FROM resa_versions WHERE project_id = ? AND design_id = ?", (project_id, design_id))
            db.run("DELETE FROM resa_designs WHERE project_id = ? AND id = ?", (project_id, design_id))
            self._touch_project(db, project_id, now_iso())

    def save_draft(
        self, project_id: str, design_id: str, config: dict[str, Any], revision: int, author: str | None = None,
    ) -> dict[str, Any]:
        config = check_config(config)
        with self._tx(write=True) as db:
            row = self._design_row(db, project_id, design_id, lock=True)
            if revision != row["revision"]:
                raise Conflict(
                    f"design {design_id} was changed by {row['updated_by'] or 'someone else'} "
                    f"(revision {row['revision']}, you have {revision})",
                    current_revision=row["revision"],
                )
            now, new_revision = now_iso(), row["revision"] + 1
            db.run(
                "UPDATE resa_designs SET config = ?, revision = ?, updated_at = ?, updated_by = ?"
                " WHERE project_id = ? AND id = ?",
                (to_json(config), new_revision, now, clean_author(author), project_id, design_id),
            )
            self._touch_project(db, project_id, now)
            head = self._latest_version(db, project_id, design_id)
        return {
            "revision": new_revision,
            "updated_at": now,
            "has_unsaved_changes": head is None or head["config"] != config,
        }

    # ── versions ─────────────────────────────────────────────────────────────

    def create_version(
        self,
        project_id: str,
        design_id: str,
        message: str,
        author: str | None = None,
        kpis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message, author, kpis = clean_message(message), clean_author(author), check_kpis(kpis)
        with self._tx(write=True) as db:
            # Row lock (postgres) / IMMEDIATE transaction (sqlite) → unique numbers.
            row = self._design_row(db, project_id, design_id, lock=True)
            latest = db.one(
                "SELECT MAX(number) AS n FROM resa_versions WHERE project_id = ? AND design_id = ?",
                (project_id, design_id),
            )
            version = {
                "number": int((latest or {}).get("n") or 0) + 1,
                "message": message,
                "author": author,
                "created_at": now_iso(),
                "kpis": kpis,
                "config": json.loads(row["config"]),
            }
            self._insert_version_row(db, project_id, design_id, version)
            db.run(
                "UPDATE resa_designs SET updated_at = ?, updated_by = ? WHERE project_id = ? AND id = ?",
                (version["created_at"], author, project_id, design_id),
            )
            self._touch_project(db, project_id, version["created_at"])
        return version_summary(version)

    def list_versions(self, project_id: str, design_id: str) -> list[dict[str, Any]]:
        with self._tx() as db:
            self._design_row(db, project_id, design_id)
            rows = db.all(
                "SELECT number, message, author, created_at, kpis FROM resa_versions"
                " WHERE project_id = ? AND design_id = ? ORDER BY number DESC",
                (project_id, design_id),
            )
        return [{**r, "kpis": json.loads(r["kpis"])} for r in rows]

    def _version_row(self, db: _Db, project_id: str, design_id: str, number: int) -> dict[str, Any]:
        self._design_row(db, project_id, design_id)
        row = db.one(
            "SELECT * FROM resa_versions WHERE project_id = ? AND design_id = ? AND number = ?",
            (project_id, design_id, number),
        )
        if row is None:
            raise NotFound(f"version not found: {project_id}/{design_id} v{number}")
        return _version(row)

    def get_version(self, project_id: str, design_id: str, number: int) -> dict[str, Any]:
        with self._tx() as db:
            return version_full(self._version_row(db, project_id, design_id, number))

    def restore_version(
        self, project_id: str, design_id: str, number: int, author: str | None = None,
    ) -> dict[str, Any]:
        with self._tx(write=True) as db:
            row = self._design_row(db, project_id, design_id, lock=True)
            version = self._version_row(db, project_id, design_id, number)
            now = now_iso()
            db.run(
                "UPDATE resa_designs SET config = ?, revision = ?, updated_at = ?, updated_by = ?"
                " WHERE project_id = ? AND id = ?",
                (to_json(version["config"]), row["revision"] + 1, now, clean_author(author), project_id, design_id),
            )
            self._touch_project(db, project_id, now)
            return self._design(db, project_id, design_id)

    # ── bundles ──────────────────────────────────────────────────────────────

    def _insert_bundle(self, data: dict[str, Any], author: str) -> dict[str, Any]:
        def create(db: _Db) -> dict[str, Any]:
            now = now_iso()
            project_id = self._insert_project(db, data["name"], data["description"], author, now)
            for design in data["designs"]:
                self._insert_design_row(db, project_id, {
                    **design, "revision": 1, "created_at": now, "created_by": author,
                    "updated_at": now, "updated_by": author,
                })
                for version in design["versions"]:
                    self._insert_version_row(db, project_id, design["id"], version)
            return self._project(db, project_id)

        return self._with_id_retry(create)
