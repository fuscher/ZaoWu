"""意图与结论性信号匹配（阶段 B1，设计文档 §3.3.6 + §6.3 B1）。

- ``IntentMatcher``：识别「承诺执行但未调用工具」的文本（说而不做）。
  承诺执行类中英正则 + 建议性负则排除（"建议你手动删除 X" 是建议不是承诺）。
- ``ConclusiveSignalMatcher``：判定文本是否含结论性信号（J 分支分界）：
  (a) 代码块；(b) 结论性关键词（强完成语义，裸"建议/已经/result"不入选）；
  (c) 陈述句长度（≥40 字符且 ≥2 个句末标点）。

纯函数模块，无 IO 无副作用，便于单测；阈值构造参数可配（默认值纳入标注集验证）。
"""
from __future__ import annotations

import re
from typing import List, Optional

# ── IntentMatcher：承诺执行类意图 ─────────────────────────────

# 承诺执行类强信号（说而不做检测的命中条件）
_COMMIT_INTENT_PATTERNS: List[str] = [
    # 中文
    r'我先读取', r'让我检查', r'接下来调用', r'我将修改',
    r'我来读取', r'我去查看',
    # 英文（\b 防 "I'll read" 误配 "I'll readability" 之类）
    r"I'll read", r'let me check', r'going to edit',
    r'I will modify', r'let me look at',
]
_COMMIT_INTENT_RE = re.compile(
    '|'.join(f'(?:{p})' for p in _COMMIT_INTENT_PATTERNS),
    re.IGNORECASE,
)

# 建议性弱信号：命中则整段不算承诺（"我先读取…但我建议你手动删除" → 负例）
_ADVISORY_PATTERNS: List[str] = [
    r'建议你', r'我建议你', r'你可以', r'你最好',
    r'i suggest', r'i recommend', r'you could', r'you can',
]
_ADVISORY_RE = re.compile(
    '|'.join(f'(?:{p})' for p in _ADVISORY_PATTERNS),
    re.IGNORECASE,
)

_MIN_INTENT_TEXT_LEN = 4  # 过短文本（如"嗯"/"好"）直接不算承诺


class IntentMatcher:
    """承诺执行类意图匹配（说而不做检测）。

    ``matches(text)`` 返回 True ⟺ 文本含承诺执行类表达 且 不含建议性弱信号。
    """

    def __init__(self,
                 commit_patterns: Optional[List[str]] = None,
                 advisory_patterns: Optional[List[str]] = None,
                 min_text_len: int = _MIN_INTENT_TEXT_LEN) -> None:
        self._commit_re = re.compile(
            '|'.join(f'(?:{p})' for p in (commit_patterns or _COMMIT_INTENT_PATTERNS)),
            re.IGNORECASE,
        )
        self._advisory_re = re.compile(
            '|'.join(f'(?:{p})' for p in (advisory_patterns or _ADVISORY_PATTERNS)),
            re.IGNORECASE,
        )
        self._min_text_len = min_text_len

    def matches(self, text: str) -> bool:
        if not text or len(text.strip()) < self._min_text_len:
            return False
        if self._advisory_re.search(text):
            return False  # 建议性弱信号整段排除（负例）
        return bool(self._commit_re.search(text))


# ── ConclusiveSignalMatcher：结论性信号（§3.3.6 三规则） ──────

# (a) 代码块：三反引号围栏，或 ≥1 处行内反引号
_CODE_FENCE_RE = re.compile(r'```[\s\S]*?```')
_INLINE_CODE_RE = re.compile(r'`[^`\n]+`')

# (b) 结论性关键词（仅强完成语义短语；裸"建议/已经/result"不入选，
#     建议性前缀"建议你/you could"由负则兜底为 idle）
# 注意："定位到"**不**入选（承诺变体"我先定位到问题所在"会误判 success）；
# 完成语义由"已定位到"承载（已完成陈述）。
_CONCLUSIVE_ZH = (
    r'结论是|综上所述|最终建议|我的建议是|建议如下|原因是|问题在于|'
    r'根因是|已定位到|已经完成|已完成|完成了|修改了|结果是'
)
_CONCLUSIVE_EN = (
    r'in conclusion|in summary|my recommendation is|my suggestion is|'
    r'the (?:issue|root cause|problem) is|'
    r"i've (?:fixed|updated|modified|found)|result is"
)
_CONCLUSIVE_RE = re.compile(
    f'(?:{_CONCLUSIVE_ZH})|(?:{_CONCLUSIVE_EN})',
    re.IGNORECASE,
)

# 建议性排除（与 IntentMatcher 负则同源，命中则 (b) 不成立）
_CONCLUSIVE_ADVISORY_RE = re.compile(
    '|'.join(f'(?:{p})' for p in _ADVISORY_PATTERNS),
    re.IGNORECASE,
)

_SENTENCE_END_CHARS = '。！？.!?'

_DEFAULT_MIN_SENTENCE_LEN = 40   # (c) 陈述句最小字符数
_DEFAULT_MIN_SENTENCE_ENDS = 2   # (c) 句末标点最小个数


class ConclusiveSignalMatcher:
    """文本含结论性信号 ⟺ 命中 (a) 代码块 | (b) 结论词 | (c) 陈述句长度。

    (c) 用 ``str.count`` 计句末标点而非正则，避免 ``.`` 误吞小数/缩写。
    """

    def __init__(self,
                 min_sentence_len: int = _DEFAULT_MIN_SENTENCE_LEN,
                 min_sentence_ends: int = _DEFAULT_MIN_SENTENCE_ENDS) -> None:
        self._min_sentence_len = min_sentence_len
        self._min_sentence_ends = min_sentence_ends

    def is_conclusive(self, text: str) -> bool:
        if not text:
            return False
        if _CODE_FENCE_RE.search(text):
            return True
        if _INLINE_CODE_RE.search(text):
            return True
        if _CONCLUSIVE_RE.search(text) and not _CONCLUSIVE_ADVISORY_RE.search(text):
            return True
        # (c) 陈述句长度：≥ 40 字符 且 ≥ 2 个句末标点
        if (len(text) >= self._min_sentence_len
                and sum(text.count(c) for c in _SENTENCE_END_CHARS) >= self._min_sentence_ends):
            return True
        return False
