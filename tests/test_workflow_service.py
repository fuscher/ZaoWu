import pytest

from services.workflow_service import (
    _migrate_definition,
    _dict_to_definition,
    save,
    touch_run_metadata,
    list_all,
)


def test_migrate_condition_code_to_expression_is_persisted():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {
                'id': 'cond-1',
                'type': 'condition',
                'config': {'conditionConfig': {'mode': 'code', 'expression': 'x > 1'}},
            }
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    node = migrated['nodes'][0]
    assert node['config']['conditionConfig']['mode'] == 'expression'
    assert migrated['_migration_log'][0]['type'] == 'condition_code_to_expression'


def test_migrate_condition_llm_to_prompt_is_persisted():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {
                'id': 'cond-1',
                'type': 'condition',
                'config': {'conditionConfig': {'mode': 'llm', 'naturalLanguage': 'is it true?'}},
            }
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    node = migrated['nodes'][0]
    assert node['config']['conditionConfig']['mode'] == 'prompt'
    assert node['config']['conditionConfig']['judgePrompt'] == 'is it true?'


def test_migrate_end_output_format_is_persisted():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {
                'id': 'end-1',
                'type': 'end',
                'config': {'outputFormat': 'markdown'},
            }
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    node = migrated['nodes'][0]
    assert 'outputFormat' not in node['config']
    assert node['config']['endMode'] == 'log'
    assert node['config']['logFormat'] == 'markdown'


def test_migrate_loop_old_mode_and_fields_are_persisted():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {
                'id': 'loop-1',
                'type': 'loop',
                'config': {
                    'loopConfig': {
                        'mode': 'for',
                        'condition': 'x > 1',
                        'iterateOver': 'items',
                    }
                },
            }
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    node = migrated['nodes'][0]
    lc = node['config']['loopConfig']
    assert lc == {'maxIterations': 10}
    assert any(
        log['type'] == 'loop_mode_removed' and log['oldMode'] == 'for'
        for log in migrated['_migration_log']
    )


def test_migrate_loop_edge_ports_are_persisted():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {'id': 'loop-1', 'type': 'loop', 'config': {}},
            {'id': 'other', 'type': 'tool', 'config': {}},
        ],
        'edges': [
            {'id': 'e1', 'source': 'loop-1', 'sourcePort': 'break', 'target': 'other', 'targetPort': 'items'},
        ],
    }
    migrated = _migrate_definition(raw)
    edge = migrated['edges'][0]
    assert edge['sourcePort'] == 'out'
    assert edge['targetPort'] == 'in'


def test_migrate_router_node_and_break_edges_removed():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {'id': 'router-1', 'type': 'router', 'config': {}},
            {'id': 'tool-1', 'type': 'tool', 'config': {}},
        ],
        'edges': [
            {'id': 'e1', 'source': 'router-1', 'sourcePort': 'default', 'target': 'tool-1', 'targetPort': 'default', 'edgeType': 'break'},
        ],
    }
    migrated = _migrate_definition(raw)
    assert all(n['type'] != 'router' for n in migrated['nodes'])
    assert len(migrated['edges']) == 0
    assert any(log['type'] == 'router_node_removed' for log in migrated['_migration_log'])


def test_migrate_does_not_mutate_input():
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {
                'id': 'cond-1',
                'type': 'condition',
                'config': {'conditionConfig': {'mode': 'code'}},
            }
        ],
        'edges': [],
    }
    original_mode = raw['nodes'][0]['config']['conditionConfig']['mode']
    _migrate_definition(raw)
    assert raw['nodes'][0]['config']['conditionConfig']['mode'] == original_mode


def test_migrate_loop_body_edges_promoted():
    """旧 bodyNodeIds / bodyEdges 应被提升为真实工作流边，loopConfig 仅保留 maxIterations。"""
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {'id': 'loop-1', 'type': 'loop', 'config': {
                'loopConfig': {
                    'maxIterations': 5,
                    'bodyNodeIds': ['body_1', 'body_2'],
                    'bodyEdges': [
                        {'id': 'be1', 'source': 'body_1', 'sourcePort': 'default',
                         'target': 'body_2', 'targetPort': 'default'},
                    ],
                }
            }},
            {'id': 'body_1', 'type': 'tool', 'config': {}},
            {'id': 'body_2', 'type': 'tool', 'config': {}},
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    loop_node = migrated['nodes'][0]
    assert loop_node['config']['loopConfig'] == {'maxIterations': 5}

    edge_ports = {(e['source'], e['sourcePort'], e['target'], e['targetPort']) for e in migrated['edges']}
    assert ('loop-1', 'body', 'body_1', 'default') in edge_ports
    assert ('body_1', 'default', 'body_2', 'default') in edge_ports


def test_migrate_loop_body_edge_idempotent():
    """已存在 loop.body 边时不再重复生成。"""
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {'id': 'loop-1', 'type': 'loop', 'config': {
                'loopConfig': {
                    'maxIterations': 5,
                    'bodyNodeIds': ['body_1'],
                    'bodyEdges': [],
                }
            }},
            {'id': 'body_1', 'type': 'tool', 'config': {}},
        ],
        'edges': [
            {'id': 'existing-body', 'source': 'loop-1', 'sourcePort': 'body',
             'target': 'body_1', 'targetPort': 'default'},
        ],
    }
    migrated = _migrate_definition(raw)
    body_edges = [e for e in migrated['edges']
                  if e['source'] == 'loop-1' and e['sourcePort'] == 'body']
    assert len(body_edges) == 1
    assert body_edges[0]['id'] == 'existing-body'


def test_migrate_loop_single_node_body_promoted():
    """最常见的旧形态：循环体里只有一个节点，bodyEdges 为空，应生成 loop.body 边。"""
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {'id': 'loop-1', 'type': 'loop', 'config': {
                'loopConfig': {
                    'maxIterations': 5,
                    'bodyNodeIds': ['body_1'],
                    'bodyEdges': [],
                }
            }},
            {'id': 'body_1', 'type': 'tool', 'config': {}},
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    loop_node = migrated['nodes'][0]
    assert loop_node['config']['loopConfig'] == {'maxIterations': 5}
    edge_ports = {(e['source'], e['sourcePort'], e['target'], e['targetPort']) for e in migrated['edges']}
    assert ('loop-1', 'body', 'body_1', 'default') in edge_ports


def test_migrate_loop_cycle_preserves_body_node_ids():
    """bodyEdges 成环导致无法确定入口时，应保留 bodyNodeIds 供人工修复。"""
    raw = {
        'id': 'wf-1',
        'name': 'Test',
        'nodes': [
            {'id': 'loop-1', 'type': 'loop', 'config': {
                'loopConfig': {
                    'maxIterations': 5,
                    'bodyNodeIds': ['body_1', 'body_2'],
                    'bodyEdges': [
                        {'id': 'be1', 'source': 'body_1', 'sourcePort': 'default',
                         'target': 'body_2', 'targetPort': 'default'},
                        {'id': 'be2', 'source': 'body_2', 'sourcePort': 'default',
                         'target': 'body_1', 'targetPort': 'default'},
                    ],
                }
            }},
            {'id': 'body_1', 'type': 'tool', 'config': {}},
            {'id': 'body_2', 'type': 'tool', 'config': {}},
        ],
        'edges': [],
    }
    migrated = _migrate_definition(raw)
    loop_node = migrated['nodes'][0]
    lc = loop_node['config']['loopConfig']
    assert lc['maxIterations'] == 5
    assert lc.get('bodyNodeIds') == ['body_1', 'body_2']
    assert len(lc.get('bodyEdges', [])) == 2
    assert not any(e['source'] == 'loop-1' and e['sourcePort'] == 'body' for e in migrated['edges'])


@pytest.mark.anyio
async def test_save_preserves_run_metadata_after_touch(tmp_path, monkeypatch):
    """save() 不应让客户端陈旧的 lastRunAt/runCount 覆盖 touch_run_metadata 写入的运行元数据。

    回归场景：运行后 touch_run_metadata 更新了服务端 lastRunAt/runCount，但前端 store
    仍持有运行前的陈旧值；用户再次保存时，PUT body 带陈旧值，若 save() 不保留服务端值，
    会让 lastRunAt 倒退、runCount 卡在初始值+1，破坏 Launcher 的「最近」排序。
    """
    import services.workflow_service as workflow_service_module
    monkeypatch.setattr(
        workflow_service_module, 'WORKFLOWS_FILE', str(tmp_path / 'workflows.json')
    )

    # 1. 创建工作流
    definition = _dict_to_definition({
        'id': 'wf-meta', 'name': 'Meta', 'nodes': [], 'edges': [],
    })
    await save(definition)
    assert definition.run_count == 0
    assert definition.last_run_at is None

    # 2. 模拟一次运行：touch_run_metadata 更新服务端 lastRunAt/runCount
    run_time = 1_700_000_000_000
    await touch_run_metadata('wf-meta', run_time)
    summary = next(s for s in await list_all() if s['id'] == 'wf-meta')
    assert summary['lastRunAt'] == run_time
    assert summary['runCount'] == 1

    # 3. 模拟前端带着运行前的陈旧 lastRunAt/runCount 再次保存
    stale_def = _dict_to_definition({
        'id': 'wf-meta', 'name': 'Meta Renamed', 'nodes': [], 'edges': [],
        'lastRunAt': None, 'runCount': 0,
    })
    await save(stale_def)

    # 4. 服务端运行元数据应被保留，未被陈旧值覆盖
    summary = next(s for s in await list_all() if s['id'] == 'wf-meta')
    assert summary['lastRunAt'] == run_time
    assert summary['runCount'] == 1
    assert summary['name'] == 'Meta Renamed'


@pytest.mark.anyio
async def test_run_count_accumulates_across_runs(tmp_path, monkeypatch):
    """连续多次运行后 runCount 应正确累加，不被每次保存前的陈旧值复位。"""
    import services.workflow_service as workflow_service_module
    monkeypatch.setattr(
        workflow_service_module, 'WORKFLOWS_FILE', str(tmp_path / 'workflows.json')
    )

    await save(_dict_to_definition({
        'id': 'wf-acc', 'name': 'Acc', 'nodes': [], 'edges': [],
    }))

    for i in range(3):
        await touch_run_metadata('wf-acc', 1_700_000_000_000 + i)
        # 每次运行后都模拟前端用陈旧 runCount=0 保存（运行前的值）
        await save(_dict_to_definition({
            'id': 'wf-acc', 'name': 'Acc', 'nodes': [], 'edges': [],
            'lastRunAt': None, 'runCount': 0,
        }))

    summary = next(s for s in await list_all() if s['id'] == 'wf-acc')
    assert summary['runCount'] == 3
    assert summary['lastRunAt'] == 1_700_000_000_002
