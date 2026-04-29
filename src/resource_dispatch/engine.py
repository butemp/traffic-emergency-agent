"""
资源调度引擎。

按照 tech.md 中的设计，实现：
- NearbySearch
- CoverageAnalysis
- DispatchOptimizer

设计原则：
- 读取离线清洗好的仓库/队伍索引文件
- 模型负责需求推断，算法负责筛选、排序和组合
- 保持工具输出结构化，便于 Web 端和 Agent 后续使用
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


DATA_FRESHNESS = {
    "note": "物资数据基于最近一次核查，实际库存可能有变动",
    "suggestion": "建议出发前电话确认关键物资的可用性",
}

CATEGORY_TO_POI = {
    "RESCUE": {"poi_type": "医院", "reason": "缺少救生装备，建议查询附近医院"},
    "FIRE": {"poi_type": "消防站", "reason": "缺少消防器材，建议查询附近消防站"},
    "VEHICLE": {"poi_type": "汽车救援", "reason": "缺少作业车辆，建议查询社会救援力量"},
}

SPECIALTY_KEYWORDS = {
    "rescue": ("救援", "救生", "急救", "救护", "抢险救援", "人员救助"),
    "clearance": ("清障", "拖车", "障碍物", "排障", "吊装", "事故车辆"),
    "emergency_repair": ("抢修", "抢通", "维修", "养护", "塌方", "水毁", "修复", "施工"),
}

STAKE_PATTERN = re.compile(r"(?:K)?\s*(\d+(?:\.\d+)?)(?:\+(\d+))?")


class ResourceDispatchEngine:
    """资源调度核心引擎。"""

    def __init__(
        self,
        warehouse_index_path: Optional[str] = None,
        team_index_path: Optional[str] = None,
    ):
        base_dir = Path(__file__).resolve().parents[2] / "data" / "仓库和队伍的物资数据"

        self.warehouse_index_path = self._resolve_data_path(
            warehouse_index_path,
            candidates=[
                base_dir / "warehouse_dispatch_resources.json",
                base_dir / "warehouse_dispatch_resources.jsonl",
                base_dir / "warehouse_index.json",
                base_dir / "warehouse_index.jsonl",
            ],
        )
        self.team_index_path = self._resolve_data_path(
            team_index_path,
            candidates=[
                base_dir / "rescue_team_dispatch_resources.json",
                base_dir / "rescue_team_dispatch_resources.jsonl",
                base_dir / "team_index.json",
                base_dir / "team_index.jsonl",
            ],
        )

        self.warehouses = self._load_records(self.warehouse_index_path)
        self.teams = self._load_records(self.team_index_path)
        self.category_index = self._build_category_index()
        self.last_search_context: Optional[Dict[str, Any]] = None

        logger.info(
            "资源调度引擎初始化完成: warehouses=%s, teams=%s",
            len(self.warehouses),
            len(self.teams),
        )

    def _resolve_data_path(self, explicit_path: Optional[str], candidates: Sequence[Path]) -> Path:
        """解析索引文件路径，支持显式路径和默认候选路径。"""
        if explicit_path:
            return Path(explicit_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # 默认返回第一个候选项，便于后续报错信息更明确
        return candidates[0]

    def _load_records(self, path: Path) -> List[Dict[str, Any]]:
        """读取 JSON 或 JSONL 资源索引。"""
        if not path.exists():
            raise FileNotFoundError(f"资源索引文件不存在: {path}")

        if path.suffix.lower() == ".jsonl":
            records: List[Dict[str, Any]] = []
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            return records

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []

    def _build_category_index(self) -> Dict[str, Dict[str, List[str]]]:
        """构建 category -> resource id 的反向索引。"""
        category_index = {
            "warehouse": {},
            "team": {},
        }

        for resource_type, records, id_field in (
            ("warehouse", self.warehouses, "warehouse_id"),
            ("team", self.teams, "team_id"),
        ):
            for record in records:
                resource_id = self._clean_text(record.get(id_field))
                if not resource_id:
                    continue
                for category in self._normalize_categories(record.get("categories")):
                    category_index[resource_type].setdefault(category, []).append(resource_id)

        return category_index

    def search_resources(
        self,
        longitude: float,
        latitude: float,
        required_categories: Optional[List[str]] = None,
        required_specialties: Optional[List[str]] = None,
        road_code: Optional[str] = None,
        stake: Optional[Any] = None,
        radius_km: float = 50.0,
        resource_type: str = "all",
        exclude_ids: Optional[List[str]] = None,
        max_results: int = 10,
    ) -> Dict[str, Any]:
        """执行 NearbySearch + CoverageAnalysis。"""
        params = {
            "longitude": float(longitude),
            "latitude": float(latitude),
            "road_code": self._clean_text(road_code),
            "stake": self._coerce_stake(stake),
            "radius_km": float(radius_km or 50.0),
            "resource_type": resource_type or "all",
            "required_categories": self._normalize_categories(required_categories),
            "required_specialties": self._normalize_required_specialties(required_specialties),
            "exclude_ids": set(exclude_ids or []),
            "max_results": max(1, int(max_results or 10)),
        }

        warehouses, teams = self._run_nearby_search(params)
        search_expanded = False

        if not warehouses and not teams and params["radius_km"] < 100:
            expanded_params = dict(params)
            expanded_params["radius_km"] = 100.0
            warehouses, teams = self._run_nearby_search(expanded_params)
            params = expanded_params
            search_expanded = True

        coverage = self._analyze_coverage(
            required_categories=params["required_categories"],
            required_specialties=params["required_specialties"],
            candidate_warehouses=warehouses,
            candidate_teams=teams,
        )

        result = {
            "status": "success",
            "search_params": {
                "longitude": params["longitude"],
                "latitude": params["latitude"],
                "road_code": params["road_code"],
                "stake": params["stake"],
                "radius_km": params["radius_km"],
                "required_categories": params["required_categories"],
                "required_specialties": params["required_specialties"],
                "resource_type": params["resource_type"],
                "search_expanded": search_expanded,
            },
            "candidates": {
                "warehouses": warehouses,
                "teams": teams,
            },
            "coverage": coverage,
            "data_freshness": DATA_FRESHNESS,
        }

        self.last_search_context = {
            "params": params,
            "candidates": {
                "warehouses": warehouses,
                "teams": teams,
            },
            "coverage": coverage,
        }
        return result

    def optimize_dispatch_plan(
        self,
        required_categories: Optional[List[str]] = None,
        required_specialties: Optional[List[str]] = None,
        exclude_ids: Optional[List[str]] = None,
        preferred_ids: Optional[List[str]] = None,
        max_warehouses: int = 5,
        max_teams: int = 5,
        tier1_distance_km: float = 15.0,
        tier2_distance_km: float = 35.0,
    ) -> Dict[str, Any]:
        """基于最近一次搜索结果生成分梯队调度方案。"""
        if self.last_search_context is None:
            return {
                "status": "error",
                "message": "尚未执行 search_emergency_resources，无法生成调度方案",
            }

        context = self.last_search_context
        base_params = context["params"]
        required_categories = self._normalize_categories(required_categories or base_params.get("required_categories"))
        required_specialties = self._normalize_required_specialties(
            required_specialties or base_params.get("required_specialties")
        )

        exclude_set = set(exclude_ids or [])
        preferred_set = set(preferred_ids or [])

        warehouse_candidates = [
            item for item in context["candidates"]["warehouses"]
            if item["resource_id"] not in exclude_set
        ]
        team_candidates = [
            item for item in context["candidates"]["teams"]
            if item["resource_id"] not in exclude_set
        ]

        selected_warehouses: List[Dict[str, Any]] = []
        selected_teams: List[Dict[str, Any]] = []
        uncovered_categories = set(required_categories)
        unmatched_specialties = set(required_specialties)

        for resource in warehouse_candidates + team_candidates:
            if resource["resource_id"] not in preferred_set:
                continue
            if resource["resource_type"] == "warehouse":
                selected_warehouses.append(resource)
            else:
                selected_teams.append(resource)
            uncovered_categories -= set(resource.get("matched_categories", []))
            unmatched_specialties -= set(resource.get("matched_specialties", []))

        remaining_warehouses = [
            item for item in warehouse_candidates
            if item["resource_id"] not in {resource["resource_id"] for resource in selected_warehouses}
        ]

        while uncovered_categories and remaining_warehouses and len(selected_warehouses) < max_warehouses:
            best_candidate = None
            best_value = float("-inf")

            for warehouse in remaining_warehouses:
                new_coverage = len(set(warehouse.get("matched_categories", [])) & uncovered_categories)
                if new_coverage == 0:
                    continue

                value = new_coverage * 100.0 - float(warehouse.get("distance_km", 9999))
                if value > best_value:
                    best_value = value
                    best_candidate = warehouse

            if best_candidate is None:
                break

            selected_warehouses.append(best_candidate)
            uncovered_categories -= set(best_candidate.get("matched_categories", []))
            remaining_warehouses = [
                item for item in remaining_warehouses
                if item["resource_id"] != best_candidate["resource_id"]
            ]

        remaining_teams = [
            item for item in team_candidates
            if item["resource_id"] not in {resource["resource_id"] for resource in selected_teams}
        ]
        remaining_teams.sort(key=lambda item: item.get("relevance_score", 0), reverse=True)

        for team in remaining_teams:
            if len(selected_teams) >= max_teams:
                break

            matched_specialties = set(team.get("matched_specialties", [])) & unmatched_specialties
            if matched_specialties or team.get("relevance_score", 0) >= 60:
                selected_teams.append(team)
                unmatched_specialties -= matched_specialties
                uncovered_categories -= set(team.get("matched_categories", []))

        dispatch_plan = self._arrange_tiers(
            selected_warehouses=selected_warehouses,
            selected_teams=selected_teams,
            uncovered_categories=sorted(uncovered_categories),
            required_category_count=len(required_categories),
            tier1_distance_km=float(tier1_distance_km),
            tier2_distance_km=float(tier2_distance_km),
        )

        coverage_summary = self._build_dispatch_coverage_summary(
            required_categories=required_categories,
            selected_warehouses=selected_warehouses,
            selected_teams=selected_teams,
            still_uncovered=dispatch_plan["still_uncovered"],
        )

        return {
            "status": "success",
            "dispatch_plan": dispatch_plan,
            "coverage_summary": coverage_summary,
            "data_freshness": DATA_FRESHNESS,
        }

    def _run_nearby_search(self, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """执行资源搜索和排序。"""
        warehouses: List[Dict[str, Any]] = []
        teams: List[Dict[str, Any]] = []

        if params["resource_type"] in {"all", "warehouse"}:
            for record in self.warehouses:
                candidate = self._build_candidate(record, "warehouse", params)
                if candidate is not None:
                    warehouses.append(candidate)

        if params["resource_type"] in {"all", "team"}:
            for record in self.teams:
                candidate = self._build_candidate(record, "team", params)
                if candidate is not None:
                    teams.append(candidate)

        warehouses.sort(key=lambda item: item["relevance_score"], reverse=True)
        teams.sort(key=lambda item: item["relevance_score"], reverse=True)

        max_results = params["max_results"]
        return warehouses[:max_results], teams[:max_results]

    def _build_candidate(
        self,
        record: Dict[str, Any],
        resource_type: str,
        params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """构建单个候选资源。"""
        id_field = "warehouse_id" if resource_type == "warehouse" else "team_id"
        name_field = "warehouse_name" if resource_type == "warehouse" else "team_name"
        resource_id = self._clean_text(record.get(id_field))
        if not resource_id or resource_id in params["exclude_ids"]:
            return None

        latitude = self._clean_float(record.get("latitude"))
        longitude = self._clean_float(record.get("longitude"))
        if latitude is None or longitude is None:
            return None

        distance_km, distance_type, same_road = self._compute_distance(
            incident_lat=params["latitude"],
            incident_lon=params["longitude"],
            incident_road_code=params["road_code"],
            incident_stake=params["stake"],
            resource_lat=latitude,
            resource_lon=longitude,
            resource_road_code=self._clean_text(record.get("road_code")),
            resource_stake=record.get("stake"),
        )
        if distance_km is None or distance_km > params["radius_km"]:
            return None

        categories = self._normalize_categories(record.get("categories"))
        required_categories = params["required_categories"]
        matched_categories = sorted(set(categories) & set(required_categories))
        unmatched_categories = sorted(set(required_categories) - set(matched_categories))

        materials_by_category = record.get("materials_by_category") or {}
        materials_summary = self._build_materials_summary(materials_by_category, matched_categories or categories)

        relevance_score = self._compute_relevance_score(
            categories=categories,
            distance_km=distance_km,
            same_road=same_road,
            required_categories=required_categories,
        )

        candidate = {
            "resource_id": resource_id,
            "resource_type": resource_type,
            "name": self._clean_text(record.get(name_field)),
            "longitude": longitude,
            "latitude": latitude,
            "distance_km": round(distance_km, 2),
            "distance_type": distance_type,
            "relevance_score": relevance_score,
            "road_code": self._clean_text(record.get("road_code")),
            "stake": self._coerce_stake(record.get("stake")),
            "same_road": same_road,
            "address": self._clean_text(record.get("address")),
            "contact": self._build_contact(record, resource_type),
            "categories": categories,
            "matched_categories": matched_categories,
            "unmatched_categories": unmatched_categories,
            "materials_summary": materials_summary,
            "recommend_reasons": [],
        }

        if resource_type == "warehouse":
            candidate["belong_org_name"] = self._clean_text(record.get("belong_org_name"))
        else:
            specialties = self._normalize_specialty_tags(record.get("specialties"))
            matched_specialties = sorted(set(specialties) & set(params["required_specialties"]))
            candidate["team_size"] = self._clean_int(record.get("team_size"))
            candidate["specialties"] = specialties
            candidate["raw_specialties"] = self._clean_text(record.get("specialties"))
            candidate["matched_specialties"] = matched_specialties

        candidate["recommend_reasons"] = self._build_recommend_reasons(candidate)
        return candidate

    def _compute_distance(
        self,
        incident_lat: float,
        incident_lon: float,
        incident_road_code: Optional[str],
        incident_stake: Optional[float],
        resource_lat: float,
        resource_lon: float,
        resource_road_code: Optional[str],
        resource_stake: Any,
    ) -> Tuple[Optional[float], str, bool]:
        """计算资源与事故点之间的有效距离。"""
        geo_distance = self._haversine_km(incident_lat, incident_lon, resource_lat, resource_lon)
        same_road = bool(incident_road_code and resource_road_code and incident_road_code == resource_road_code)

        stake_points = self._parse_stake_points(resource_stake)
        if same_road and incident_stake is not None and stake_points:
            stake_distance = min(abs(incident_stake - point) for point in stake_points)
            effective_distance = max(stake_distance, geo_distance * 0.8)
            return effective_distance, "stake", True

        if incident_road_code and resource_road_code and incident_road_code != resource_road_code:
            return geo_distance * 1.5, "haversine", False

        return geo_distance, "haversine", same_road

    def _compute_relevance_score(
        self,
        categories: List[str],
        distance_km: float,
        same_road: bool,
        required_categories: List[str],
    ) -> float:
        """根据距离、类别匹配和资源丰富度计算综合得分。"""
        score = 0.0

        if distance_km <= 10:
            score += 40.0
        elif distance_km <= 50:
            score += 40.0 * (50.0 - distance_km) / 40.0

        if required_categories:
            matched = set(categories) & set(required_categories)
            match_ratio = len(matched) / len(required_categories)
            score += 35.0 * match_ratio

        if same_road:
            score += 15.0

        score += min(10.0, len(categories) * 2.0)
        return round(min(score, 100.0), 1)

    def _analyze_coverage(
        self,
        required_categories: List[str],
        required_specialties: List[str],
        candidate_warehouses: List[Dict[str, Any]],
        candidate_teams: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """分析候选资源对需求的覆盖情况。"""
        category_detail: Dict[str, Dict[str, Any]] = {}

        for category in required_categories:
            sources = []
            for resource in [*candidate_warehouses, *candidate_teams]:
                if category not in resource.get("matched_categories", []):
                    continue

                materials = resource.get("materials_summary", {}).get(category, [])
                sources.append(
                    {
                        "resource_id": resource["resource_id"],
                        "resource_type": resource["resource_type"],
                        "name": resource["name"],
                        "distance_km": resource["distance_km"],
                        "item_count": len(materials),
                        "items": materials[:5],
                    }
                )

            category_detail[category] = {
                "status": "covered" if sources else "missing",
                "source_count": len(sources),
                "total_items": sum(source["item_count"] for source in sources),
                "sources": sources,
                "nearest_source_km": min((source["distance_km"] for source in sources), default=None),
            }

        specialty_detail: Dict[str, Dict[str, Any]] = {}
        for specialty in required_specialties:
            sources = []
            for team in candidate_teams:
                if specialty not in team.get("matched_specialties", []):
                    continue
                sources.append(
                    {
                        "resource_id": team["resource_id"],
                        "name": team["name"],
                        "distance_km": team["distance_km"],
                        "team_size": team.get("team_size"),
                    }
                )

            specialty_detail[specialty] = {
                "status": "covered" if sources else "missing",
                "source_count": len(sources),
                "sources": sources,
                "nearest_source_km": min((source["distance_km"] for source in sources), default=None),
            }

        covered_categories = [key for key, value in category_detail.items() if value["status"] == "covered"]
        missing_categories = [key for key, value in category_detail.items() if value["status"] == "missing"]
        covered_specialties = [key for key, value in specialty_detail.items() if value["status"] == "covered"]
        missing_specialties = [key for key, value in specialty_detail.items() if value["status"] == "missing"]

        coverage_ratio = (
            len(covered_categories) / len(required_categories)
            if required_categories else 1.0
        )

        return {
            "detail": category_detail,
            "specialty_detail": specialty_detail,
            "coverage_ratio": round(coverage_ratio, 2),
            "covered_categories": covered_categories,
            "missing_categories": missing_categories,
            "covered_specialties": covered_specialties,
            "missing_specialties": missing_specialties,
            "recommendation": self._generate_recommendation(missing_categories),
        }

    def _generate_recommendation(self, missing_categories: List[str]) -> Dict[str, Any]:
        """根据缺口类别生成补充建议。"""
        if not missing_categories:
            return {
                "action": "sufficient",
                "message": "所有所需物资类别均已覆盖",
            }

        recommendations = []
        for category in missing_categories:
            recommendations.append(
                CATEGORY_TO_POI.get(
                    category,
                    {
                        "poi_type": None,
                        "reason": f"缺少 {category} 类物资，建议扩大搜索范围或人工协调",
                    },
                )
            )

        return {
            "action": "need_supplement",
            "missing": missing_categories,
            "recommendations": recommendations,
        }

    def _arrange_tiers(
        self,
        selected_warehouses: List[Dict[str, Any]],
        selected_teams: List[Dict[str, Any]],
        uncovered_categories: List[str],
        required_category_count: int,
        tier1_distance_km: float,
        tier2_distance_km: float,
    ) -> Dict[str, Any]:
        """将选中的资源按距离分梯队。"""
        all_resources = [
            {"type": "warehouse", "data": resource} for resource in selected_warehouses
        ] + [
            {"type": "team", "data": resource} for resource in selected_teams
        ]

        tier1: List[Dict[str, Any]] = []
        tier2: List[Dict[str, Any]] = []
        tier3: List[Dict[str, Any]] = []

        for resource in all_resources:
            item = self._build_dispatch_resource_item(resource["type"], resource["data"])
            distance_km = resource["data"]["distance_km"]

            if distance_km <= tier1_distance_km:
                tier1.append(item)
            elif distance_km <= tier2_distance_km:
                tier2.append(item)
            else:
                tier3.append(item)

        for tier in (tier1, tier2, tier3):
            tier.sort(key=lambda item: item.get("relevance_score", 0), reverse=True)

        return {
            "tier1": {
                "label": f"第一梯队（{int(tier1_distance_km)}km内，预计15分钟内到达）",
                "resources": tier1,
            },
            "tier2": {
                "label": f"第二梯队（{int(tier1_distance_km)}-{int(tier2_distance_km)}km，预计30分钟内到达）",
                "resources": tier2,
            },
            "tier3": {
                "label": f"第三梯队（{int(tier2_distance_km)}km以上，预计45分钟以上到达）",
                "resources": tier3,
            },
            "still_uncovered": uncovered_categories,
            "summary": {
                "total_warehouses": len(selected_warehouses),
                "total_teams": len(selected_teams),
                "coverage_ratio": round(
                    1 - len(uncovered_categories) / max(required_category_count, 1),
                    2,
                ),
            },
        }

    def _build_dispatch_coverage_summary(
        self,
        required_categories: List[str],
        selected_warehouses: List[Dict[str, Any]],
        selected_teams: List[Dict[str, Any]],
        still_uncovered: List[str],
    ) -> Dict[str, Any]:
        """生成调度结果的覆盖摘要。"""
        covered = sorted(
            set(required_categories) -
            set(still_uncovered)
        )
        coverage_ratio = (
            len(covered) / len(required_categories)
            if required_categories else 1.0
        )
        recommendation = self._generate_recommendation(still_uncovered)
        suggestion = recommendation.get("message")
        if not suggestion and recommendation.get("recommendations"):
            suggestion = "；".join(item["reason"] for item in recommendation["recommendations"])

        return {
            "coverage_ratio": round(coverage_ratio, 2),
            "covered": covered,
            "still_missing": still_uncovered,
            "suggestion": suggestion or "已完成内部资源调度",
            "selected_warehouse_ids": [item["resource_id"] for item in selected_warehouses],
            "selected_team_ids": [item["resource_id"] for item in selected_teams],
        }

    def _build_dispatch_resource_item(self, resource_type: str, resource: Dict[str, Any]) -> Dict[str, Any]:
        """将候选资源转换为调度输出项。"""
        item = {
            "type": resource_type,
            "resource_id": resource["resource_id"],
            "name": resource["name"],
            "longitude": resource.get("longitude"),
            "latitude": resource.get("latitude"),
            "address": resource.get("address"),
            "road_code": resource.get("road_code"),
            "stake": resource.get("stake"),
            "distance_km": resource["distance_km"],
            "relevance_score": resource["relevance_score"],
            "contact": resource["contact"],
            "recommend_reasons": resource.get("recommend_reasons", []),
        }

        if resource_type == "warehouse":
            item["action"] = self._build_warehouse_action(resource)
            item["materials_summary"] = resource.get("materials_summary", {})
            item["source_org"] = resource.get("belong_org_name")
        else:
            item["action"] = self._build_team_action(resource)
            item["team_size"] = resource.get("team_size")
            item["specialties"] = resource.get("specialties", [])
            item["source_org"] = resource.get("name")

        return item

    def _build_warehouse_action(self, resource: Dict[str, Any]) -> str:
        """生成仓库资源的调度动作描述。"""
        materials = []
        summary = resource.get("materials_summary", {})

        for category_items in summary.values():
            for item in category_items[:3]:
                unit = item.get("unit") or ""
                materials.append(f"{item.get('name')}x{item.get('quantity')}{unit}")
            if len(materials) >= 3:
                break

        if not materials:
            return "电话确认仓库库存后按需取用物资"
        return "取用物资：" + "、".join(materials[:3])

    def _build_team_action(self, resource: Dict[str, Any]) -> str:
        """生成救援队伍的调度动作描述。"""
        specialty_map = {
            "rescue": "立即出动，执行现场救援",
            "clearance": "立即出动，执行现场清障",
            "emergency_repair": "立即出动，执行抢修抢通",
        }
        for specialty in resource.get("matched_specialties", []):
            if specialty in specialty_map:
                return specialty_map[specialty]

        specialties = resource.get("specialties", [])
        if specialties:
            return "立即出动，执行" + "、".join(specialties[:2])
        return "立即出动，执行现场应急处置"

    def _build_materials_summary(
        self,
        materials_by_category: Dict[str, Any],
        categories: Iterable[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """按类别提取简化后的物资摘要。"""
        summary: Dict[str, List[Dict[str, Any]]] = {}
        for category in categories:
            items = materials_by_category.get(category) or []
            cleaned_items = []
            for item in items[:5]:
                cleaned_items.append(
                    {
                        "name": self._clean_text(item.get("name")) or "未命名物资",
                        "quantity": item.get("quantity", 0),
                        "unit": self._clean_text(item.get("unit")) or "",
                    }
                )
            if cleaned_items:
                summary[category] = cleaned_items
        return summary

    def _build_contact(self, record: Dict[str, Any], resource_type: str) -> Dict[str, Optional[str]]:
        """统一联系人字段。"""
        if resource_type == "warehouse":
            return {
                "name": self._clean_text(record.get("principal")),
                "phone": self._clean_text(record.get("contact_phone")),
            }

        return {
            "name": self._clean_text(record.get("leader_name")),
            "phone": self._clean_text(record.get("leader_phone")),
        }

    def _build_recommend_reasons(self, candidate: Dict[str, Any]) -> List[str]:
        """构造推荐理由。"""
        reasons = []
        if candidate["same_road"] and candidate.get("road_code"):
            reasons.append(f"距事故点 {candidate['distance_km']}km，同路段 {candidate['road_code']}")
        else:
            reasons.append(f"距事故点 {candidate['distance_km']}km")

        if candidate.get("matched_categories"):
            reasons.append("覆盖所需类别：" + "、".join(candidate["matched_categories"]))

        if candidate["resource_type"] == "team":
            if candidate.get("matched_specialties"):
                reasons.append("专长匹配：" + "、".join(candidate["matched_specialties"]))
            if candidate.get("team_size"):
                reasons.append(f"队伍规模 {candidate['team_size']} 人")

        reasons.append(f"综合评分 {candidate['relevance_score']}")
        return reasons

    def _normalize_categories(self, values: Optional[Iterable[Any]]) -> List[str]:
        """归一化物资类别。"""
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]

        normalized = []
        for value in values:
            text = self._clean_text(value)
            if text:
                normalized.append(text.upper())
        return sorted(dict.fromkeys(normalized))

    def _normalize_required_specialties(self, values: Optional[Iterable[Any]]) -> List[str]:
        """归一化用户要求的专长标签。"""
        if values is None:
            return []
        if isinstance(values, str):
            values = [values]

        normalized = []
        for value in values:
            text = self._clean_text(value)
            if not text:
                continue
            text = text.lower()
            if text in SPECIALTY_KEYWORDS:
                normalized.append(text)
                continue

            for tag, keywords in SPECIALTY_KEYWORDS.items():
                if text == tag or any(keyword.lower() in text for keyword in keywords):
                    normalized.append(tag)
                    break

        return sorted(dict.fromkeys(normalized))

    def _normalize_specialty_tags(self, value: Any) -> List[str]:
        """从队伍专长文本中提取标准专长标签。"""
        if value is None:
            return []
        if isinstance(value, list):
            texts = [self._clean_text(item) or "" for item in value]
        else:
            texts = [self._clean_text(value) or ""]

        joined_text = " ".join(texts)
        tags = []
        lowered = joined_text.lower()

        for tag, keywords in SPECIALTY_KEYWORDS.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                tags.append(tag)

        return sorted(dict.fromkeys(tags))

    def _parse_stake_points(self, value: Any) -> List[float]:
        """从桩号文本中提取一个或多个数值点。"""
        if value in (None, ""):
            return []
        if isinstance(value, (int, float)):
            return [float(value)]

        text = str(value)
        points = []
        for major, minor in STAKE_PATTERN.findall(text):
            major_value = float(major)
            if minor:
                major_value += int(minor) / 1000.0
            points.append(round(major_value, 3))
        return points

    def _coerce_stake(self, value: Any) -> Optional[float]:
        """将单个 stake 值转成浮点数。"""
        points = self._parse_stake_points(value)
        if not points:
            return None
        return points[0]

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """计算两点之间的 Haversine 距离。"""
        radius_km = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius_km * c

    def _clean_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _clean_float(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _clean_int(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
