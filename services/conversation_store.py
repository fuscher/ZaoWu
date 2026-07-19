"""SQLite 对话存储 — 替代 conversations.json 的全量读写。

每轮 Agent 迭代后逐条追加消息不再需要解析整个 JSON 文件；
所有 REST API 返回的 JSON 形状与原 conversations.json 完全兼容。

用法：
    store = ConversationStore(db_path)
    await store.ensure_tables()
    convs = await store.list_all()
    conv = await store.get(conv_id)
    await store.append_message(conv_id, user_msg)
"""

from __future__ import annotations

import json
import os
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, AsyncIterator

import aiosqlite

logger = logging.getLogger('zaowu.services.conversation_store')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'data', 'conversations.db')

# ── SQL ───────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id               TEXT PRIMARY KEY,
    title            TEXT NOT NULL DEFAULT '',
    provider_id      TEXT NOT NULL DEFAULT '',
    model_id         TEXT NOT NULL DEFAULT '',
    system_prompt    TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    agent_config_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id                TEXT PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role              TEXT NOT NULL,
    content           TEXT,
    timestamp         INTEGER NOT NULL,
    model             TEXT NOT NULL DEFAULT '',
    tool_calls_json   TEXT,
    tool_call_id      TEXT,
    name              TEXT,
    seq               INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, seq);
"""


class ConversationStore:
    """SQLite 对话存储，对外返回与 conversations.json 完全兼容的 dict 结构。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    # ── lifecycle ──────────────────────────────────────────────

    async def ensure_tables(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with self._connect() as db:
            await db.executescript(DDL)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """返回已启用 foreign_keys + WAL 的数据库连接。"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute('PRAGMA journal_mode=WAL')
            await db.execute('PRAGMA foreign_keys=ON')
            yield db

    async def close(self) -> None:
        pass  # aiosqlite connections are ephemeral (async with)

    # ── conversation CRUD ─────────────────────────────────────

    @staticmethod
    def _row_to_conv(row: aiosqlite.Row) -> dict:
        return {
            'id': row['id'],
            'title': row['title'],
            'providerId': row['provider_id'],
            'modelId': row['model_id'],
            'systemPrompt': row['system_prompt'],
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at'],
            'agentConfig': json.loads(row['agent_config_json']),
            'messages': [],
        }

    @staticmethod
    def _row_to_msg(row: aiosqlite.Row) -> dict:
        msg: dict = {
            'id': row['id'],
            'role': row['role'],
            'content': row['content'],
            'timestamp': row['timestamp'],
        }
        if row['model']:
            msg['model'] = row['model']
        if row['tool_calls_json']:
            msg['tool_calls'] = json.loads(row['tool_calls_json'])
        if row['tool_call_id']:
            msg['tool_call_id'] = row['tool_call_id']
        if row['name']:
            msg['name'] = row['name']
        return msg

    async def list_all(self) -> List[dict]:
        """返回对话列表（不含 messages，与原有 /api/chat/conversations GET 兼容）。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                'SELECT * FROM conversations ORDER BY updated_at DESC',
            )
            convs = [self._row_to_conv(r) for r in rows]
            for c in convs:
                c['messageCount'] = (
                    await (await db.execute(
                        'SELECT COUNT(*) FROM messages WHERE conversation_id=?',
                        (c['id'],)
                    )).fetchone()
                )[0]
                del c['messages']  # list_all doesn't include message bodies
            return convs

    async def get(self, conv_id: str) -> Optional[dict]:
        """返回完整对话（含 messages 数组）。"""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                'SELECT * FROM conversations WHERE id=?', (conv_id,)
            )).fetchone()
            if row is None:
                return None
            conv = self._row_to_conv(row)
            msg_rows = await db.execute_fetchall(
                'SELECT * FROM messages WHERE conversation_id=? ORDER BY seq',
                (conv_id,),
            )
            conv['messages'] = [self._row_to_msg(m) for m in msg_rows]
            return conv

    async def exists(self, conv_id: str) -> bool:
        async with self._connect() as db:
            row = await (await db.execute(
                'SELECT 1 FROM conversations WHERE id=?', (conv_id,)
            )).fetchone()
            return row is not None

    async def create(self, conv: dict) -> None:
        async with self._connect() as db:
            await db.execute(
                'INSERT INTO conversations(id,title,provider_id,model_id,system_prompt,created_at,updated_at,agent_config_json) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (
                    conv['id'], conv.get('title', ''),
                    conv.get('providerId', ''), conv.get('modelId', ''),
                    conv.get('systemPrompt', ''),
                    conv.get('createdAt', ''), conv.get('updatedAt', ''),
                    json.dumps(conv.get('agentConfig', {}), ensure_ascii=False),
                ),
            )
            await db.commit()

    async def update(self, conv_id: str, fields: dict) -> None:
        sets: List[str] = []
        values: List[Any] = []
        field_map = {
            'title': 'title',
            'providerId': 'provider_id',
            'modelId': 'model_id',
            'systemPrompt': 'system_prompt',
            'updatedAt': 'updated_at',
        }
        for key, col in field_map.items():
            if key in fields:
                sets.append(f'{col}=?')
                values.append(fields[key])
        if 'agentConfig' in fields:
            sets.append('agent_config_json=?')
            values.append(json.dumps(fields['agentConfig'], ensure_ascii=False))
        if not sets:
            return
        values.append(conv_id)
        async with self._connect() as db:
            await db.execute(
                f'UPDATE conversations SET {", ".join(sets)} WHERE id=?',
                tuple(values),
            )
            await db.commit()

    async def delete(self, conv_id: str) -> None:
        async with self._connect() as db:
            await db.execute('DELETE FROM conversations WHERE id=?', (conv_id,))
            await db.commit()

    async def clear_messages(self, conv_id: str) -> None:
        async with self._connect() as db:
            await db.execute('DELETE FROM messages WHERE conversation_id=?', (conv_id,))
            await db.commit()

    # ── message CRUD ──────────────────────────────────────────

    async def append_message(self, conv_id: str, msg: dict) -> None:
        next_seq = await self._next_seq(conv_id)
        msg_id = msg.get('id') or f'{next_seq}-{int(msg.get("timestamp", 0))}'
        async with self._connect() as db:
            await db.execute(
                'INSERT INTO messages(id,conversation_id,role,content,timestamp,model,'
                'tool_calls_json,tool_call_id,name,seq) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (
                    msg_id,
                    conv_id,
                    msg.get('role', ''),
                    msg.get('content'),
                    msg.get('timestamp', 0),
                    msg.get('model', ''),
                    json.dumps(msg.get('tool_calls')) if msg.get('tool_calls') else None,
                    msg.get('tool_call_id'),
                    msg.get('name'),
                    next_seq,
                ),
            )
            if 'updatedAt' in msg:
                await db.execute(
                    'UPDATE conversations SET updated_at=? WHERE id=?',
                    (msg['updatedAt'], conv_id),
                )
            await db.commit()

    async def count_messages(self, conv_id: str) -> int:
        async with self._connect() as db:
            row = await (await db.execute(
                'SELECT COUNT(*) FROM messages WHERE conversation_id=?', (conv_id,)
            )).fetchone()
            return row[0] if row else 0

    async def _next_seq(self, conv_id: str) -> int:
        async with self._connect() as db:
            row = await (await db.execute(
                'SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE conversation_id=?',
                (conv_id,),
            )).fetchone()
            return row[0] if row else 0

    # ── migration ─────────────────────────────────────────────

    async def migrate_from_json(self, json_path: str) -> int:
        """从 conversations.json 导入数据。返回导入的对话数量。"""
        if not os.path.exists(json_path):
            return 0
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return 0

        convs = data.get('conversations', [])
        if not convs:
            return 0

        imported = 0
        async with self._connect() as db:
            for conv in convs:
                cid = conv.get('id', '')
                if not cid or await self._exists_in_db(db, cid):
                    continue
                await db.execute(
                    'INSERT INTO conversations(id,title,provider_id,model_id,system_prompt,created_at,updated_at,agent_config_json) '
                    'VALUES(?,?,?,?,?,?,?,?)',
                    (
                        cid, conv.get('title', ''),
                        conv.get('providerId', ''), conv.get('modelId', ''),
                        conv.get('systemPrompt', ''),
                        conv.get('createdAt', ''), conv.get('updatedAt', ''),
                        json.dumps(conv.get('agentConfig', {}), ensure_ascii=False),
                    ),
                )
                for i, msg in enumerate(conv.get('messages', [])):
                    await db.execute(
                        'INSERT INTO messages(id,conversation_id,role,content,timestamp,model,'
                        'tool_calls_json,tool_call_id,name,seq) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (
                            msg.get('id', ''), cid,
                            msg.get('role', ''), msg.get('content'),
                            msg.get('timestamp', 0), msg.get('model', ''),
                            json.dumps(msg.get('tool_calls')) if msg.get('tool_calls') else None,
                            msg.get('tool_call_id'), msg.get('name'), i,
                        ),
                    )
                imported += 1
            await db.commit()
        return imported

    @staticmethod
    async def _exists_in_db(db: aiosqlite.Connection, conv_id: str) -> bool:
        row = await (await db.execute(
            'SELECT 1 FROM conversations WHERE id=?', (conv_id,)
        )).fetchone()
        return row is not None
