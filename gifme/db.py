from __future__ import annotations

import json

from mautrix.util.async_db import UpgradeTable, Connection, Scheme

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Table initialization (SQLite FTS4 responses)")
async def upgrade_v1(conn: Connection, scheme: Scheme) -> None:
    if scheme == Scheme.SQLITE:
        await conn.execute(
            """CREATE VIRTUAL TABLE responses USING fts4(
                msg_info TEXT,
                tags TEXT,
                tokenize=porter
            )"""
        )
    # Postgres: FTS4 does not exist; do nothing. v2 will create entries.


@upgrade_table.register(description="Replace responses with columnar entries table and migrate")
async def upgrade_v2(conn: Connection, scheme: Scheme) -> None:
    # Create entries table (dialect-aware)
    if scheme == Scheme.SQLITE:
        await conn.execute("""
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                msgtype TEXT NOT NULL,
                mime_type TEXT,
                width INTEGER,
                height INTEGER,
                size INTEGER,
                filename TEXT,
                body TEXT,
                formatted_body TEXT,
                sender TEXT,
                tags TEXT
            )
        """)
    else:
        await conn.execute("""
            CREATE TABLE entries (
                id SERIAL PRIMARY KEY,
                original TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                msgtype TEXT NOT NULL,
                mime_type TEXT,
                width INTEGER,
                height INTEGER,
                size BIGINT,
                filename TEXT,
                body TEXT,
                formatted_body TEXT,
                sender TEXT,
                tags TEXT
            )
        """)

    # Full-text search: GIN on Postgres, no extra object on SQLite (we use LIKE in app)
    if scheme != Scheme.SQLITE:
        await conn.execute("""
            CREATE INDEX idx_entries_tags_fts ON entries
            USING GIN (to_tsvector('english', COALESCE(tags, '')))
        """)

    # Migrate from responses if it exists (SQLite only; Postgres would not have FTS4)
    if await conn.table_exists("responses"):
        rows = await conn.fetch("SELECT docid, msg_info, tags FROM responses")
        for r in rows:
            try:
                j = json.loads(r["msg_info"])
            except (json.JSONDecodeError, TypeError):
                continue
            orig = j.get("original") or ""
            if not orig:
                continue

            # Infer msgtype
            if "body" in j or "sender" in j:
                msgtype = "text"
            elif (j.get("mimetype") or "").lower().startswith("video"):
                msgtype = "video"
            elif (
                "filename" in j
                or "mimetype" in j
                or (isinstance(orig, str) and orig.startswith("mxc:"))
            ):
                msgtype = "image"
            else:
                msgtype = "text"

            tags_val = r["tags"] or ""

            await conn.execute(
                """INSERT INTO entries (
                    original, source, msgtype, mime_type, width, height, size,
                    filename, body, formatted_body, sender, tags
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                orig,
                "migrated",
                msgtype,
                j.get("mimetype"),
                j.get("width"),
                j.get("height"),
                j.get("size"),
                j.get("filename"),
                j.get("body"),
                j.get("formatted_body"),
                j.get("sender"),
                tags_val,
            )

        await conn.execute("DROP TABLE responses")
