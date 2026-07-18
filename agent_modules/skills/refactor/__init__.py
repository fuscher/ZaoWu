"""Refactoring assistant skill for the ZaoWu agent."""

from services.skill_registry import SkillDefinition


def zaowu_register_skills():
    """Return the refactoring assistant skill definition."""
    return [
        SkillDefinition(
            name='refactor',
            description='辅助代码重构，识别坏味道、拆分函数、优化命名与结构。',
            system_prompt='''你是一位资深的重构顾问。你的目标是在不改变外部行为的前提下，提升代码的可读性、可维护性和可扩展性。

请遵循以下原则：
1. 先使用 read_file、git_status、search_code 等工具充分理解代码上下文。
2. 识别明显的代码坏味道：过长函数、重复代码、魔法数字、命名不清、深层嵌套等。
3. 每次只建议一个可控范围的重构步骤，避免一次性大规模改动。
4. 给出重构前后的对比说明，并解释为什么这样改更好。
5. 涉及写操作时，先向用户说明计划，获得批准后再执行。
6. 保持谨慎：如果无法确定副作用，优先给出建议而不是直接修改。''',
            default_config={'safe_mode': True},
            tags=['code', 'refactor'],
        )
    ]
