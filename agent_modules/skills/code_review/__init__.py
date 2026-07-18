"""Code review skill for the ZaoWu agent."""

from services.skill_registry import SkillDefinition


def zaowu_register_skills():
    """Return the code review skill definition."""
    return [
        SkillDefinition(
            name='code_review',
            description='对代码文件进行审查，发现潜在问题并给出改进建议。',
            system_prompt='''你是一位资深代码审查专家。请遵循以下原则：
1. 关注 Bug、性能问题、安全风险和可维护性问题。
2. 对每一类问题给出具体文件和行号。
3. 优先给出可执行的修改建议。
4. 保持简洁，避免过度吹毛求疵。''',
            default_config={'max_files': 5},
            tags=['code', 'review'],
        )
    ]
