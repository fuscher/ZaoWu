"""ConversationStore 阶段二 schema 与压缩字段持久化测试。"""
import pytest

pytestmark = pytest.mark.anyio

from services.conversation_store import ConversationStore


@pytest.fixture
async def store(tmp_path):
    s = ConversationStore(str(tmp_path / 'test.db'))
    await s.ensure_tables()
    await s.create({
        'id': 'conv-1',
        'title': 'T',
        'providerId': 'p',
        'modelId': 'm',
        'systemPrompt': '',
        'createdAt': '2026-01-01T00:00:00+00:00',
        'updatedAt': '2026-01-01T00:00:00+00:00',
        'agentConfig': {'enabled': True},
    })
    return s


async def test_new_db_has_compaction_columns(store):
    """新库建表后 compaction_summary / compacted_until_seq 列存在。"""
    async with store._connect() as db:
        cur = await db.execute('PRAGMA table_info(conversations)')
        cols = {row[1] for row in await cur.fetchall()}
    assert 'compaction_summary' in cols
    assert 'compacted_until_seq' in cols


async def test_default_compaction_fields(store):
    """新建对话无压缩时：compactionSummary 为 None，compactedUntilSeq 为 -1。"""
    conv = await store.get('conv-1')
    assert conv['compactionSummary'] is None
    assert conv['compactedUntilSeq'] == -1


async def test_update_compaction_fields_round_trip(store):
    """update 写入压缩字段后 get 能读回。"""
    await store.update('conv-1', {
        'compactionSummary': '历史摘要：用户在做 X',
        'compactedUntilSeq': 12,
    })
    conv = await store.get('conv-1')
    assert conv['compactionSummary'] == '历史摘要：用户在做 X'
    assert conv['compactedUntilSeq'] == 12


async def test_message_row_carries_seq(store):
    """_row_to_msg 应携带 seq，供 _build_messages 跳过已压缩早期消息。"""
    await store.append_message('conv-1', {
        'id': 'm1', 'role': 'user', 'content': 'hi', 'timestamp': 1,
    })
    await store.append_message('conv-1', {
        'id': 'm2', 'role': 'assistant', 'content': 'hello', 'timestamp': 2,
    })
    conv = await store.get('conv-1')
    seqs = [m.get('seq') for m in conv['messages']]
    assert seqs == [0, 1]


async def test_migration_adds_columns_to_legacy_db(tmp_path):
    """旧库（无压缩列）ensure_tables 后应自动补列，不丢数据。"""
    import aiosqlite
    db_path = str(tmp_path / 'legacy.db')
    # 模拟旧库结构（无 compaction 列）
    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT, provider_id TEXT, model_id TEXT,
                system_prompt TEXT, created_at TEXT, updated_at TEXT,
                agent_config_json TEXT
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
                timestamp INTEGER, model TEXT, tool_calls_json TEXT,
                tool_call_id TEXT, name TEXT, seq INTEGER DEFAULT 0
            );
            INSERT INTO conversations(id,title,provider_id,model_id,system_prompt,
                created_at,updated_at,agent_config_json)
                VALUES('c1','t','p','m','','','','{}');
        """)
        await db.commit()

    # 用新代码打开旧库 → 迁移
    s = ConversationStore(db_path)
    await s.ensure_tables()
    conv = await s.get('c1')
    assert conv is not None
    # 旧库迁移后压缩字段有默认值
    assert conv['compactionSummary'] is None
    assert conv['compactedUntilSeq'] == -1


async def test_corrupt_tool_calls_json_does_not_break_get(store):
    """损坏的 tool_calls_json 不应让整个对话构建失败。

    旧代码 `json.loads(row['tool_calls_json'])` 无 try/except → JSONDecodeError
    → store.get 抛出 → agent_service._get_conversation 吞掉返回 None
    → 整个对话显示 not found。修复后丢弃该字段，其余消息正常返回。
    """
    import aiosqlite
    db_path = store._db_path
    # 直接写一条 tool_calls_json 损坏的 assistant 消息（模拟旧版本/手动改库/写入中断）
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO messages(id,conversation_id,role,content,timestamp,model,"
            "tool_calls_json,tool_call_id,name,seq) "
            "VALUES('bad','conv-1','assistant',NULL,1,'','{not valid json',NULL,NULL,0)"
        )
        await db.execute(
            "INSERT INTO messages(id,conversation_id,role,content,timestamp,model,"
            "tool_calls_json,tool_call_id,name,seq) "
            "VALUES('good','conv-1','user','hi',2,'',NULL,NULL,NULL,1)"
        )
        await db.commit()

    conv = await store.get('conv-1')
    # 关键：没有抛 JSONDecodeError，对话仍可读出
    assert conv is not None
    by_id = {m['id']: m for m in conv['messages']}
    # 损坏消息保留但 tool_calls 字段被丢弃
    assert 'tool_calls' not in by_id['bad']
    # 其余消息正常
    assert by_id['good']['content'] == 'hi'
