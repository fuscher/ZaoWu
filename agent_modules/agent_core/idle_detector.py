"""完成质量检测（阶段 B2，设计文档 §3.3.1/§3.3.2/§6.3 B2）。

``IdleDetector`` 是纯函数判定器：输入本轮 ``collected_text`` 与跨轮
``full_text``/``executed_tool_names``/``preset``，输出完成质量四态
（success/idle/constrained/empty）+ 动作（终态/空响应重试/纠正注入重试/交接）。

决策流严格对齐 §3.3.2 决策图：
- 无文本：有历史工具 → success 终态；plan → constrained 终态（只读约束下的合理行为）；
  build → 未重试过则 empty+重试一次（对齐原 retried_empty 语义），已重试则 empty 终态
- 有文本 + 写意图：plan → constrained + handoff（交接建议）；build → 首次 idle+纠正重试，
  二次 idle 终态
- 有文本 + 文本化工具调用（E9）：与「说而不做」同构 → 纠正重试一次，二次 idle 终态
- 有文本无写意图：结论性信号 → success 终态；否则 idle 终态（软警告，不重试）

**计数设计**：``empty_retry_count`` 与 ``idle_retry_count`` 独立——空响应重试
（模型抽风，重试是全新机会）与说而不做纠正（消耗一次纠正机会）互不消耗。
避免场景：首轮空响应消耗掉纠正机会后，次轮"我先读取…"直接 idle 终态而拿不到
一次纠正（master 语义「idle 首次可纠正」）。两计数均在实例内维护（process_message
每会话新建，不跨会话/不跨进程），detect 保持纯数据输入便于单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from agent_modules.agent_core.intent_patterns import (
    ConclusiveSignalMatcher, IntentMatcher, ToolTextMatcher,
)

# 完成质量枚举（与 done.quality / messages.metadata.quality 一致）
QUALITY_SUCCESS = 'success'
QUALITY_IDLE = 'idle'
QUALITY_CONSTRAINED = 'constrained'
QUALITY_EMPTY = 'empty'

# 动作枚举
ACTION_TERMINAL = 'terminal'                    # 终态，正常收尾
ACTION_RETRY_EMPTY = 'retry_empty'              # 空响应：重试一次（notice retrying_empty）
ACTION_INJECT_CORRECTION = 'inject_correction_retry'  # 说而不做：纠正注入后重试
ACTION_HANDOFF = 'handoff'                      # constrained：发交接建议后终态

# notice code（对齐 §5.3 枚举）
NOTICE_RETRYING_EMPTY = 'retrying_empty'
NOTICE_INTENT_NOT_EXECUTED = 'intent_not_executed'
NOTICE_PLAN_READY_FOR_BUILD = 'plan_ready_for_build'

# 说而不做纠正消息（§3.3.3；仅注入本轮内存 messages，绝不落库）
# R1 查证（2026-08-07）：role='system' 追加到内存 messages 末尾——llm_stream.py 与
# 路由层均无 system 位置/role 校验，项目走 OpenAI chat/completions 协议（system 允许
# 任意位置），无 provider 兼容风险。保持 system role（纠正指令效力最强）。
CORRECTION_TEMPLATE = (
    '[系统纠正] 你上一轮声明了工具操作意图但未实际调用工具。\n'
    '请要么立即调用对应工具，要么基于已有信息直接给出结论。\n'
    '不要做"先做X"的承诺而不执行。'
)

# S15-E-P0-6（E9）：工具调用文本化纠正消息（形态与 CORRECTION_TEMPLATE 一致，
# 仅注入本轮内存 messages，绝不落库；复用 intent_not_executed 通道一次机会）
TOOL_TEXT_CORRECTION = (
    '[系统纠正] 检测到工具调用以文本形式输出（如 XML/JSON 片段或伪函数调用），'
    '但未实际发起结构化工具调用。\n'
    '请改用结构化的工具调用，或基于已有信息直接给出结论。'
)


@dataclass(frozen=True)
class IdleDecision:
    """IdleDetector.detect 的输出。"""
    quality: str                                   # success | idle | constrained | empty
    action: str                                    # terminal | retry_empty | inject_correction_retry | handoff
    notice_code: Optional[str] = None              # 需发射的 notice code（无则 None）
    correction: Optional[str] = None               # 纠正消息文本（inject_correction_retry 时非空）


class IdleDetector:
    """完成质量判定器（纯函数核心 + 实例内双重试计数）。"""

    def __init__(self,
                 max_retries: int = 1,
                 intent_matcher: Optional[IntentMatcher] = None,
                 conclusive_matcher: Optional[ConclusiveSignalMatcher] = None,
                 tool_text_matcher: Optional[ToolTextMatcher] = None,
                 correction_template: str = CORRECTION_TEMPLATE,
                 tool_text_correction: str = TOOL_TEXT_CORRECTION) -> None:
        self._max_retries = max_retries
        self._intent_matcher = intent_matcher or IntentMatcher()
        self._conclusive_matcher = conclusive_matcher or ConclusiveSignalMatcher()
        self._tool_text_matcher = tool_text_matcher or ToolTextMatcher()
        self._correction_template = correction_template
        self._tool_text_correction = tool_text_correction
        # 独立计数：空响应重试（empty）与说而不做纠正（idle）互不消耗
        self.empty_retry_count = 0
        self.idle_retry_count = 0

    def reset(self) -> None:
        """清空两个重试计数。

        当前主循环两处重试（retry_empty / inject_correction_retry）均**不**调用
        reset：重试是一次性机会（对齐原 retried_empty 语义），计数保留保证
        "屡教不改"的模型最终以终态收尾而非无限重试。reset 保留为可选的
        纯函数能力（未来按需接入，如用户手动重试）。"""
        self.empty_retry_count = 0
        self.idle_retry_count = 0

    def detect(self, *,
               collected_text: str,
               full_text: str,
               executed_tool_names: List[str],
               preset: str) -> IdleDecision:
        """无工具调用轮（调用方仅在本轮无 tool_call 时进入）的质量判定。"""
        has_text = bool(collected_text)
        has_history_tools = bool(executed_tool_names)
        is_plan = preset == 'plan'

        if not has_text:
            # 无文本：有历史工具 → 摘要 success；plan → constrained（不重试）；
            # build → 未空转重试过则 empty+重试一次，已重试则 empty 终态。
            # 用 empty_retry_count 独立计数，不消耗说而不做的纠正机会。
            if has_history_tools:
                return IdleDecision(QUALITY_SUCCESS, ACTION_TERMINAL)
            if is_plan:
                return IdleDecision(QUALITY_CONSTRAINED, ACTION_TERMINAL)
            if self.empty_retry_count < self._max_retries:
                self.empty_retry_count += 1
                return IdleDecision(
                    QUALITY_EMPTY, ACTION_RETRY_EMPTY, notice_code=NOTICE_RETRYING_EMPTY,
                )
            return IdleDecision(QUALITY_EMPTY, ACTION_TERMINAL)

        # 有文本：先查文本化工具调用（E9）——模型"以为"调了工具但只输出文本
        if self._tool_text_matcher.matches(collected_text):
            if self.idle_retry_count < self._max_retries:
                self.idle_retry_count += 1
                return IdleDecision(
                    QUALITY_IDLE, ACTION_INJECT_CORRECTION,
                    notice_code=NOTICE_INTENT_NOT_EXECUTED,
                    correction=self._tool_text_correction,
                )
            return IdleDecision(QUALITY_IDLE, ACTION_TERMINAL)

        # 有文本：先查写意图（IntentMatcher）
        if self._intent_matcher.matches(collected_text):
            if is_plan:
                # plan 模式想写不能写 → constrained + 交接建议
                return IdleDecision(
                    QUALITY_CONSTRAINED, ACTION_HANDOFF,
                    notice_code=NOTICE_PLAN_READY_FOR_BUILD,
                )
            # build 模式：首次纠正重试（idle_retry_count 独立计数），二次 idle 终态
            if self.idle_retry_count < self._max_retries:
                self.idle_retry_count += 1
                return IdleDecision(
                    QUALITY_IDLE, ACTION_INJECT_CORRECTION,
                    notice_code=NOTICE_INTENT_NOT_EXECUTED,
                    correction=self._correction_template,
                )
            return IdleDecision(QUALITY_IDLE, ACTION_TERMINAL)

        # 无写意图：结论性信号 → success；否则 idle 软警告（不重试）
        if self._conclusive_matcher.is_conclusive(collected_text):
            return IdleDecision(QUALITY_SUCCESS, ACTION_TERMINAL)
        return IdleDecision(QUALITY_IDLE, ACTION_TERMINAL)
