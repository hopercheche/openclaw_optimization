from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Iterable

from .models import AuditEvent, RunState, utc_now


@dataclass(slots=True)
class ContextRecord:
    record_key: str
    run_id: str
    kind: str
    title: str
    body: str
    source: str
    created_at: str
    metadata: dict
    score: float = 0.0

    @property
    def record_id(self) -> str:
        return self.record_key

    def to_dict(self, snippet_limit: int = 500) -> dict:
        payload = asdict(self)
        payload["record_id"] = self.record_id
        payload["snippet"] = _trim_text(self.body, snippet_limit)
        payload.pop("body", None)
        return payload


class ContextIndex:
    """Local long-term context index backed by SQLite FTS when available."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fts_enabled = self._initialize()

    @property
    def fts_enabled(self) -> bool:
        return self._fts_enabled

    def archive_run(self, state: RunState, events: Iterable[AuditEvent]) -> list[ContextRecord]:
        records = _records_from_run(state, list(events))
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM context_records WHERE run_id = ?", (state.run_id,))
            if self._fts_enabled:
                connection.execute("DELETE FROM context_records_fts WHERE run_id = ?", (state.run_id,))
            for record in records:
                self._insert_record(connection, record)
            connection.commit()
        return records

    def archive_record(
        self,
        run_id: str,
        kind: str,
        title: str,
        body: str,
        source: str,
        metadata: dict | None = None,
    ) -> str:
        record = ContextRecord(
            record_key=_record_key(run_id, kind, title),
            run_id=run_id,
            kind=kind,
            title=title,
            body=body,
            source=source,
            created_at=utc_now(),
            metadata=metadata or {},
        )
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM context_records WHERE record_key = ?", (record.record_key,))
            if self._fts_enabled:
                connection.execute(
                    "DELETE FROM context_records_fts WHERE record_key = ?",
                    (record.record_key,),
                )
            self._insert_record(connection, record)
            connection.commit()
        return record.record_id

    def search(
        self,
        query: str,
        top_k: int = 5,
        exclude_run_id: str | None = None,
        limit: int | None = None,
    ) -> list[ContextRecord]:
        requested_limit = top_k if limit is None else limit
        normalized_limit = max(1, min(20, int(requested_limit)))
        if self._fts_enabled:
            try:
                return self._search_fts(query, normalized_limit, exclude_run_id)
            except sqlite3.Error:
                return self._search_like(query, normalized_limit, exclude_run_id)
        return self._search_like(query, normalized_limit, exclude_run_id)

    def render_snippets(self, records: Iterable[ContextRecord], snippet_limit: int = 500) -> list[dict]:
        return [record.to_dict(snippet_limit=snippet_limit) for record in records]

    def render_payload(self, records: Iterable[ContextRecord], snippet_limit: int = 500) -> dict:
        return {
            "retrieved_context": self.render_snippets(records, snippet_limit=snippet_limit),
        }

    def _initialize(self) -> bool:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS context_records (
                    record_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """,
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_context_records_run
                ON context_records(run_id)
                """,
            )
            fts_enabled = _sqlite_supports_fts5(connection)
            if fts_enabled:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS context_records_fts
                    USING fts5(
                        record_key UNINDEXED,
                        run_id UNINDEXED,
                        kind,
                        title,
                        body,
                        source UNINDEXED
                    )
                    """,
                )
            connection.commit()
        return fts_enabled

    def _search_fts(
        self,
        query: str,
        limit: int,
        exclude_run_id: str | None,
    ) -> list[ContextRecord]:
        match_query = _fts_query(query)
        if not match_query:
            return []
        params: list[object] = [match_query]
        run_filter = ""
        if exclude_run_id:
            run_filter = "AND r.run_id != ?"
            params.append(exclude_run_id)
        params.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    r.record_key,
                    r.run_id,
                    r.kind,
                    r.title,
                    r.body,
                    r.source,
                    r.created_at,
                    r.metadata_json,
                    bm25(context_records_fts) AS rank
                FROM context_records_fts
                JOIN context_records r
                    ON r.record_key = context_records_fts.record_key
                WHERE context_records_fts MATCH ?
                    {run_filter}
                ORDER BY rank ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def _search_like(
        self,
        query: str,
        limit: int,
        exclude_run_id: str | None,
    ) -> list[ContextRecord]:
        terms = _query_terms(query)
        if not terms:
            return []
        params: list[object] = []
        clauses: list[str] = []
        for term in terms[:8]:
            pattern = f"%{term}%"
            clauses.append("(lower(title) LIKE ? OR lower(body) LIKE ? OR lower(kind) LIKE ?)")
            params.extend([pattern, pattern, pattern])
        run_filter = ""
        if exclude_run_id:
            run_filter = "AND run_id != ?"
            params.append(exclude_run_id)
        params.append(max(limit * 4, limit))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    record_key,
                    run_id,
                    kind,
                    title,
                    body,
                    source,
                    created_at,
                    metadata_json,
                    0.0 AS rank
                FROM context_records
                WHERE ({" OR ".join(clauses)})
                    {run_filter}
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        records = [_record_from_row(row) for row in rows]
        scored = [
            _score_like_record(record, terms)
            for record in records
        ]
        return sorted(scored, key=lambda item: (-item.score, item.created_at, item.record_key))[:limit]

    def _insert_record(self, connection: sqlite3.Connection, record: ContextRecord) -> None:
        connection.execute(
            """
            INSERT INTO context_records (
                record_key, run_id, kind, title, body, source, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.record_key,
                record.run_id,
                record.kind,
                record.title,
                record.body,
                record.source,
                record.created_at,
                json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        if self._fts_enabled:
            connection.execute(
                """
                INSERT INTO context_records_fts (
                    record_key, run_id, kind, title, body, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_key,
                    record.run_id,
                    record.kind,
                    record.title,
                    record.body,
                    record.source,
                ),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


def _sqlite_supports_fts5(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("CREATE VIRTUAL TABLE temp._openclaw_fts_check USING fts5(value)")
        connection.execute("DROP TABLE temp._openclaw_fts_check")
        return True
    except sqlite3.Error:
        return False


def _records_from_run(state: RunState, events: list[AuditEvent]) -> list[ContextRecord]:
    created_at = utc_now()
    records: list[ContextRecord] = [
        ContextRecord(
            record_key=f"{state.run_id}:goal",
            run_id=state.run_id,
            kind="goal",
            title="Run goal",
            body=state.goal.strip(),
            source="run_state.goal",
            created_at=created_at,
            metadata={
                "planner_strategy": state.planner_strategy,
                "permission_mode": state.permission_mode,
                "workspace_path": state.workspace_path,
            },
        ),
    ]

    planning_events = [event for event in events if event.event_type == "planning"]
    if planning_events:
        event = planning_events[-1]
        records.append(
            ContextRecord(
                record_key=f"{state.run_id}:planning",
                run_id=state.run_id,
                kind="planning",
                title="Selected planner path",
                body=_planning_body(event),
                source=f"audit_event:{event.event_id}",
                created_at=event.timestamp,
                metadata={
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "selected_tools": event.data.get("selected_tools", []),
                    "selection_rule": event.data.get("selection_rule", ""),
                },
            ),
        )

    critique_events = [event for event in events if event.event_type == "critique"]
    if critique_events:
        records.append(
            ContextRecord(
                record_key=f"{state.run_id}:critique",
                run_id=state.run_id,
                kind="critique",
                title="Verifier critique summary",
                body=_join_event_messages(critique_events, limit=8),
                source="audit_events:critique",
                created_at=critique_events[-1].timestamp,
                metadata={
                    "event_count": len(critique_events),
                    "event_ids": [event.event_id for event in critique_events[:8]],
                },
            ),
        )

    if state.final_response.strip():
        records.append(
            ContextRecord(
                record_key=f"{state.run_id}:final",
                run_id=state.run_id,
                kind="final",
                title="Final response",
                body=state.final_response.strip(),
                source="run_state.final_response",
                created_at=state.updated_at,
                metadata={
                    "status": state.status,
                    "audit_path": state.audit_path,
                },
            ),
        )

    return [record for record in records if record.body.strip()]


def _record_key(run_id: str, kind: str, title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_")
    return f"{run_id}:{kind}:{slug[:48] or 'record'}"


def _planning_body(event: AuditEvent) -> str:
    selected_titles = event.data.get("selected_titles", [])
    selected_tools = event.data.get("selected_tools", [])
    return " ".join([
        f"Selected planner titles: {', '.join(map(str, selected_titles))}.",
        f"Selected tools: {', '.join(map(str, selected_tools))}.",
        f"Selection rule: {event.data.get('selection_rule', '')}.",
        f"Planner strategy: {event.data.get('planner_strategy', '')}.",
    ]).strip()


def _join_event_messages(events: list[AuditEvent], limit: int) -> str:
    parts: list[str] = []
    for event in events[:limit]:
        critique = event.data.get("critique")
        if critique:
            parts.append(str(critique))
        else:
            parts.append(event.message)
    return " ".join(parts)


def _record_from_row(row: sqlite3.Row) -> ContextRecord:
    metadata_json = row["metadata_json"] or "{}"
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        metadata = {}
    score = float(row["rank"])
    if score < 0:
        score = -score
    return ContextRecord(
        record_key=str(row["record_key"]),
        run_id=str(row["run_id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        body=str(row["body"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        metadata=metadata,
        score=score,
    )


def _score_like_record(record: ContextRecord, terms: list[str]) -> ContextRecord:
    haystack = f"{record.kind} {record.title} {record.body}".lower()
    record.score = sum(haystack.count(term) for term in terms)
    return record


def _fts_query(query: str) -> str:
    terms = _query_terms(query)
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms[:8])


def _query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in re.findall(r"\w+", query.lower()):
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _trim_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."
