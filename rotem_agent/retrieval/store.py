from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rotem_agent.state import STATE_DIR, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    matter        TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    pages         INTEGER NOT NULL DEFAULT 0,
    needs_ocr     INTEGER NOT NULL DEFAULT 0,
    machine_read  INTEGER NOT NULL DEFAULT 0,
    ingested_at   TEXT NOT NULL,
    UNIQUE (matter, rel_path)
);

CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    matter       TEXT NOT NULL,
    idx          INTEGER NOT NULL,
    text         TEXT NOT NULL,
    start        INTEGER NOT NULL,
    end          INTEGER NOT NULL,
    terms        TEXT NOT NULL,
    embedding    BLOB,
    embed_model  TEXT
);

CREATE INDEX IF NOT EXISTS chunks_by_matter ON chunks (matter);
"""


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: int
    rel_path: str
    idx: int
    text: str
    terms: list[str]
    embedding: np.ndarray | None


@dataclass(frozen=True)
class DocumentRecord:
    rel_path: str
    content_hash: str
    pages: int
    needs_ocr: bool
    chunks: int
    machine_read: bool = False


class ChunkStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STATE_DIR / "index.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(SCHEMA)
        self._migrate()
        self._connection.commit()

    def _migrate(self) -> None:
        """Add columns the running code needs to an index built by older code.

        Reindexing every matter to gain a column would mean re-embedding, and
        re-running OCR, at real cost.
        """
        existing = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "machine_read" not in existing:
            self._connection.execute(
                "ALTER TABLE documents ADD COLUMN machine_read INTEGER NOT NULL DEFAULT 0"
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "ChunkStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def hashes(self, matter: str) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT rel_path, content_hash FROM documents WHERE matter = ?", (matter,)
        ).fetchall()
        return {row["rel_path"]: row["content_hash"] for row in rows}

    def documents(self, matter: str) -> list[DocumentRecord]:
        rows = self._connection.execute(
            """
            SELECT d.rel_path, d.content_hash, d.pages, d.needs_ocr, d.machine_read,
                   (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunks
            FROM documents d WHERE d.matter = ? ORDER BY d.rel_path
            """,
            (matter,),
        ).fetchall()
        return [
            DocumentRecord(
                rel_path=row["rel_path"],
                content_hash=row["content_hash"],
                pages=row["pages"],
                needs_ocr=bool(row["needs_ocr"]),
                chunks=row["chunks"],
                machine_read=bool(row["machine_read"]),
            )
            for row in rows
        ]

    def replace_document(
        self,
        matter: str,
        rel_path: str,
        content_hash: str,
        *,
        pages: int,
        needs_ocr: bool,
        chunks: list[tuple[int, str, int, int, list[str], np.ndarray | None]],
        embed_model: str,
        machine_read: bool = False,
    ) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM documents WHERE matter = ? AND rel_path = ?", (matter, rel_path)
            )
            cursor = self._connection.execute(
                """
                INSERT INTO documents
                    (matter, rel_path, content_hash, pages, needs_ocr, machine_read, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    matter,
                    rel_path,
                    content_hash,
                    pages,
                    int(needs_ocr),
                    int(machine_read),
                    utc_now(),
                ),
            )
            document_id = cursor.lastrowid
            self._connection.executemany(
                """
                INSERT INTO chunks
                    (document_id, matter, idx, text, start, end, terms, embedding, embed_model)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        matter,
                        idx,
                        text,
                        start,
                        end,
                        json.dumps(terms, ensure_ascii=False),
                        None if vector is None else np.asarray(vector, dtype=np.float32).tobytes(),
                        embed_model,
                    )
                    for idx, text, start, end, terms, vector in chunks
                ],
            )

    def forget_document(self, matter: str, rel_path: str) -> None:
        """Remove a file that is no longer in the matter folder.

        A document withdrawn from a matter must stop appearing in drafts, so
        deletion has to propagate rather than leaving orphaned chunks behind.
        """
        with self._connection:
            self._connection.execute(
                "DELETE FROM documents WHERE matter = ? AND rel_path = ?", (matter, rel_path)
            )

    def load_chunks(self, matter: str) -> list[StoredChunk]:
        rows = self._connection.execute(
            """
            SELECT c.id, c.idx, c.text, c.terms, c.embedding, d.rel_path
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.matter = ? ORDER BY d.rel_path, c.idx
            """,
            (matter,),
        ).fetchall()
        return [
            StoredChunk(
                chunk_id=row["id"],
                rel_path=row["rel_path"],
                idx=row["idx"],
                text=row["text"],
                terms=json.loads(row["terms"]),
                embedding=(
                    None
                    if row["embedding"] is None
                    else np.frombuffer(row["embedding"], dtype=np.float32)
                ),
            )
            for row in rows
        ]
