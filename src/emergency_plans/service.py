"""应急预案服务（parsered_data 风格）。

数据源：
- 预案文件目录：data/预案/parsered_data/*.json（中文键、镜像原 PDF 章节结构）
- 索引文件：data/预案/plan_index.json（scene 路由 + section 别名 + level 映射 + 灾害补充预案）

核心能力：
- list_plans / list_scenes / get_toc：路由层
- get_emergency_plan：按 module 别名 / 中文 section 路径 / 关键词搜索取数；返回 content（原始子树）+ content_text（可读 markdown）
- get_grading_bundle：取主预案 + 灾害补充预案的 grading 表（附件 1/附件 2）
- normalize_* / infer_*：场景/灾害类别/响应级别推断（关键词规则）

设计原则：
- 不绑死任何特定预案的结构；通过 plan_index 的别名列表 + 通配符匹配兼容不同预案的命名差异
- 调用方拿到的 content_text 已经 Markdown 化，可以直接喂给 LLM 或写入方案章节
- 取数失败时返回 status=not_found + available_top_keys / fallback_chain，方便上层判断和修正
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────── 常量：场景/灾害/级别关键词 ───────────────────────────

INCIDENT_CATEGORY_ALIASES: Dict[str, List[str]] = {
    "EXPRESSWAY": ["高速公路", "高速公路支线", "连接线"],
    "HIGHWAY": ["普通公路", "普通国道", "国道", "省道", "县道", "乡道", "公路桥梁", "公路隧道"],
    "ROAD_TRANSPORT": ["道路运输", "客运站", "货运站", "道路客运", "道路货运"],
    "PORT": ["主要港口", "地区性重要港口", "一般港口", "危险货物码头", "仓储场所", "港口客运枢纽", "港口", "码头"],
    "WATERWAY": ["航道", "重要航道", "界河航道"],
    "WATERWAY_XIJIANG": ["西江水道", "西江黄金水道", "西江航运干线"],
    "WATER_TRANSPORT": ["水路运输", "水运保障", "水路客运", "水路货运"],
    "CITY_BUS": ["城市公交", "城市公共汽电车", "公交"],
    "URBAN_RAIL": ["城市轨道交通", "地铁", "轨道交通"],
    "CONSTRUCTION": ["公路水运工程", "工程施工", "施工工地"],
}

DISASTER_TYPE_ALIASES: Dict[str, List[str]] = {
    "FLOOD": ["洪水台风", "洪水", "台风", "暴雨", "积水", "洪涝", "内涝", "洪水地质灾害"],
    "ICE_SNOW": ["低温雨雪冰冻", "冰雪", "结冰", "冻雨", "大雪", "寒潮"],
    "EARTHQUAKE": ["地震", "地震地质灾害"],
    "PUBLIC_HEALTH": ["公共卫生", "公共卫生事件", "疫情", "传染病"],
    "CYBER": ["网络安全", "网络攻击", "系统瘫痪"],
}

RESPONSE_LEVEL_NAMES = {
    "I": "特别重大级",
    "II": "重大级",
    "III": "较大级",
    "IV": "一般级",
}

SCENE_TYPE_KEYWORDS: List[Tuple[Tuple[str, ...], str]] = [
    (("危化品", "泄漏", "爆炸", "追尾", "相撞", "车祸"), "交通运输事故和危险化学品泄漏事故"),
    (("洪水", "暴雨", "台风", "滑坡", "塌方", "泥石流", "山体"), "洪水与地质灾害事件"),
    (("冰雪", "结冰", "冻雨", "大雾", "浓雾", "低温"), "气象灾害事件"),
    (("拥堵", "积压", "排队"), "交通拥堵事件"),
]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip().lower()


# ─────────────────────────── 主服务类 ───────────────────────────

class EmergencyPlanService:
    """读 parsered_data 风格预案的服务，按 scene/module/section 取数。"""

    DEFAULT_PLANS_DIR = "data/预案/parsered_data"
    DEFAULT_INDEX_PATH = "data/预案/plan_index.json"

    def __init__(
        self,
        plans_dir: Optional[str] = None,
        index_path: Optional[str] = None,
    ):
        self.plans_dir = Path(plans_dir or self.DEFAULT_PLANS_DIR)
        self.index_path = Path(index_path or self.DEFAULT_INDEX_PATH)
        self.index = self._load_index()
        self.plans = self._load_plans()  # title → {meta, content}

        logger.info(
            "EmergencyPlanService 初始化完成: plans_dir=%s, index_path=%s, plans=%s",
            self.plans_dir, self.index_path, len(self.plans),
        )

    # ─────────────── 加载 ───────────────

    def _load_index(self) -> Dict[str, Any]:
        if not self.index_path.exists():
            logger.warning("plan_index.json 不存在: %s，将使用空索引", self.index_path)
            return {}
        with open(self.index_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_plans(self) -> Dict[str, Dict[str, Any]]:
        plans: Dict[str, Dict[str, Any]] = {}
        if not self.plans_dir.exists():
            logger.warning("预案目录不存在: %s", self.plans_dir)
            return plans
        for path in sorted(self.plans_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error("加载预案失败: %s, error=%s", path, e)
                continue
            cover = data.get("封面", {}) if isinstance(data.get("封面"), dict) else {}
            title = cover.get("标题") or data.get("plan_name") or path.stem
            plans[title] = {
                "title": title,
                "file": path.name,
                "publisher": cover.get("发布单位", ""),
                "publish_time": cover.get("发布时间", ""),
                "content": data,
            }
        return plans

    # ─────────────── 路由层 ───────────────

    def list_plans(self) -> List[Dict[str, Any]]:
        return [
            {
                "title": p["title"],
                "file": p["file"],
                "publisher": p.get("publisher", ""),
                "publish_time": p.get("publish_time", ""),
                "top_level_keys": [k for k in p["content"].keys() if k != "目录"],
            }
            for p in self.plans.values()
        ]

    def list_scenes(self) -> List[Dict[str, Any]]:
        scene_plans = (self.index.get("scene_plans", {}) or {})
        out = []
        for scene, entry in scene_plans.items():
            preferred = entry.get("preferred_plan_name", "")
            out.append({
                "scene": scene,
                "preferred_plan_name": preferred,
                "available": preferred in self.plans,
                "fallback_to": entry.get("fallback_to"),
                "description": entry.get("description", ""),
            })
        return out

    def resolve_plan_for_scene(self, scene: str) -> Tuple[Optional[Dict[str, Any]], List[str], str]:
        """沿 fallback_to 链查找匹配预案。返回 (plan_dict, chain, resolved_via)。"""
        scene_plans = (self.index.get("scene_plans", {}) or {})
        fallback_default = self.index.get("fallback_plan_name", "")

        chain: List[str] = []
        current = (scene or "").upper().strip()
        visited: set = set()

        while current and current not in visited:
            visited.add(current)
            entry = scene_plans.get(current)
            if not entry:
                chain.append(f"{current}(未在索引中)")
                break
            preferred = entry.get("preferred_plan_name", "")
            chain.append(f"{current}→{preferred}")
            if preferred and preferred in self.plans:
                return self.plans[preferred], chain, f"scene_plans[{current}].preferred_plan_name"
            nxt = entry.get("fallback_to")
            if not nxt:
                break
            current = nxt

        if fallback_default and fallback_default in self.plans:
            chain.append(f"fallback_default→{fallback_default}")
            return self.plans[fallback_default], chain, "fallback_plan_name"

        return None, chain, ""

    def get_toc(self, scene: str = "", plan_name: str = "", depth: int = 3) -> Dict[str, Any]:
        """返回某预案的章节路径树（深度可调）。"""
        plan_meta: Optional[Dict[str, Any]] = None
        chain: List[str] = []
        if plan_name and plan_name in self.plans:
            plan_meta = self.plans[plan_name]
        elif scene:
            plan_meta, chain, _ = self.resolve_plan_for_scene(scene)

        if plan_meta is None:
            return {
                "status": "not_found",
                "scene": scene,
                "plan_name": plan_name,
                "fallback_chain": chain,
                "message": "未找到匹配预案",
            }

        toc = self._walk_keys(plan_meta["content"], max_depth=depth)
        return {
            "status": "success",
            "scene": scene,
            "plan_name": plan_meta["title"],
            "plan_file": plan_meta["file"],
            "fallback_chain": chain,
            "depth": depth,
            "toc": toc,
        }

    # ─────────────── 取数核心 ───────────────

    def get_emergency_plan(
        self,
        incident_category: str = "",
        module: str = "",
        section_path: str = "",
        search_keyword: str = "",
        disaster_type: str = "",
        level: str = "",
        scene_type: str = "",
    ) -> Dict[str, Any]:
        """
        按 incident_category（场景）路由到预案，再按 module/section_path/search_keyword 取数。

        三选一：必须提供 module / section_path / search_keyword 之一。
        当 module='response_measures' 且传了 level 时，自动改查对应级别的子节别名
        （response_measures_i/ii/iii/iv）。
        """
        normalized_category = self.normalize_incident_category(incident_category) or incident_category
        normalized_disaster = self.normalize_disaster_type(disaster_type) or disaster_type
        normalized_level = self.normalize_response_level(level) or level

        plan_meta, fallback_chain, resolved_via = self.resolve_plan_for_scene(normalized_category)
        if plan_meta is None:
            return {
                "status": "not_found",
                "incident_category": normalized_category,
                "disaster_type": normalized_disaster,
                "module": module,
                "section_path": section_path,
                "search_keyword": search_keyword,
                "level": normalized_level,
                "fallback_chain": fallback_chain,
                "message": f"未找到 incident_category={normalized_category} 对应的预案",
            }

        # 至少要提供一种查询方式
        if not module and not section_path and not search_keyword:
            return {
                "status": "error",
                "code": "MISSING_QUERY",
                "incident_category": normalized_category,
                "plan_name": plan_meta["title"],
                "message": "请提供 module / section_path / search_keyword 之一",
                "hint": "可调 get_toc 看预案章节结构，或 list_scenes 看 module 别名清单",
            }

        plan = plan_meta["content"]

        # 主预案取数
        primary = self._fetch(
            plan=plan,
            plan_meta=plan_meta,
            module=module,
            section_path=section_path,
            search_keyword=search_keyword,
            level=normalized_level,
        )
        primary["incident_category"] = normalized_category
        primary["disaster_type"] = normalized_disaster
        primary["level"] = normalized_level
        primary["scene_type"] = scene_type
        primary["fallback_chain"] = fallback_chain
        primary["resolved_via"] = resolved_via

        # 灾害类补充预案（如有）
        supplementary = None
        if normalized_disaster:
            supp_name = (self.index.get("disaster_supplementary_plans", {}) or {}).get(normalized_disaster)
            if supp_name and supp_name in self.plans and supp_name != plan_meta["title"]:
                supp_meta = self.plans[supp_name]
                supplementary = self._fetch(
                    plan=supp_meta["content"],
                    plan_meta=supp_meta,
                    module=module,
                    section_path=section_path,
                    search_keyword=search_keyword,
                    level=normalized_level,
                )
                supplementary["role"] = "supplementary_plan"
        primary["supplementary_plan"] = supplementary

        return primary

    def _fetch(
        self,
        plan: Dict[str, Any],
        plan_meta: Dict[str, Any],
        module: str,
        section_path: str,
        search_keyword: str,
        level: str,
    ) -> Dict[str, Any]:
        """从单份预案里按 module/section_path/search_keyword 取数。"""
        base = {
            "plan_name": plan_meta["title"],
            "plan_file": plan_meta["file"],
            "module": module,
            "section_path": section_path,
            "search_keyword": search_keyword,
        }

        # ── 关键词搜索 ──
        if search_keyword:
            hits = self._search_in_plan(plan, search_keyword)
            return {
                **base,
                "status": "success",
                "mode": "search",
                "hit_count": len(hits),
                "hits": hits[:50],
                "truncated": len(hits) > 50,
                "content_text": self._render_search_hits(search_keyword, hits[:20]),
            }

        # ── module 别名 ──
        if module:
            effective_module = module
            # level 自动映射
            level_map = self.index.get("level_section_map", {}) or {}
            if module == "response_measures" and level and level in level_map:
                mapped = level_map[level]
                logger.debug("module=response_measures + level=%s → 自动改查 %s", level, mapped)
                effective_module = mapped

            alias_table = (self.index.get("section_aliases", {}) or {})
            alias_paths = alias_table.get(effective_module)
            if not alias_paths:
                return {
                    **base,
                    "status": "not_found",
                    "mode": "module",
                    "effective_module": effective_module,
                    "message": f"未知 module 别名: {effective_module}",
                    "available_modules": sorted(alias_table.keys()),
                }

            value, hit_path, used = self._try_aliases(plan, alias_paths)
            if value is None:
                return {
                    **base,
                    "status": "not_found",
                    "mode": "module",
                    "effective_module": effective_module,
                    "tried_paths": alias_paths,
                    "message": f"该预案下找不到 module={effective_module} 的任何候选路径",
                }

            text = self._render_subtree(value, root_title=used[-1] if used else effective_module)
            return {
                **base,
                "status": "success",
                "mode": "module",
                "effective_module": effective_module,
                "hit_path": hit_path,
                "resolved_segments": used,
                "content": value,
                "content_text": text,
                "source_reference": self._build_source_ref(plan_meta["title"], hit_path),
            }

        # ── section_path ──
        if section_path:
            value, used, found = self._resolve_path(plan, self._split_path(section_path))
            if not found:
                return {
                    **base,
                    "status": "not_found",
                    "mode": "section",
                    "available_top_keys": list(plan.keys()),
                    "message": f"路径无法解析: {section_path}",
                }
            text = self._render_subtree(value, root_title=used[-1] if used else section_path)
            return {
                **base,
                "status": "success",
                "mode": "section",
                "hit_path": ".".join(used),
                "resolved_segments": used,
                "content": value,
                "content_text": text,
                "source_reference": self._build_source_ref(plan_meta["title"], ".".join(used)),
            }

        return {**base, "status": "error", "code": "UNREACHABLE", "message": "查询模式判定失败"}

    # ─────────────── 定级专用 ───────────────

    def get_grading_bundle(
        self,
        incident_category: str = "",
        disaster_type: str = "",
    ) -> Dict[str, Any]:
        """
        取主预案 + 灾害补充预案的分级标准（附件1/附件2 表格内容）。

        返回:
        {
          status,
          incident_category, disaster_type,
          main_plan_name, main_grading_table (附件2), main_grading_text,
          warning_grading_table (附件1, 可选),
          supplementary_plan_name, supplementary_grading_table, supplementary_grading_text,
          fallback_chain,
        }
        """
        normalized_category = self.normalize_incident_category(incident_category) or incident_category
        normalized_disaster = self.normalize_disaster_type(disaster_type) or disaster_type

        plan_meta, chain, _ = self.resolve_plan_for_scene(normalized_category)
        if plan_meta is None:
            return {
                "status": "not_found",
                "incident_category": normalized_category,
                "disaster_type": normalized_disaster,
                "message": "未找到匹配预案",
                "fallback_chain": chain,
            }

        main_table_value, _, main_table_path = self._fetch_grading_table(plan_meta["content"], appendix="附件2*")
        warning_table_value, _, _ = self._fetch_grading_table(plan_meta["content"], appendix="附件1*")

        supplementary = None
        if normalized_disaster:
            supp_name = (self.index.get("disaster_supplementary_plans", {}) or {}).get(normalized_disaster)
            if supp_name and supp_name in self.plans and supp_name != plan_meta["title"]:
                supp_meta = self.plans[supp_name]
                supp_value, _, supp_path = self._fetch_grading_table(supp_meta["content"], appendix="附件2*")
                supplementary = {
                    "supplementary_plan_name": supp_meta["title"],
                    "supplementary_grading_table": supp_value,
                    "supplementary_grading_path": supp_path,
                    "supplementary_grading_text": self._render_grading_table(supp_value) if supp_value else "",
                }

        return {
            "status": "success" if main_table_value else "partial",
            "incident_category": normalized_category,
            "disaster_type": normalized_disaster,
            "main_plan_name": plan_meta["title"],
            "main_plan_file": plan_meta["file"],
            "main_grading_table": main_table_value,
            "main_grading_path": main_table_path,
            "main_grading_text": self._render_grading_table(main_table_value) if main_table_value else "",
            "warning_grading_table": warning_table_value,
            "warning_grading_text": self._render_grading_table(warning_table_value) if warning_table_value else "",
            "fallback_chain": chain,
            **(supplementary or {
                "supplementary_plan_name": "",
                "supplementary_grading_table": None,
                "supplementary_grading_path": "",
                "supplementary_grading_text": "",
            }),
        }

    def _fetch_grading_table(self, plan: Dict[str, Any], appendix: str = "附件2*") -> Tuple[Any, List[str], str]:
        """从预案的附件区取分级表 dict。"""
        # 优先按 "附件.附件2*" 通配查找
        value, used, found = self._resolve_path(plan, ["附件", appendix])
        if found:
            return value, used, ".".join(used)
        # 兼容某些预案把分级标准放在顶层"总则"下
        for candidate in ("总则.事故分级", "总则.事件分级"):
            value, used, found = self._resolve_path(plan, self._split_path(candidate))
            if found:
                return value, used, ".".join(used)
        return None, [], ""

    # ─────────────── 路径解析底层 ───────────────

    @staticmethod
    def _split_path(dotted: str) -> List[str]:
        return [seg for seg in dotted.split(".") if seg]

    @staticmethod
    def _resolve_path(node: Any, segments: List[str]) -> Tuple[Any, List[str], bool]:
        """按 segments 逐级下钻。支持末尾 '*' 通配 + 宽松匹配（去空格 / 子串）。"""
        used: List[str] = []
        for seg in segments:
            if not isinstance(node, dict):
                return None, used, False

            # 末尾 * 通配
            if seg.endswith("*"):
                prefix = seg[:-1]
                candidates = [k for k in node.keys() if k.startswith(prefix)]
                if not candidates:
                    return None, used, False
                chosen = candidates[0]
                used.append(chosen)
                node = node[chosen]
                continue

            # 精确
            if seg in node:
                used.append(seg)
                node = node[seg]
                continue

            # 宽松：去空格全等 / 子串
            norm = re.sub(r"\s+", "", seg).lower()
            matched = None
            for k in node.keys():
                if re.sub(r"\s+", "", k).lower() == norm:
                    matched = k
                    break
            if matched is None:
                for k in node.keys():
                    if seg in k or k in seg:
                        matched = k
                        break
            if matched is None:
                return None, used, False
            used.append(matched)
            node = node[matched]
        return node, used, True

    @classmethod
    def _try_aliases(cls, plan: Dict[str, Any], alias_paths: List[str]) -> Tuple[Any, str, List[str]]:
        """逐个尝试 alias 路径，返回 (value, hit_alias, used_segments)。"""
        for alias in alias_paths:
            value, used, found = cls._resolve_path(plan, cls._split_path(alias))
            if found:
                return value, alias, used
        return None, "", []

    @staticmethod
    def _walk_keys(node: Any, prefix: str = "", depth: int = 0, max_depth: int = 3) -> List[str]:
        out: List[str] = []
        if depth > max_depth:
            return out
        if isinstance(node, dict):
            for k, v in node.items():
                path = f"{prefix}.{k}" if prefix else k
                out.append(path)
                out.extend(EmergencyPlanService._walk_keys(v, path, depth + 1, max_depth))
        return out

    @staticmethod
    def _search_in_plan(plan: Any, keyword: str, prefix: str = "") -> List[Dict[str, str]]:
        hits: List[Dict[str, str]] = []
        if isinstance(plan, dict):
            for k, v in plan.items():
                path = f"{prefix}.{k}" if prefix else k
                if keyword in str(k):
                    preview = (
                        str(v)[:160].replace("\n", " ")
                        if not isinstance(v, (dict, list))
                        else f"({type(v).__name__}, {len(v)} items)"
                    )
                    hits.append({"path": path, "match": "key", "preview": preview})
                elif isinstance(v, str) and keyword in v:
                    idx = v.find(keyword)
                    start = max(0, idx - 30)
                    end = min(len(v), idx + 100)
                    preview = v[start:end].replace("\n", " ")
                    hits.append({"path": path, "match": "value", "preview": preview})
                hits.extend(EmergencyPlanService._search_in_plan(v, keyword, path))
        elif isinstance(plan, list):
            for i, item in enumerate(plan):
                hits.extend(EmergencyPlanService._search_in_plan(item, keyword, f"{prefix}[{i}]"))
        return hits

    # ─────────────── 渲染层（subtree → markdown） ───────────────

    @classmethod
    def _render_subtree(cls, node: Any, root_title: str = "", depth: int = 0, max_depth: int = 6) -> str:
        """把任意子树渲染为可读 markdown 文本。"""
        if depth > max_depth:
            return "...（嵌套过深，已截断）"

        if isinstance(node, str):
            return node

        if isinstance(node, (int, float, bool)) or node is None:
            return str(node)

        if isinstance(node, list):
            lines = []
            for item in node:
                rendered = cls._render_subtree(item, depth=depth + 1, max_depth=max_depth)
                lines.append(f"- {rendered}")
            return "\n".join(lines)

        if isinstance(node, dict):
            # 表格特判：附件1/附件2 那种 {"标题": ..., "表格": {Ⅰ级:..., Ⅱ级:...}}
            # _render_grading_table 内部会处理标题/表格/注，不要在外层重复渲染
            if "表格" in node and isinstance(node["表格"], dict):
                return cls._render_grading_table(node)

            # 普通 dict
            lines = []
            heading_prefix = "#" * min(depth + 2, 6)
            for k, v in node.items():
                if isinstance(v, str):
                    lines.append(f"{heading_prefix} {k}\n\n{v}\n")
                elif isinstance(v, (int, float, bool)) or v is None:
                    lines.append(f"{heading_prefix} {k}: {v}\n")
                elif isinstance(v, list):
                    rendered = cls._render_subtree(v, depth=depth + 1, max_depth=max_depth)
                    lines.append(f"{heading_prefix} {k}\n\n{rendered}\n")
                elif isinstance(v, dict):
                    rendered = cls._render_subtree(v, depth=depth + 1, max_depth=max_depth)
                    lines.append(f"{heading_prefix} {k}\n\n{rendered}\n")
            return "\n".join(lines).strip()

        return str(node)

    @staticmethod
    def _render_grading_table(table_node: Any) -> str:
        """把附件1/附件2 的分级表渲染为 LLM 友好的「【级别】触发条件 ...」格式。"""
        if not isinstance(table_node, dict):
            return ""

        # 找到 "表格" key
        table = table_node.get("表格") if "表格" in table_node else table_node
        if not isinstance(table, dict):
            return ""

        lines: List[str] = []
        if "标题" in table_node:
            lines.append(f"**{table_node['标题']}**\n")

        for level_key, level_data in table.items():
            if not isinstance(level_data, dict):
                lines.append(f"【{level_key}】{level_data}")
                continue
            level_label = level_data.get("级别", level_key)
            level_desc = level_data.get("级别描述", "")
            color = level_data.get("颜色标示", "")
            authority = level_data.get("响应主体", level_data.get("响应启动主体", ""))
            header = f"【{level_label}{('（' + level_desc + '）') if level_desc else ''}】"
            if color:
                header += f" 颜色：{color}"
            if authority:
                header += f" 响应主体：{authority}"
            lines.append(header)

            for field_name in (
                "事故的严重程度及影响范围",
                "预计可能发生事故情形",
                "事件的严重程度及影响范围",
                "criteria",
                "触发条件",
            ):
                if field_name in level_data:
                    val = level_data[field_name]
                    if isinstance(val, list):
                        for item in val:
                            lines.append(f"- {item}")
                    else:
                        lines.append(f"- {val}")
            lines.append("")

        if table_node.get("注"):
            lines.append(f"*{table_node['注']}*")

        return "\n".join(lines).strip()

    @staticmethod
    def _render_search_hits(keyword: str, hits: List[Dict[str, str]]) -> str:
        if not hits:
            return f"未找到关键词「{keyword}」"
        lines = [f"**关键词「{keyword}」命中 {len(hits)} 处：**\n"]
        for h in hits:
            lines.append(f"- `{h['path']}` ({h['match']}): {h['preview']}")
        return "\n".join(lines)

    @staticmethod
    def _build_source_ref(plan_name: str, hit_path: str) -> str:
        if not plan_name:
            return ""
        if hit_path:
            return f"《{plan_name}》{hit_path}".strip()
        return f"《{plan_name}》"

    # ─────────────── normalize / infer 类方法（沿用旧实现） ───────────────

    @classmethod
    def normalize_incident_category(cls, value: str) -> str:
        if not value:
            return ""
        raw = str(value).strip()
        upper = raw.upper()
        if upper in INCIDENT_CATEGORY_ALIASES:
            return upper
        normalized = _normalize_text(raw)
        for code, aliases in INCIDENT_CATEGORY_ALIASES.items():
            if normalized == _normalize_text(code):
                return code
            if any(normalized == _normalize_text(alias) for alias in aliases):
                return code
        return ""

    @classmethod
    def normalize_disaster_type(cls, value: str) -> str:
        if not value:
            return ""
        raw = str(value).strip()
        upper = raw.upper()
        if upper in DISASTER_TYPE_ALIASES:
            return upper
        normalized = _normalize_text(raw)
        for code, aliases in DISASTER_TYPE_ALIASES.items():
            if normalized == _normalize_text(code):
                return code
            if any(normalized == _normalize_text(alias) for alias in aliases):
                return code
        return ""

    @classmethod
    def normalize_response_level(cls, value: str) -> str:
        if not value:
            return ""
        normalized = _normalize_text(value)
        if normalized in {"i", "i级", "ⅰ", "ⅰ级", "特别重大", "特别重大级"}:
            return "特别重大级"
        if normalized in {"ii", "ii级", "ⅱ", "ⅱ级", "重大", "重大级"}:
            return "重大级"
        if normalized in {"iii", "iii级", "ⅲ", "ⅲ级", "较大", "较大级"}:
            return "较大级"
        if normalized in {"iv", "iv级", "ⅳ", "ⅳ级", "一般", "一般级"}:
            return "一般级"
        if "特别重大" in normalized:
            return "特别重大级"
        if normalized.startswith("重大") or normalized.endswith("重大级"):
            return "重大级"
        if "较大" in normalized:
            return "较大级"
        if "一般" in normalized:
            return "一般级"
        return ""

    @classmethod
    def infer_incident_category(cls, text: str, location_text: str = "", incident_type: str = "") -> str:
        merged = f"{text or ''}\n{location_text or ''}\n{incident_type or ''}"
        if any(k in merged for k in ("高速", "收费站", "服务区")):
            return "EXPRESSWAY"
        if re.search(r"\bG\d+\b", merged):
            return "EXPRESSWAY"
        if any(k in merged for k in ("国道", "省道", "县道", "乡道", "公路", "隧道", "桥梁")):
            return "HIGHWAY"
        if any(k in merged for k in ("港口", "码头", "泊位", "客运枢纽")):
            return "PORT"
        if any(k in merged for k in ("航道", "断航", "船闸")):
            return "WATERWAY"
        if any(k in merged for k in ("公交", "公交车站", "公交场站")):
            return "CITY_BUS"
        if any(k in merged for k in ("地铁", "轨道交通", "轻轨")):
            return "URBAN_RAIL"
        if any(k in merged for k in ("施工", "工地", "作业面", "公路水运工程")):
            return "CONSTRUCTION"
        return ""

    @classmethod
    def infer_disaster_type(cls, text: str, incident_type: str = "", scene_status: str = "") -> str:
        merged = f"{text or ''}\n{incident_type or ''}\n{scene_status or ''}"
        if any(k in merged for k in ("暴雨", "洪水", "台风", "积水", "内涝", "滑坡", "塌方", "泥石流")):
            return "FLOOD"
        if any(k in merged for k in ("结冰", "冻雨", "冰雪", "低温", "大雪", "寒潮")):
            return "ICE_SNOW"
        if "地震" in merged:
            return "EARTHQUAKE"
        if any(k in merged for k in ("疫情", "传染病", "公共卫生")):
            return "PUBLIC_HEALTH"
        if any(k in merged for k in ("网络", "系统", "黑客", "攻击")):
            return "CYBER"
        return ""

    @classmethod
    def infer_scene_type(
        cls,
        incident_category: str,
        incident_type: str = "",
        disaster_type: str = "",
        scene_status: str = "",
        raw_text: str = "",
        available_scene_names: Optional[Iterable[str]] = None,
    ) -> str:
        merged = f"{incident_category}\n{incident_type}\n{disaster_type}\n{scene_status}\n{raw_text}"
        candidate = ""
        for keywords, scene_name in SCENE_TYPE_KEYWORDS:
            if any(k in merged for k in keywords):
                candidate = scene_name
                break

        if not available_scene_names:
            return candidate
        names = list(available_scene_names)
        if not names:
            return candidate
        if not candidate:
            return names[0]
        matched = cls.match_scene_name(names, candidate)
        return matched or names[0]

    @classmethod
    def match_scene_name(cls, scene_names: Iterable[str], scene_type: str) -> str:
        target = _normalize_text(scene_type)
        if not target:
            return ""
        for name in scene_names:
            normalized_name = _normalize_text(name)
            if target == normalized_name:
                return name
            if target in normalized_name or normalized_name in target:
                return name
        alias_map = {
            "交通事故和危化品泄漏": "交通运输事故和危险化学品泄漏事故",
            "交通事故和危险化学品泄漏": "交通运输事故和危险化学品泄漏事故",
            "洪水与地质灾害": "洪水与地质灾害事件",
            "气象灾害": "气象灾害事件",
            "交通拥堵": "交通拥堵事件",
        }
        alias = alias_map.get(scene_type, "")
        if alias:
            return cls.match_scene_name(scene_names, alias)
        return ""
