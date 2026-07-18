"""Documentation generation skill for the ZaoWu agent."""

from services.skill_registry import SkillDefinition


def zaowu_register_skills():
    """Return the documentation generation skill definition."""
    return [
        SkillDefinition(
            name='doc_generate',
            description='为项目生成清晰、结构化的 README、API 文档或代码注释。',
            system_prompt='''你是一位技术文档专家。你的任务是为代码库生成清晰、准确、结构化的文档。

请遵循以下原则：
1. 在生成文档前，先使用 list_files、read_file、search_code 等工具了解项目结构和关键代码。
2. 根据项目类型选择合适的文档模板（README、API 文档、模块说明等）。
3. 文档应包含：项目简介、目录结构、核心功能说明、使用示例和贡献指南（如适用）。
4. 对于代码注释，重点说明函数/类的职责、参数、返回值和可能的异常。
5. 使用与用户消息相同的语言撰写文档。
6. 生成内容前，优先向用户确认文档范围和目标受众。
7. 涉及写文件时，先说明计划并获得批准。''',
            default_config={'format': 'markdown', 'include_examples': True},
            tags=['docs', 'writing'],
        )
    ]
