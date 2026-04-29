"""专家库检索工具。"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .base import BaseTool

logger = logging.getLogger(__name__)


INCIDENT_EXPERT_KEYWORDS = {
    "hazmat": ("危化品", "危险货物", "危险品", "化学", "泄漏", "爆炸"),
    "geology": ("滑坡", "塌方", "泥石流", "边坡", "地质", "岩土", "水毁"),
    "bridge": ("桥梁", "桥", "涵洞", "隧道", "结构", "坍塌"),
    "traffic": ("交通", "道路运输", "公路", "高速", "车辆", "拥堵"),
    "construction": ("施工", "工程", "建设", "养护", "抢修"),
    "safety": ("安全", "应急", "风险", "事故", "安全管理"),
    "fire": ("火灾", "消防", "燃烧", "爆燃"),
    "rail": ("轨道", "地铁", "城市轨道"),
    "port": ("港口", "航道", "水运", "码头", "船舶"),
}


class SearchExperts(BaseTool):
    """按专业方向检索应急专家。"""

    def __init__(self, data_path: Optional[str] = None):
        default_path = Path(__file__).resolve().parents[2] / "data" / "专家数据" / "expert_info.xls"
        super().__init__(data_path=data_path or str(default_path))
        self.experts = self._load_experts(Path(self.data_path))
        logger.info("专家库加载完成: experts=%s", len(self.experts))

    @property
    def name(self) -> str:
        return "search_experts"

    @property
    def description(self) -> str:
        return (
            "从本地专家库中检索适合参与研判的专家，返回专家姓名、专业方向、职称、单位和联系方式。"
            "适用于危化品、地质灾害、桥隧结构、交通安全、消防、港航等需要专家技术支持的场景。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "专业关键词，如 危险货物、岩土、桥梁、交通安全、消防",
                },
                "incident_type": {
                    "type": "string",
                    "description": "事故类型或灾害类型，如 危化品泄漏、山体滑坡、桥梁垮塌、交通事故",
                },
                "longitude": {
                    "type": "number",
                    "description": "事故点经度。可选，专家有坐标时用于距离排序",
                },
                "latitude": {
                    "type": "number",
                    "description": "事故点纬度。可选，专家有坐标时用于距离排序",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回专家数量，默认 5",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["keywords"],
        }

    def execute(
        self,
        keywords: List[str],
        incident_type: str = "",
        longitude: Optional[float] = None,
        latitude: Optional[float] = None,
        max_results: int = 5,
    ) -> str:
        query_terms = self._normalize_terms([*(keywords or []), incident_type])
        query_terms.extend(self._expand_incident_terms(incident_type))
        query_terms = list(dict.fromkeys(query_terms))

        scored = []
        for expert in self.experts:
            score, matched_terms = self._score_expert(expert, query_terms)
            if score <= 0:
                continue

            distance_km = None
            if longitude is not None and latitude is not None:
                distance_km = self._distance_to_expert(latitude, longitude, expert)
                if distance_km is not None:
                    score += max(0.0, 15.0 - min(distance_km, 150.0) / 10.0)

            scored.append((score, distance_km, matched_terms, expert))

        scored.sort(key=lambda item: (item[0], -(item[1] or 99999)), reverse=True)
        limit = max(1, min(int(max_results or 5), 20))

        results = []
        for score, distance_km, matched_terms, expert in scored[:limit]:
            results.append(
                {
                    "expert_id": expert["id"],
                    "name": expert["name"],
                    "specialty_field": expert["specialty_field"],
                    "professional_title": expert["professional_title"],
                    "duties": expert["duties"],
                    "work_unit": expert["work_unit"],
                    "major": expert["major"],
                    "phone": expert["phone"],
                    "email": expert["email"],
                    "address": expert["address"],
                    "longitude": expert["longitude"],
                    "latitude": expert["latitude"],
                    "distance_km": round(distance_km, 2) if distance_km is not None else None,
                    "match_score": round(score, 1),
                    "matched_terms": matched_terms,
                    "dispatch_note": "建议由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持",
                }
            )

        return json.dumps(
            {
                "status": "success",
                "query_terms": query_terms,
                "count": len(results),
                "experts": results,
                "data_note": "专家库坐标覆盖有限，距离仅在专家记录含经纬度时计算；调度前需人工确认可用状态。",
            },
            ensure_ascii=False,
            indent=2,
        )

    def _load_experts(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"专家库文件不存在: {path}")

        try:
            import xlrd
        except Exception as error:
            raise RuntimeError("读取 expert_info.xls 需要安装 xlrd") from error

        book = xlrd.open_workbook(str(path))
        sheet = book.sheet_by_index(0)
        headers = [str(item).strip() for item in sheet.row_values(0)]
        index = {name: pos for pos, name in enumerate(headers)}

        experts: List[Dict[str, Any]] = []
        for row_index in range(1, sheet.nrows):
            row = sheet.row_values(row_index)
            if self._cell(row, index, "del_flag") in {"1", "1.0"}:
                continue

            name = self._cell(row, index, "name")
            if not name:
                continue

            experts.append(
                {
                    "id": self._cell(row, index, "id"),
                    "name": name,
                    "specialty_field": self._cell(row, index, "specialty_field"),
                    "duties": self._cell(row, index, "duties"),
                    "professional_title": self._cell(row, index, "professional_title"),
                    "work_unit": self._cell(row, index, "work_unit"),
                    "major": self._cell(row, index, "major"),
                    "phone": self._cell(row, index, "phone"),
                    "email": self._cell(row, index, "email"),
                    "address": self._cell(row, index, "address"),
                    "longitude": self._clean_float(self._cell(row, index, "longitude")),
                    "latitude": self._clean_float(self._cell(row, index, "latitude")),
                    "on_duty_status": self._cell(row, index, "on_duty_status"),
                    "verification_state": self._cell(row, index, "verification_state"),
                }
            )
        return experts

    def _score_expert(self, expert: Dict[str, Any], query_terms: Iterable[str]) -> tuple[float, List[str]]:
        searchable = " ".join(
            str(expert.get(key) or "")
            for key in ("specialty_field", "duties", "professional_title", "work_unit", "major", "address")
        )
        score = 0.0
        matched_terms: List[str] = []
        for term in query_terms:
            if not term:
                continue
            if term in searchable:
                matched_terms.append(term)
                score += 20.0 if term in str(expert.get("specialty_field") or "") else 10.0

        if expert.get("phone"):
            score += 5.0
        if "高级" in str(expert.get("professional_title") or ""):
            score += 5.0
        return score, matched_terms

    def _expand_incident_terms(self, incident_type: str) -> List[str]:
        text = incident_type or ""
        expanded: List[str] = []
        for keywords in INCIDENT_EXPERT_KEYWORDS.values():
            if any(keyword in text for keyword in keywords):
                expanded.extend(keywords)
        return expanded

    def _normalize_terms(self, values: Iterable[Any]) -> List[str]:
        terms: List[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            terms.extend(item for item in re.split(r"[,，、\s]+", text) if item)
        return terms

    def _distance_to_expert(
        self,
        incident_latitude: float,
        incident_longitude: float,
        expert: Dict[str, Any],
    ) -> Optional[float]:
        latitude = expert.get("latitude")
        longitude = expert.get("longitude")
        if latitude is None or longitude is None:
            return None
        return self._haversine_km(incident_latitude, incident_longitude, latitude, longitude)

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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

    def _cell(self, row: List[Any], index: Dict[str, int], key: str) -> str:
        position = index.get(key)
        if position is None or position >= len(row):
            return ""
        value = row[position]
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    def _clean_float(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
