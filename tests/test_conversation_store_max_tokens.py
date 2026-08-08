"""ConversationStore max_tokens 列持久化测试。

覆盖：
- 新库建表含 max_tokens 列
- create/update 往返读写
- 旧库迁移补列、旧行 maxTokens 为 None（不固化默认值，全局 config 兜底语义）
"""
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


async def test_new_db_has_max_tokens_column(store):
    """新库建表后 max_tokens 列存在。"""
    async with store._connect() as db:
        cur = await db.execute('PRAGMA table_info(conversations)')
        cols = {row[1] for row in await cur.fetchall()}
    assert 'max_tokens' in cols


async def test_default_max_tokens_is_none(store):
    """新建对话未设置 maxTokens 时读回 None（兜底语义：跟随全局 config）。"""
    conv = await store.get('conv-1')
    assert 'maxTokens' in conv
    assert conv['maxTokens'] is None


async def test_create_with_max_tokens_round_trip(tmp_path):
    """create 携带 maxTokens 时 get 能读回。"""
    s = ConversationStore(str(tmp_path / 'test.db'))
    await s.ensure_tables()
    await s.create({
        'id': 'c2',
        'title': 'T2',
        'providerId': 'p',
        'modelId': 'm',
        'systemPrompt': '',
        'createdAt': '2026-01-01T00:00:00+00:00',
        'updatedAt': '2026-01-01T00:00:00+00:00',
        'agentConfig': {},
        'maxTokens': 8192,
    })
    conv = await s.get('c2')
    assert conv['maxTokens'] == 8192


async def test_update_max_tokens_round_trip(store):
    """update 写入 maxTokens 后 get 能读回。"""
    await store.update('conv-1', {'maxTokens': 1024})
    conv = await store.get('conv-1')
    assert conv['maxTokens'] == 1024


async def test_migration_adds_max_tokens_to_legacy_db(tmp_path):
    """旧库（无 max_tokens 列）ensure_tables 后应自动补列，且旧行 maxTokens 为 None。

    关键：列无 DEFAULT，迁移不能给旧行回填 4096——
    否则全局 config 兜底对旧对话永久失效（本缺陷的变体）。
    """
    import aiosqlite
    db_path = str(tmp_path / 'legacy.db')
    # 模拟旧库结构（无 max_tokens 列）
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
    # 补列成功 + 旧行未被回填默认值
    assert 'maxTokens' in conv
    assert conv['maxTokens'] is None
