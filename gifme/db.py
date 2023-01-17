from __future__ import annotations

from mautrix.util.async_db import UpgradeTable, Connection

upgrade_table = UpgradeTable()

@upgrade_table.register(description="Table initialization")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
            """CREATE VIRTUAL TABLE responses USING fts4(
                msg_info TEXT,
                tags TEXT,
                tokenize=porter
            )"""
    )
