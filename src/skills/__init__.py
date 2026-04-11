"""
Skill 基础定义。

该包用于承载新的 Skill-Based Agent 架构相关的静态配置和抽象模型。
当前阶段先提供 SkillDefinition，后续再逐步迁移更多运行逻辑。
"""

from .base import SkillDefinition

__all__ = ["SkillDefinition"]
