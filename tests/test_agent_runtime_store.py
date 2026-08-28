"""S13-P1-1: Agent 运行期状态存储单元测试。

覆盖 StopStore / ActiveAgentStore 接口的默认内存实现：
get/set/pop、不存在返回 None、contains 语义。
"""
import asyncio

import pytest

from services.agent_runtime_store import (
    MemoryStopStore,
    MemoryActiveAgentStore,
)


# ── MemoryStopStore ─────────────────────────────────────────

def test_stop_store_set_get():
    store = MemoryStopStore()
    event = asyncio.Event()
    store.set('conv-1', event)
    assert store.get('conv-1') is event


def test_stop_store_get_missing_returns_none():
    store = MemoryStopStore()
    assert store.get('conv-missing') is None


def test_stop_store_pop_removes_and_returns():
    store = MemoryStopStore()
    event = asyncio.Event()
    store.set('conv-1', event)
    assert store.pop('conv-1') is event
    assert store.get('conv-1') is None


def test_stop_store_pop_missing_returns_none():
    store = MemoryStopStore()
    assert store.pop('conv-missing') is None


def test_stop_store_set_overwrites():
    store = MemoryStopStore()
    e1 = asyncio.Event()
    e2 = asyncio.Event()
    store.set('conv-1', e1)
    store.set('conv-1', e2)
    assert store.get('conv-1') is e2


# ── MemoryActiveAgentStore ──────────────────────────────────

def test_agent_store_set_get():
    store = MemoryActiveAgentStore()
    agent = object()
    store.set('conv-1', agent)
    assert store.get('conv-1') is agent


def test_agent_store_get_missing_returns_none():
    store = MemoryActiveAgentStore()
    assert store.get('conv-missing') is None


def test_agent_store_pop_removes_and_returns():
    store = MemoryActiveAgentStore()
    agent = object()
    store.set('conv-1', agent)
    assert store.pop('conv-1') is agent
    assert store.get('conv-1') is None


def test_agent_store_pop_missing_returns_none():
    store = MemoryActiveAgentStore()
    assert store.pop('conv-missing') is None


def test_agent_store_contains():
    store = MemoryActiveAgentStore()
    assert not store.contains('conv-1')
    store.set('conv-1', object())
    assert store.contains('conv-1')
    store.pop('conv-1')
    assert not store.contains('conv-1')


def test_agent_store_set_overwrites():
    store = MemoryActiveAgentStore()
    a1 = object()
    a2 = object()
    store.set('conv-1', a1)
    store.set('conv-1', a2)
    assert store.get('conv-1') is a2
