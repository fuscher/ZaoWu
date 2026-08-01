import pytest

from services.workflow_service import _migrate_definition


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
