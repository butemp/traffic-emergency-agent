"""录入数据 schema 定义 + 校验函数。

4 类数据：预案 / 专家 / 仓库 / 救援队。
每个数据类都给出：
- 必填字段 + 类型要求
- 唯一性键（用于查重）
- validate(payload, existing_ids) -> (ok, errors)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 数据文件路径
PLANS_DIR = PROJECT_ROOT / "data" / "预案" / "parsered_data"
PLAN_INDEX_PATH = PROJECT_ROOT / "data" / "预案" / "plan_index.json"
EXPERT_XLS_PATH = PROJECT_ROOT / "data" / "专家数据" / "expert_info.xls"
EXPERT_JSON_PATH = PROJECT_ROOT / "data" / "专家数据" / "expert_info.json"
WAREHOUSE_JSONL_PATH = PROJECT_ROOT / "data" / "仓库和队伍的物资数据" / "warehouse_dispatch_resources.jsonl"
TEAM_JSONL_PATH = PROJECT_ROOT / "data" / "仓库和队伍的物资数据" / "rescue_team_dispatch_resources.jsonl"

# 仓库 categories 合法枚举
WAREHOUSE_CATEGORIES = {
    "SIGN", "WARNING", "PPE", "FIRE", "TOOL",
    "VEHICLE", "MATERIAL", "RESCUE", "COMMS", "DEICE", "OTHER",
}

_PHONE_RE = re.compile(r"^[\d\-\+\(\)\s]{6,20}$")
_LAT_RANGE = (-90.0, 90.0)
_LON_RANGE = (-180.0, 180.0)


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ─── 预案 schema ────────────────────────────────────────

def validate_plan(payload: Any, existing_titles: Set[str]) -> Tuple[bool, List[str]]:
    """预案录入校验。payload 必须是 dict（parsered_data 风格 JSON）。"""
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["预案根节点必须是 dict（parsered_data 风格 JSON）"]

    cover = payload.get("封面")
    if not isinstance(cover, dict):
        errors.append("缺少必填字段 '封面'，或 '封面' 不是 dict")
    else:
        title = cover.get("标题")
        if not _is_nonempty_str(title):
            errors.append("缺少必填字段 '封面.标题'（必须非空字符串）")
        elif title.strip() in existing_titles:
            errors.append(f"预案 '封面.标题' 已存在: {title.strip()}（如需覆盖请加 --overwrite）")

    # 推荐字段（缺失只警告，不阻断）
    return (not errors), errors


# ─── 专家 schema ────────────────────────────────────────

EXPERT_REQUIRED_FIELDS = ("name",)
EXPERT_OPTIONAL_FIELDS = (
    "id", "sex", "birthday", "specialty_field", "duties", "professional_title",
    "work_unit", "education", "major", "graduation_school", "phone", "email",
    "address", "longitude", "latitude", "declaration_type", "remark",
)


def validate_expert(payload: Any, existing_ids: Set[str]) -> Tuple[bool, List[str]]:
    """专家录入校验。"""
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["专家记录必须是 dict"]

    for f in EXPERT_REQUIRED_FIELDS:
        if not _is_nonempty_str(payload.get(f)):
            errors.append(f"缺少必填字段 '{f}'（必须非空字符串）")

    # 至少一个联系方式
    phone = payload.get("phone")
    email = payload.get("email")
    if not _is_nonempty_str(phone) and not _is_nonempty_str(email):
        errors.append("'phone' 与 'email' 至少需要一个（非空字符串）")

    if _is_nonempty_str(phone) and not _PHONE_RE.match(str(phone).strip()):
        errors.append(f"'phone' 格式不合法: {phone!r}（应为 6-20 位数字+常见分隔符）")

    # 坐标可选；如果给了必须合法
    lon = payload.get("longitude")
    lat = payload.get("latitude")
    if lon not in (None, ""):
        if not _is_number(lon) or not (_LON_RANGE[0] <= float(lon) <= _LON_RANGE[1]):
            errors.append(f"'longitude' 不合法: {lon!r}（应为 -180~180 数字）")
    if lat not in (None, ""):
        if not _is_number(lat) or not (_LAT_RANGE[0] <= float(lat) <= _LAT_RANGE[1]):
            errors.append(f"'latitude' 不合法: {lat!r}（应为 -90~90 数字）")

    # id 重复
    eid = payload.get("id")
    if _is_nonempty_str(eid) and str(eid).strip() in existing_ids:
        errors.append(f"专家 id 已存在: {eid}（不传 id 系统会自动生成 uuid）")

    return (not errors), errors


# ─── 仓库 schema ────────────────────────────────────────

WAREHOUSE_REQUIRED_FIELDS = ("warehouse_name", "latitude", "longitude", "categories", "contact_phone")
WAREHOUSE_OPTIONAL_FIELDS = (
    "warehouse_id", "warehouse_type", "belong_org_code", "belong_org_name",
    "address", "road_code", "stake", "principal", "verification_state",
    "last_verified_at", "next_due_at", "remark",
    "material_item_count", "material_kind_count", "materials_by_category",
)


def validate_warehouse(payload: Any, existing_ids: Set[str]) -> Tuple[bool, List[str]]:
    """仓库录入校验（预聚合 JSON 格式）。"""
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["仓库记录必须是 dict"]

    if not _is_nonempty_str(payload.get("warehouse_name")):
        errors.append("缺少必填字段 'warehouse_name'（非空字符串）")

    lon = payload.get("longitude")
    lat = payload.get("latitude")
    if not _is_number(lon) or not (_LON_RANGE[0] <= float(lon) <= _LON_RANGE[1]):
        errors.append(f"'longitude' 缺失或不合法: {lon!r}（必须 -180~180 数字）")
    if not _is_number(lat) or not (_LAT_RANGE[0] <= float(lat) <= _LAT_RANGE[1]):
        errors.append(f"'latitude' 缺失或不合法: {lat!r}（必须 -90~90 数字）")

    cats = payload.get("categories")
    if not isinstance(cats, list) or not cats:
        errors.append(f"'categories' 缺失或为空 list；合法值: {sorted(WAREHOUSE_CATEGORIES)}")
    else:
        bad = [c for c in cats if c not in WAREHOUSE_CATEGORIES]
        if bad:
            errors.append(f"'categories' 含非法值: {bad}；合法值: {sorted(WAREHOUSE_CATEGORIES)}")

    phone = payload.get("contact_phone")
    if not _is_nonempty_str(phone):
        errors.append("缺少必填字段 'contact_phone'（非空字符串）")
    elif not _PHONE_RE.match(str(phone).strip()):
        errors.append(f"'contact_phone' 格式不合法: {phone!r}")

    # materials_by_category 是可选的；如果给了须为 dict，key 必须在合法 categories 内
    mbc = payload.get("materials_by_category")
    if mbc is not None and not isinstance(mbc, dict):
        errors.append("'materials_by_category' 必须是 dict（key 为类别编码）")

    # id 重复
    wid = payload.get("warehouse_id")
    if _is_nonempty_str(wid) and str(wid).strip() in existing_ids:
        errors.append(f"仓库 id 已存在: {wid}（不传 id 系统会自动生成 uuid）")

    return (not errors), errors


# ─── 救援队 schema ──────────────────────────────────────

TEAM_REQUIRED_FIELDS = ("team_name", "latitude", "longitude")
TEAM_OPTIONAL_FIELDS = (
    "team_id", "team_code", "team_type", "team_size", "status",
    "leader_name", "leader_phone", "jurisdiction_unit", "jurisdiction_leader", "jurisdiction_phone",
    "specialties", "address", "road_code", "stake", "verification_state",
    "last_verified_at", "next_due_at", "remark",
    "categories", "material_item_count", "material_kind_count", "materials_by_category",
)


def validate_team(payload: Any, existing_ids: Set[str]) -> Tuple[bool, List[str]]:
    """救援队录入校验（预聚合 JSON 格式）。"""
    errors: List[str] = []
    if not isinstance(payload, dict):
        return False, ["救援队记录必须是 dict"]

    if not _is_nonempty_str(payload.get("team_name")):
        errors.append("缺少必填字段 'team_name'（非空字符串）")

    lon = payload.get("longitude")
    lat = payload.get("latitude")
    if not _is_number(lon) or not (_LON_RANGE[0] <= float(lon) <= _LON_RANGE[1]):
        errors.append(f"'longitude' 缺失或不合法: {lon!r}（必须 -180~180 数字）")
    if not _is_number(lat) or not (_LAT_RANGE[0] <= float(lat) <= _LAT_RANGE[1]):
        errors.append(f"'latitude' 缺失或不合法: {lat!r}（必须 -90~90 数字）")

    # 至少一个联系方式
    leader_phone = payload.get("leader_phone")
    jur_phone = payload.get("jurisdiction_phone")
    if not _is_nonempty_str(leader_phone) and not _is_nonempty_str(jur_phone):
        errors.append("'leader_phone' 与 'jurisdiction_phone' 至少需要一个（非空字符串）")
    for fname, fval in (("leader_phone", leader_phone), ("jurisdiction_phone", jur_phone)):
        if _is_nonempty_str(fval) and not _PHONE_RE.match(str(fval).strip()):
            errors.append(f"'{fname}' 格式不合法: {fval!r}")

    # team_size 可选；如果给了须为 int
    ts = payload.get("team_size")
    if ts is not None and not isinstance(ts, int):
        try:
            int(ts)
        except (TypeError, ValueError):
            errors.append(f"'team_size' 必须是整数: {ts!r}")

    # id 重复
    tid = payload.get("team_id")
    if _is_nonempty_str(tid) and str(tid).strip() in existing_ids:
        errors.append(f"救援队 id 已存在: {tid}（不传 id 系统会自动生成 uuid）")

    return (not errors), errors


# ─── 通用工具 ──────────────────────────────────────────

def format_errors(data_type: str, errors: List[str]) -> str:
    """统一报错格式。"""
    lines = [f"❌ {data_type} 录入失败：{len(errors)} 个错误"]
    for i, e in enumerate(errors, 1):
        lines.append(f"  {i}. {e}")
    return "\n".join(lines)
