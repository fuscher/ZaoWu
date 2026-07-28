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
    assert lc['mode'] == 'canvas'
    assert lc['maxIterations'] == 10
    assert 'condition' not in lc
    assert 'iterateOver' not in lc


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
    assert edge['sourcePort'] == 'out_end'
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
