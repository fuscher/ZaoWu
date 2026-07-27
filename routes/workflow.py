from __future__ import annotations

from quart import Blueprint, request, jsonify, Response
import asyncio
import json
from services import workflow_service
from services.workflow_service import _dict_to_definition, _definition_to_dict
from services.tool_registry import ToolRegistry
from workflow_engine.executor import WorkflowExecutor, execute_workflow
from workflow_engine.sse_helpers import _generate_run_id

workflow_bp = Blueprint('workflow', __name__)
stop_events: dict[str, asyncio.Event] = {}


def _confirm_key(workflow_id: str, run_id: str) -> tuple[str, str]:
    return (workflow_id, run_id)


_workflow_pending_ids: dict[tuple[str, str], set[str]] = {}
_workflow_confirmations: dict[tuple[str, str], dict[str, asyncio.Event]] = {}
_workflow_confirmation_results: dict[tuple[str, str], dict[str, bool]] = {}


def _register_pending_id(workflow_id: str, run_id: str, node_id: str, tool_call: dict) -> None:
    request_id = (tool_call or {}).get('requestId')
    if not request_id:
        return
    key = _confirm_key(workflow_id, run_id)
    _workflow_pending_ids.setdefault(key, set()).add(request_id)


@workflow_bp.route('/<workflow_id>/run', methods=['POST'])
async def run_workflow(workflow_id):
    definition = await workflow_service.load(workflow_id)
    if not definition:
        return jsonify({'ok': False, 'error': 'workflow not found'}), 404

    executor = WorkflowExecutor(definition)
    errors = executor.validate()
    if errors:
        return jsonify({'ok': False, 'errors': errors}), 400

    body = await request.get_json(silent=True) or {}
    initial_input = body.get('initialInput', '')

    run_id = _generate_run_id()
    stop_events[run_id] = asyncio.Event()

    async def generate():
        try:
            async for event in execute_workflow(
                definition,
                stop_events[run_id],
                confirm_callback=lambda node_id, tc: _wait_confirmation(workflow_id, run_id, node_id, tc),
                run_id=run_id,
                initial_input=initial_input,
                register_pending_callback=lambda workflow_id_inner, node_id, tc: _register_pending_id(workflow_id_inner, run_id, node_id, tc),
            ):
                yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
        except Exception as e:
            fallback = {'type': 'wf_errored', 'workflowId': workflow_id, 'runId': run_id, 'error': f'SSE 异常: {e}'}
            yield f'data: {json.dumps(fallback, ensure_ascii=False)}\n\n'
        finally:
            stop_events.pop(run_id, None)
            key = _confirm_key(workflow_id, run_id)
            _workflow_pending_ids.pop(key, None)
            _workflow_confirmations.pop(key, None)
            _workflow_confirmation_results.pop(key, None)

    return Response(
        generate(),
        mimetype='text/event-stream; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'X-Run-Id': run_id,
        }
    )


@workflow_bp.route('/<workflow_id>/run/stop', methods=['POST'])
async def stop_workflow(workflow_id):
    body = await request.get_json(silent=True)
    run_id = body.get('runId') if body else None
    if run_id and run_id in stop_events:
        stop_events[run_id].set()
        key = _confirm_key(workflow_id, run_id)
        run_conf = _workflow_confirmations.get(key)
        if run_conf:
            _workflow_confirmation_results.setdefault(key, {})
            for req_id in list(run_conf.keys()):
                _workflow_confirmation_results[key][req_id] = False
                run_conf[req_id].set()
    return jsonify({'ok': True})


@workflow_bp.route('', methods=['GET'])
async def list_workflows():
    summaries = await workflow_service.list_all()
    return jsonify({'ok': True, 'workflows': summaries})


@workflow_bp.route('', methods=['POST'])
async def create_workflow():
    body = await request.get_json(silent=True) or {}
    if not body.get('name'):
        return jsonify({'ok': False, 'error': 'name 必填'}), 400
    if not body.get('id'):
        body['id'] = f'wf-{_generate_run_id()[:8]}'
    definition = _dict_to_definition(body)
    saved = await workflow_service.save(definition)
    return jsonify({'ok': True, 'workflow': _definition_to_dict(saved)}), 201


@workflow_bp.route('/<workflow_id>', methods=['GET'])
async def get_workflow(workflow_id):
    definition = await workflow_service.load(workflow_id)
    if not definition:
        return jsonify({'ok': False, 'error': 'workflow not found'}), 404
    return jsonify({'ok': True, 'workflow': _definition_to_dict(definition)})


@workflow_bp.route('/<workflow_id>', methods=['PUT'])
async def update_workflow(workflow_id):
    body = await request.get_json(silent=True) or {}
    body['id'] = workflow_id
    definition = _dict_to_definition(body)
    existing = await workflow_service.load(workflow_id)
    if not existing:
        return jsonify({'ok': False, 'error': 'workflow not found'}), 404
    saved = await workflow_service.save(definition)
    return jsonify({'ok': True, 'workflow': _definition_to_dict(saved)})


@workflow_bp.route('/<workflow_id>', methods=['DELETE'])
async def delete_workflow(workflow_id):
    ok = await workflow_service.delete(workflow_id)
    if not ok:
        return jsonify({'ok': False, 'error': 'workflow not found'}), 404
    return jsonify({'ok': True})


@workflow_bp.route('/<workflow_id>/runs', methods=['GET'])
async def list_runs(workflow_id):
    runs = await workflow_service.list_runs(workflow_id)
    return jsonify({'ok': True, 'runs': runs})


@workflow_bp.route('/<workflow_id>/export', methods=['POST'])
async def export_workflow(workflow_id):
    body = await request.get_json(silent=True) or {}
    file_path = body.get('filePath')
    if not file_path:
        return jsonify({'ok': False, 'error': 'filePath 必填'}), 400
    try:
        await workflow_service.export_to_file(workflow_id, file_path)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True})


async def _wait_confirmation(workflow_id: str, run_id: str, node_id: str, tool_call: dict) -> bool:
    request_id = tool_call['requestId']
    key = _confirm_key(workflow_id, run_id)
    run_conf = _workflow_confirmations.setdefault(key, {})
    run_results = _workflow_confirmation_results.setdefault(key, {})

    if request_id in run_results:
        return run_results.pop(request_id)

    event = asyncio.Event()
    run_conf[request_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=60)
        return run_results.pop(request_id, False)
    except asyncio.TimeoutError:
        return False
    finally:
        run_conf.pop(request_id, None)
        pending = _workflow_pending_ids.get(key)
        if pending:
            pending.discard(request_id)


@workflow_bp.route('/<workflow_id>/confirm-tool', methods=['POST'])
async def confirm_tool(workflow_id):
    body = await request.get_json(silent=True) or {}
    run_id = body.get('runId')
    request_id = body.get('requestId')
    approved = body.get('approved')

    if not run_id or not request_id or not isinstance(approved, bool):
        return jsonify({'ok': False, 'error': 'invalid params'}), 400

    key = _confirm_key(workflow_id, run_id)

    pending = _workflow_pending_ids.get(key)
    if not pending or request_id not in pending:
        return jsonify({'ok': False, 'error': 'confirmation not found'}), 410

    _workflow_confirmation_results.setdefault(key, {})[request_id] = approved

    run_conf = _workflow_confirmations.get(key)
    if run_conf and request_id in run_conf:
        run_conf[request_id].set()

    return jsonify({'ok': True})


@workflow_bp.route('/tools', methods=['GET'])
async def list_tools():
    """返回 ToolRegistry 中全部工具定义（含 JSON Schema 参数），供前端动态表单使用。"""
    registry = ToolRegistry.get_instance()
    tools = []
    for t in registry.list_tools().values():
        tools.append({
            'name': t.name,
            'description': t.description,
            'parameters': t.parameters,
            'requiresApproval': t.requires_approval,
            'tags': t.tags,
        })
    return jsonify({'ok': True, 'tools': tools})
