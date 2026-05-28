"""TOCC 实时数据 API 客户端与字段适配器。"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

import requests


DEFAULT_TOCC_BASE_URL = "https://tocc.itsgx.cn:10003/prod-api"
DEFAULT_TOCC_API_KEY = "mZRsWLNomAaBrcor9skwqbQUvbwTsFYb"


CATEGORY_KEYWORDS = {
    "SIGN": ("标志", "标牌", "指示牌", "警示牌", "限速牌", "导向牌", "标识牌"),
    "WARNING": ("锥", "警示", "爆闪", "反光", "水马", "护栏", "隔离", "警戒", "示警"),
    "PPE": ("安全帽", "反光衣", "反光背心", "防护", "手套", "雨衣", "口罩", "护目镜"),
    "FIRE": ("灭火", "消防", "水带", "消防斧", "消防泵", "泡沫", "干粉"),
    "TOOL": ("切割", "发电机", "电镐", "油锯", "铁锹", "铲", "泵", "吊", "挖掘", "装载", "工具"),
    "VEHICLE": ("车", "车辆", "拖车", "清障车", "货车", "吊车", "皮卡", "救护车"),
    "MATERIAL": ("砂", "沙", "编织袋", "麻袋", "土工布", "木桩", "钢板", "水泥", "材料"),
    "RESCUE": ("救生", "救援", "担架", "绳", "破拆", "急救", "救护", "搜救"),
    "COMMS": ("对讲", "通信", "照明", "手电", "电筒", "灯", "电台", "扩音", "喇叭"),
    "DEICE": ("除冰", "融雪", "防滑", "撒布", "盐", "铲雪", "雪"),
}


class ToccApiError(RuntimeError):
    """TOCC API 调用或响应结构异常。"""


class ToccApiClient:
    """TOCC API 客户端。

    该类只负责请求与字段适配，不在导入时发起网络调用。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or os.getenv("TOCC_BASE_URL") or DEFAULT_TOCC_BASE_URL).rstrip("/")
        self.api_key = api_key or os.getenv("TOCC_API_KEY") or DEFAULT_TOCC_API_KEY
        self.timeout = timeout if timeout is not None else self._float_env("TOCC_TIMEOUT_SECONDS", 15.0)
        self.headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    def get_experts(self, **filters: Any) -> List[Dict[str, Any]]:
        """获取专家列表。"""
        payload = self._get_json("/expertAI/list", params=self._clean_params(filters))
        if payload.get("code") != 200:
            raise ToccApiError(f"专家接口返回异常: code={payload.get('code')}, msg={payload.get('msg')}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ToccApiError("专家接口响应缺少 data 列表")
        return data

    def get_all_warehouses(self, page_size: int = 100, **filters: Any) -> List[Dict[str, Any]]:
        """分页获取全部仓库列表。"""
        page_size = max(1, int(page_size or 100))
        page_num = 1
        total: Optional[int] = None
        rows: List[Dict[str, Any]] = []

        while True:
            payload = self.get_warehouses_page(page=page_num, page_size=page_size, **filters)
            page_rows = payload.get("rows") or []
            if not isinstance(page_rows, list):
                raise ToccApiError("仓库接口响应 rows 不是列表")

            rows.extend(page_rows)
            total_value = payload.get("total")
            if total is None and isinstance(total_value, int):
                total = total_value

            if not page_rows:
                break
            if total is not None and len(rows) >= total:
                break
            if len(page_rows) < page_size:
                break
            page_num += 1

        return rows[:total] if total is not None else rows

    def get_warehouses_page(self, page: int = 1, page_size: int = 100, **filters: Any) -> Dict[str, Any]:
        """获取单页仓库列表。"""
        params = {
            "pageNum": page,
            "pageSize": page_size,
            **self._clean_params(filters),
        }
        payload = self._get_json("/warehouseAi/list", params=params)
        if payload.get("code") != 200:
            raise ToccApiError(f"仓库接口返回异常: code={payload.get('code')}, msg={payload.get('msg')}")
        return payload

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                headers=self.headers,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise ToccApiError(f"TOCC API 请求失败: {path}: {error}") from error

        if not isinstance(payload, dict):
            raise ToccApiError(f"TOCC API 响应不是 JSON 对象: {path}")
        return payload

    @staticmethod
    def _clean_params(params: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in params.items() if value not in (None, "", [], {})}

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        value = os.getenv(name)
        if not value:
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default


def map_expert_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """将专家 API 驼峰字段映射为项目内部下划线字段。"""
    return {
        "id": _text(record.get("id")),
        "name": _text(record.get("name")),
        "sex": _text(record.get("sex")),
        "birthday": _text(record.get("birthday")),
        "dept_id": _text(record.get("deptId")),
        "dept_name": _text(record.get("deptName")),
        "specialty_field": _text(record.get("specialtyField")),
        "duties": _text(record.get("duties")),
        "professional_title": _text(record.get("professionalTitle")),
        "work_unit": _text(record.get("workUnit")),
        "education": _text(record.get("education")),
        "major": _text(record.get("major")),
        "graduation_school": _text(record.get("graduationSchool")),
        "phone": _text(record.get("phone")),
        "email": _text(record.get("email")),
        "address": _text(record.get("address")),
        "longitude": _float(record.get("longitude")),
        "latitude": _float(record.get("latitude")),
        "declaration_type": _text(record.get("declarationType")),
        "exper_status": _text(record.get("experStatus")),
        "remark": _text(record.get("remark")),
        "data_source": "tocc_api",
    }


def map_warehouse_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """将仓库 API 驼峰字段映射为资源调度引擎内部字段。"""
    materials_by_category = build_materials_by_category(record)
    categories = sorted(materials_by_category.keys())
    return {
        "warehouse_id": _text(record.get("id")),
        "warehouse_name": _text(record.get("warehouseName")),
        "warehouse_type": _text(record.get("warehouseType")),
        "warehouse_type_name": _text(record.get("warehouseTypeName")),
        "belong_org_code": _text(record.get("belongOrgCode")),
        "belong_org_name": _text(record.get("belongOrgName")),
        "address": _text(record.get("address")),
        "principal": _text(record.get("principal")),
        "contact_phone": _text(record.get("contactPhone")),
        "road_code": _text(record.get("roadCode")),
        "stake": record.get("stake"),
        "latitude": _float(record.get("latitude")),
        "longitude": _float(record.get("longitude")),
        "remark": _text(record.get("remark")),
        "create_time": _text(record.get("createTime")),
        "verification_state": _text(record.get("verificationState")),
        "unitor": _text(record.get("unitor")),
        "unitor_id": _text(record.get("unitorId")),
        "unitor_tel": _text(record.get("unitorTel")),
        "next_due_at": _text(record.get("nextDueAt")),
        "categories": categories,
        "material_item_count": sum(len(items) for items in materials_by_category.values()),
        "material_kind_count": len(categories),
        "materials_by_category": materials_by_category,
        "total_material_count": record.get("totalMaterialCount"),
        "api_distance": record.get("distance"),
        "data_source": "tocc_api",
    }


def build_materials_by_category(record: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """从仓库 API 的 materials/equipments 生成现有调度结构。"""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in _iter_material_items(record):
        name = _first_text(
            item,
            "materialName",
            "equipmentName",
            "equipName",
            "name",
            "material_name",
            "equipment_name",
        )
        if not name:
            continue
        category = infer_material_category(name)
        grouped.setdefault(category, []).append(
            {
                "name": name,
                "quantity": _first_value(item, "quantity", "num", "count", "amount", "materialNum", "stock", default=0),
                "unit": _first_text(item, "unit", "unitName", "materialUnit", "equipmentUnit"),
                "spec_model": _first_text(item, "specModel", "model", "specification", "spec"),
                "material_type": _first_text(item, "materialType", "equipmentType", "type"),
                "material_ids": [_text(item.get("id"))] if item.get("id") not in (None, "") else [],
            }
        )
    return grouped


def infer_material_category(name: str) -> str:
    """按物资名称粗映射到调度引擎内部类别。"""
    normalized = _text(name).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.lower() in normalized for keyword in keywords):
            return category
    return "OTHER"


def _iter_material_items(record: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for field_name in ("materials", "equipments"):
        value = record.get(field_name)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item


def _first_value(record: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return default


def _first_text(record: Dict[str, Any], *keys: str) -> str:
    return _text(_first_value(record, *keys))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
