"""
Skill 路由器。

负责扫描 skills 目录、读取 Skill 元信息，并根据当前阶段动态筛选
可用的 prompt 片段和工具集合。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from .task_state import TaskPhase
from ..skills import SkillDefinition
from ..tools import BaseTool

logger = logging.getLogger(__name__)


PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}


class SkillRouter:
    """根据任务阶段动态筛选 Skill。"""

    def __init__(self, skills_dir: Optional[Union[str, Path]] = None):
        default_dir = Path(__file__).resolve().parent.parent / "skills"
        self.skills_dir = Path(skills_dir) if skills_dir else default_dir
        self.skills: List[SkillDefinition] = self._load_all_skills()

        logger.info(
            "SkillRouter 初始化完成: skills_dir=%s, loaded_skills=%s",
            self.skills_dir,
            len(self.skills),
        )

    def _load_all_skills(self) -> List[SkillDefinition]:
        """扫描目录并加载所有 Skill 清单。"""
        if not self.skills_dir.exists():
            logger.warning("Skill 目录不存在: %s", self.skills_dir)
            return []

        loaded_skills: List[SkillDefinition] = []

        for skill_dir in sorted(path for path in self.skills_dir.iterdir() if path.is_dir()):
            manifest_path = skill_dir / "SKILL.yaml"
            if not manifest_path.exists():
                continue

            skill = self._load_single_skill(skill_dir, manifest_path)
            if skill is not None:
                loaded_skills.append(skill)

        loaded_skills.sort(key=self._sort_key)
        return loaded_skills

    def _load_single_skill(self, skill_dir: Path, manifest_path: Path) -> Optional[SkillDefinition]:
        """加载单个 Skill 的清单和 prompt。"""
        try:
            manifest = self._load_manifest(manifest_path)

            prompt_path = skill_dir / "prompt.md"
            prompt_fragment = ""
            if prompt_path.exists():
                prompt_fragment = prompt_path.read_text(encoding="utf-8").strip()

            return SkillDefinition(
                name=manifest.get("name", skill_dir.name),
                description=manifest.get("description", ""),
                version=str(manifest.get("version", "1.0")),
                active_phases=list(manifest.get("active_phases", [])),
                tool_names=list(manifest.get("tools", [])),
                priority=str(manifest.get("priority", "normal")),
                dependencies=list(manifest.get("dependencies", [])),
                prompt_fragment=prompt_fragment,
                skill_dir=skill_dir,
            )
        except Exception as error:
            logger.error("加载 Skill 失败: skill_dir=%s, error=%s", skill_dir, error)
            return None

    def _load_manifest(self, manifest_path: Path) -> dict:
        """
        读取 Skill 清单。

        优先使用 pyyaml；如果当前环境没有安装，则回退到一个只支持
        当前项目清单格式的轻量解析器。
        """
        try:
            import yaml
        except ImportError:
            logger.warning("未安装 pyyaml，使用轻量解析器读取: %s", manifest_path)
            return self._parse_simple_yaml(manifest_path)

        with open(manifest_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def _parse_simple_yaml(self, manifest_path: Path) -> dict:
        """
        解析当前项目用到的简化 YAML。

        支持的格式：
        - key: value
        - key:
            - item1
            - item2
        """
        manifest: dict = {}
        current_list_key: Optional[str] = None

        with open(manifest_path, "r", encoding="utf-8") as file:
            for raw_line in file:
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                if stripped.startswith("- "):
                    if current_list_key and isinstance(manifest.get(current_list_key), list):
                        manifest[current_list_key].append(self._clean_yaml_value(stripped[2:]))
                    continue

                if ":" not in stripped:
                    continue

                key, raw_value = stripped.split(":", 1)
                key = key.strip()
                value = raw_value.strip()

                if not value:
                    manifest[key] = []
                    current_list_key = key
                    continue

                if value == "[]":
                    manifest[key] = []
                    current_list_key = None
                    continue

                if value == "{}":
                    manifest[key] = {}
                    current_list_key = None
                    continue

                manifest[key] = self._clean_yaml_value(value)
                current_list_key = None

        return manifest

    def _clean_yaml_value(self, value: str) -> str:
        """清理简单 YAML 中的字符串值。"""
        return value.strip().strip('"').strip("'")

    def _sort_key(self, skill: SkillDefinition) -> tuple:
        """统一控制 Skill 的排序顺序。"""
        priority_value = PRIORITY_ORDER.get(skill.priority, PRIORITY_ORDER["normal"])
        return (priority_value, skill.name)

    def _normalize_phase(self, phase: Union[str, TaskPhase]) -> str:
        """统一 phase 输入格式。"""
        if isinstance(phase, TaskPhase):
            return phase.value
        return phase

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """按名称查找 Skill。"""
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

    def get_active_skills(self, phase: Union[str, TaskPhase]) -> List[SkillDefinition]:
        """获取某个阶段当前应激活的 Skill 列表。"""
        normalized_phase = self._normalize_phase(phase)
        return [skill for skill in self.skills if skill.is_active_for_phase(normalized_phase)]

    def get_active_tool_names(self, phase: Union[str, TaskPhase]) -> List[str]:
        """获取当前阶段的去重工具名列表。"""
        tool_names: List[str] = []
        seen = set()

        for skill in self.get_active_skills(phase):
            for tool_name in skill.tool_names:
                if tool_name in seen:
                    continue
                seen.add(tool_name)
                tool_names.append(tool_name)

        return tool_names

    def get_prompt_fragments(self, phase: Union[str, TaskPhase]) -> List[str]:
        """获取当前阶段所有 Skill 的 prompt 片段。"""
        fragments: List[str] = []
        for skill in self.get_active_skills(phase):
            if skill.prompt_fragment:
                fragments.append(skill.prompt_fragment)
        return fragments

    def build_phase_prompt(self, phase: Union[str, TaskPhase]) -> str:
        """
        组合当前阶段的 Skill Prompt。

        返回值可以直接拼接到主 system prompt 后面。
        """
        normalized_phase = self._normalize_phase(phase)
        active_skills = self.get_active_skills(normalized_phase)

        if not active_skills:
            return ""

        sections = [
            f"## 当前任务阶段\n{normalized_phase}",
            "## 当前激活 Skills",
            "\n".join(f"- {skill.name}: {skill.description}" for skill in active_skills),
        ]

        for skill in active_skills:
            if not skill.prompt_fragment:
                continue
            sections.append(f"## Skill Prompt: {skill.name}\n{skill.prompt_fragment}")

        return "\n\n".join(sections).strip()

    def resolve_tools(
        self,
        phase: Union[str, TaskPhase],
        available_tools: Union[Dict[str, BaseTool], Iterable[BaseTool]],
    ) -> List[BaseTool]:
        """
        根据当前阶段，从已有工具实例中筛出应激活的工具。

        这里不负责创建工具实例，只做“按阶段过滤”的工作。
        """
        if isinstance(available_tools, dict):
            tool_map = available_tools
        else:
            tool_map = {tool.name: tool for tool in available_tools}

        resolved_tools: List[BaseTool] = []
        missing_tools: List[str] = []

        for tool_name in self.get_active_tool_names(phase):
            tool = tool_map.get(tool_name)
            if tool is None:
                missing_tools.append(tool_name)
                continue
            resolved_tools.append(tool)

        if missing_tools:
            logger.warning("部分 Skill 工具尚未注册: %s", ", ".join(missing_tools))

        return resolved_tools
