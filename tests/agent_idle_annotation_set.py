"""空转识别标注集（设计文档 §8.2 / D1）— 53 条人工标注的 text-only 轮次样本。

28 正例 = 应判 idle/constrained（说而不做）：
- 承诺类 20 条（"我先读取…"、"让我检查…" 等有承诺无执行的文本）
- 陷阱类 8 条（"建议你手动删除 X"——建议非承诺、无结论信号 → 应 idle；
  "我先定位…"——承诺性定位短语、无结论信号 → 应 idle，防 D1 漏测）
25 负例 = 应判 success（正常结论）：
- 结论词 20 条（"结论是/综上所述/已经完成…" 等强完成语义）
- 代码块 5 条（含三反引号围栏或行内反引号代码）

本文件不以 test_ 开头，不被 pytest 收集；指标断言在 tests/test_agent_service.py。
样本来源：历史 agent 对话采样 + 人工构造边界 case。
"""
from __future__ import annotations

# (text, preset, expected_idle) —— expected_idle=True 表示应判为 idle/constrained
# （即"说而不做"或"被约束"）；False 表示应判 success（正常结论）。
ANNOTATION_SET: list = [
    # ── 正例 1-20：承诺执行类（build 模式） ──────────────────
    ('我先读取这个文件看看', 'build', True),
    ('让我检查一下配置', 'build', True),
    ('接下来调用 read_file 读取源码', 'build', True),
    ('我将修改 src/main.py', 'build', True),
    ('我来读取测试文件', 'build', True),
    ('我去查看一下日志', 'build', True),
    ('让我检查一下这个报错', 'build', True),
    ('我先读取 auth 模块的代码', 'build', True),
    ('接下来调用 git_status 看看状态', 'build', True),
    ('我将修改这个 bug', 'build', True),
    ("I'll read the file first", 'build', True),
    ('let me check the config', 'build', True),
    ('going to edit src/main.py', 'build', True),
    ('I will modify this function', 'build', True),
    ('let me look at the tests', 'build', True),
    ('我先读取一下，然后继续', 'build', True),
    ('让我检查运行日志确认', 'build', True),
    ('我来读取项目结构再动手', 'build', True),
    ('我去查看 git 历史', 'build', True),
    ('接下来调用工具处理', 'build', True),
    # ── 正例 21-28：陷阱类（无结论信号 → idle） ──────────────
    ('建议你手动删除那个文件', 'build', True),
    ('我建议你先重启一下服务', 'build', True),
    ('你可以直接修改这个配置', 'build', True),
    ('建议你检查一下网络', 'build', True),
    ('我建议你换个更大的模型', 'build', True),
    # 承诺变体：承诺性"定位"短语——无结论信号（未命中断言/结论词），应 idle。
    # 防御回归：IntentMatcher 若把"我先定位"误判为结论性（漏加意图模式）→ 此样本防 D1 漏测
    ('我先定位这个 bug', 'build', True),
    ('我先定位问题所在', 'build', True),
    ('让我先定位一下', 'build', True),
    # 危险变体（2026-08-07 修正）："我先定位到问题所在"——承诺未兑现但含"到"，
    # 若 (b) 结论词保留"定位到"会被误判 success（样本恰好避开的变体，现补上）
    ('我先定位到问题所在', 'build', True),
    # ── 负例 1-20：结论性关键词（success） ───────────────────
    ('结论是这里存在内存泄漏', 'build', False),
    ('综上所述，问题出在缓存未失效', 'build', False),
    ('我的建议是改用异步 IO', 'build', False),
    ('原因是登录态过期了', 'build', False),
    ('问题在于依赖版本冲突', 'build', False),
    ('已定位到内存泄漏在缓存层', 'build', False),
    ('根因是配置文件缺少 key', 'build', False),
    ('已经完成全部修改', 'build', False),
    ('已完成代码审查', 'build', False),
    ('修改了 main.py 第 42 行', 'build', False),
    ('结果是测试全部通过', 'build', False),
    ('建议如下：先升级依赖', 'build', False),
    ('最终建议是保持现状', 'build', False),
    ('the issue is the cache never invalidates', 'build', False),
    ('in conclusion, the bug is in auth', 'build', False),
    ("i've fixed the timeout issue", 'build', False),
    ("i've updated the dependency", 'build', False),
    ('my recommendation is to use asyncio', 'build', False),
    ('the root cause is the config key', 'build', False),
    ('result is all tests pass now', 'build', False),
    # ── 负例 21-25：代码块（success） ────────────────────────
    ('代码如下：```python\nx = 1\n```', 'build', False),
    ('函数签名是 `def foo()`', 'build', False),
    ('修复方案：\n```python\nretry(3)\n```', 'build', False),
    ('调用方式见 `run_command`', 'build', False),
    ('输出：\n```\nhello\n```', 'build', False),
]
