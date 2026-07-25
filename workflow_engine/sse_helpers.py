from __future__ import annotations

import time
import uuid
from workflow_engine.context import ExecutionContext, NodeContext


def _now_ms() -> int:
    """当前时间戳（毫秒）。"""
    return int(time.time() * 1000)


def _generate_run_id() -> str:
    """生成唯一 run ID（uuid4 去连字符）。"""
    return uuid.uuid4().hex


def _sse_wf_started(ctx: ExecutionContext, start_time: float) -> dict:
    return {'type': 'wf_started', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'startTime': start_time}


def _sse_node_started(ctx: ExecutionContext, ctx_node: NodeContext) -> dict:
    return {'type': 'node_started', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'nodeId': ctx_node.node_id, 'input': ctx_node.inputs}


def _sse_node_progress(ctx: ExecutionContext, ctx_node: NodeContext, delta: str) -> dict:
    return {'type': 'node_progress', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'nodeId': ctx_node.node_id, 'delta': delta}


def _sse_node_ended(ctx: ExecutionContext, ctx_node: NodeContext) -> dict:
    return {'type': 'node_ended', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'nodeId': ctx_node.node_id, 'output': ctx_node.outputs,
            'tokens': ctx_node.tokens_in + ctx_node.tokens_out,
            'elapsedMs': int(ctx_node.elapsed_ms)}


def _sse_node_errored(ctx: ExecutionContext, ctx_node: NodeContext, error: str,
                      retry_attempt: int = 0) -> dict:
    return {'type': 'node_errored', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'nodeId': ctx_node.node_id, 'error': error, 'retryAttempt': retry_attempt}


def _sse_edge_crossed(ctx: ExecutionContext, source: str, target: str) -> dict:
    return {'type': 'edge_crossed', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'sourceNodeId': source, 'targetNodeId': target}


def _sse_wf_completed(ctx: ExecutionContext, total_tokens: int) -> dict:
    return {'type': 'wf_completed', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id,
            'endTime': _now_ms(), 'totalTokens': total_tokens}


def _sse_wf_errored(workflow_id: str, run_id: str, error: str) -> dict:
    return {'type': 'wf_errored', 'workflowId': workflow_id, 'runId': run_id, 'error': error}


def _sse_node_requires_confirmation(ctx: ExecutionContext, ctx_node: NodeContext,
                                    tool_call: dict) -> dict:
    return {'type': 'node_requires_confirmation', 'workflowId': ctx.workflow_id,
            'runId': ctx.run_id, 'nodeId': ctx_node.node_id, 'toolCall': tool_call}


def _sse_wf_paused(ctx: ExecutionContext, reason: str) -> dict:
    return {'type': 'wf_paused', 'workflowId': ctx.workflow_id,
            'runId': ctx.run_id, 'pauseReason': reason}


def _sse_wf_resumed(ctx: ExecutionContext) -> dict:
    return {'type': 'wf_resumed', 'workflowId': ctx.workflow_id, 'runId': ctx.run_id}
