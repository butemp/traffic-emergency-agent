"""
Skill 抽象定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class SkillDefinition:
    """
    Skill 元信息定义。

    目前只负责描述 Skill 的静态属性，不承载实际工具执行逻辑。
    这样做便于先完成 Skill 的目录化与动态加载，再逐步迁移具体能力。
    """

    name: str
    description: str
    version: str
    active_phases: List[str] = field(default_factory=list)
    tool_names: List[str] = field(default_factory=list)
    priority: str = "normal"
    dependencies: List[str] = field(default_factory=list)
    prompt_fragment: str = ""
    skill_dir: Path = field(default_factory=Path)

    def is_active_for_phase(self, phase: str) -> bool:
        """判断当前 Skill 是否应在指定阶段激活。"""
        return phase in self.active_phases
