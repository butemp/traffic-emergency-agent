"""
将“仓库和队伍的物资数据”（.xls）格式化为 Map Resources JSON，便于 Agent 工具检索。

输入目录默认：data/仓库和队伍的物资数据
输出目录默认：data/graph

导出文件：
- resources_warehouses.json  仓库资源列表
- resources_teams.json       队伍资源列表
- resources_all.json         合并后的资源列表

使用示例：
  python -m scripts.convert_inventory_to_map_resources \
      --input-dir data/仓库和队伍的物资数据 \
      --output-dir data/graph

依赖：pandas、xlrd（读取 .xls）。如未安装，请先：
  pip install pandas xlrd
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def _ensure_deps():
    try:
        import pandas as _pd  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "依赖缺失：需要 pandas\n"
            "请先安装依赖：pip install pandas xlrd\n"
            f"原始错误：{e}"
        )


_ensure_deps()
import pandas as pd  # noqa: E402


def _find_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    """在 DataFrame 列名中按不区分大小写/下划线匹配最合适列名。"""
    norm = {c.lower().replace("_", ""): c for c in cols}
    for cand in candidates:
        key = cand.lower().replace("_", "")
        if key in norm:
            return norm[key]
    # 次优：包含匹配
    for c in cols:
        c_norm = c.lower().replace("_", "")
        for cand in candidates:
            k = cand.lower().replace("_", "")
            if k in c_norm:
                return c
    return None


def _coerce_phone(x: object) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        # Excel 读入为浮点的常见情况
        s = s[:-2]
    return s


def _to_float(x: object) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        s = str(x).strip().replace(",", "")
        return float(s)
    except Exception:
        return None


def _excel_date_to_iso(x: object) -> Optional[str]:
    # 仅在像是 Excel 序列数或可解析的日期时转换
    try:
        # pandas 读取后通常已是 datetime 或 NaT
        if pd.isna(x):
            return None
        if isinstance(x, (datetime, pd.Timestamp)):
            return pd.to_datetime(x).isoformat()
        # 尝试按 Excel 序列数转换（1900）
        val = float(x)
        if 20000 <= val <= 60000:
            base = datetime(1899, 12, 30)
            return (base + pd.to_timedelta(int(val), unit="D")).isoformat()
        # 兜底尝试解析
        return pd.to_datetime(x, errors="coerce").isoformat() if x else None
    except Exception:
        return None


@dataclass
class Tables:
    materials: pd.DataFrame
    warehouses: pd.DataFrame
    wh_map: pd.DataFrame
    teams: pd.DataFrame
    team_map: pd.DataFrame


def load_tables(input_dir: str) -> Tables:
    def read_xls(path: str) -> pd.DataFrame:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        return pd.read_excel(path, sheet_name=0, engine="xlrd")

    materials = read_xls(os.path.join(input_dir, "em_material.xls"))
    warehouses = read_xls(os.path.join(input_dir, "em_warehouse.xls"))
    wh_map = read_xls(os.path.join(input_dir, "em_warehouse_material.xls"))
    teams = read_xls(os.path.join(input_dir, "rescue_team.xls"))
    team_map = read_xls(os.path.join(input_dir, "rescue_team_material.xls"))

    return Tables(materials, warehouses, wh_map, teams, team_map)


def clean_and_index(t: Tables) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """基础清洗与建立便于聚合的索引列。返回 (materials, warehouses, teams)。"""
    # 规范主键列名
    def norm_id(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
        id_col = _find_col(df.columns.tolist(), ["id", "ID"]) or "id"
        if id_col not in df.columns:
            df[id_col] = None
        # 过滤空/异常 id
        df = df.copy()
        df[id_col] = df[id_col].astype(str).str.strip()
        df = df[df[id_col].notna() & (df[id_col] != "") & (~df[id_col].isin(["#NUM!", "nan"]))]
        return df, id_col

    materials, mat_id = norm_id(t.materials)
    warehouses, wh_id = norm_id(t.warehouses)
    teams, team_id = norm_id(t.teams)

    # 关键字段映射（尽可能宽松匹配）
    # materials
    m_name = _find_col(materials.columns.tolist(), ["material_name", "name"]) or "material_name"
    m_spec = _find_col(materials.columns.tolist(), ["spec_model", "spec", "model"]) or "spec_model"
    m_unit = _find_col(materials.columns.tolist(), ["unit"]) or "unit"
    m_qty = _find_col(materials.columns.tolist(), ["quantity", "qty"]) or "quantity"
    m_del = _find_col(materials.columns.tolist(), ["del_flag", "deleted"]) or "del_flag"
    m_status = _find_col(materials.columns.tolist(), ["status"]) or "status"

    for col in [m_name, m_spec, m_unit, m_status]:
        if col not in materials.columns:
            materials[col] = None
    if m_qty not in materials.columns:
        materials[m_qty] = 0
    if m_del not in materials.columns:
        materials[m_del] = 0

    # 统一数量为数值
    materials[m_qty] = pd.to_numeric(materials[m_qty], errors="coerce").fillna(0)
    # 只保留未删除（如有该字段）
    try:
        materials = materials[(materials[m_del].fillna(0).astype(float) == 0)]
    except Exception:
        pass

    # warehouses
    wh_name = _find_col(warehouses.columns.tolist(), ["warehouse_name", "name"]) or "warehouse_name"
    wh_addr = _find_col(warehouses.columns.tolist(), ["address"]) or "address"
    wh_lat = _find_col(warehouses.columns.tolist(), ["latitude", "lat"]) or "latitude"
    wh_lon = _find_col(warehouses.columns.tolist(), ["longitude", "lon", "lng"]) or "longitude"
    wh_principal = _find_col(warehouses.columns.tolist(), ["principal", "负责人"]) or "principal"
    wh_phone = _find_col(warehouses.columns.tolist(), ["contact_phone", "phone", "tel"]) or "contact_phone"
    wh_type = _find_col(warehouses.columns.tolist(), ["warehouse_type"]) or "warehouse_type"

    for col in [wh_name, wh_addr, wh_lat, wh_lon, wh_phone, wh_type, wh_principal]:
        if col not in warehouses.columns:
            warehouses[col] = None

    # 规范坐标
    warehouses[wh_lat] = warehouses[wh_lat].apply(_to_float)
    warehouses[wh_lon] = warehouses[wh_lon].apply(_to_float)

    # teams
    team_name_col = _find_col(teams.columns.tolist(), ["team_name", "name"]) or "team_name"
    team_addr_col = _find_col(teams.columns.tolist(), ["address"]) or "address"
    team_lat_col = _find_col(teams.columns.tolist(), ["latitude", "lat"]) or "latitude"
    team_lon_col = _find_col(teams.columns.tolist(), ["longitude", "lon", "lng"]) or "longitude"
    team_type_col = _find_col(teams.columns.tolist(), ["team_type"]) or "team_type"
    team_size_col = _find_col(teams.columns.tolist(), ["team_size"]) or "team_size"
    team_leader_col = _find_col(teams.columns.tolist(), ["leader", "principal"]) or "leader"
    team_phone_col = _find_col(teams.columns.tolist(), ["leader_phone", "contact_phone", "phone", "tel"]) or "leader_phone"

    for col in [team_name_col, team_addr_col, team_lat_col, team_lon_col, team_type_col, team_size_col, team_leader_col, team_phone_col]:
        if col not in teams.columns:
            teams[col] = None

    teams[team_lat_col] = teams[team_lat_col].apply(_to_float)
    teams[team_lon_col] = teams[team_lon_col].apply(_to_float)

    # 添加便捷索引名，后续构造 JSON 使用
    warehouses = warehouses.rename(columns={
        wh_name: "_name", wh_addr: "_address", wh_lat: "_lat", wh_lon: "_lon",
        wh_phone: "_phone", wh_type: "_type", wh_principal: "_principal", wh_id: "_id"
    })
    teams = teams.rename(columns={
        team_name_col: "_name", team_addr_col: "_address", team_lat_col: "_lat", team_lon_col: "_lon",
        team_type_col: "_type", team_size_col: "_size", team_leader_col: "_leader", team_phone_col: "_phone", team_id: "_id"
    })
    materials = materials.rename(columns={
        mat_id: "_id", m_name: "_name", m_spec: "_spec", m_unit: "_unit", m_qty: "_qty", m_status: "_status"
    })

    return materials, warehouses, teams


def _aggregate_capacity_for_warehouses(materials: pd.DataFrame, wh_map: pd.DataFrame) -> pd.DataFrame:
    # 关联 wh_map(material_id, warehouse_id) → materials(_qty)
    wh_mid = _find_col(wh_map.columns.tolist(), ["material_id", "mid", "materialid"]) or "material_id"
    wh_wid = _find_col(wh_map.columns.tolist(), ["warehouse_id", "wid", "warehouseid"]) or "warehouse_id"

    df = wh_map[[wh_mid, wh_wid]].copy()
    df.columns = ["material_id", "warehouse_id"]

    m = materials[["_id", "_name", "_qty", "_unit"]].copy()
    merged = df.merge(m, left_on="material_id", right_on="_id", how="left")

    # 聚合：每个仓库的物资条目数、总数量
    agg = merged.groupby("warehouse_id").agg(
        total_items=("material_id", "count"),
        total_quantity=("_qty", "sum")
    ).reset_index()
    return agg


def _aggregate_capacity_for_teams(materials: pd.DataFrame, team_map: pd.DataFrame) -> pd.DataFrame:
    tm_mid = _find_col(team_map.columns.tolist(), ["material_id"]) or "material_id"
    tm_tid = _find_col(team_map.columns.tolist(), ["team_id"]) or "team_id"

    df = team_map[[tm_mid, tm_tid]].copy()
    df.columns = ["material_id", "team_id"]

    m = materials[["_id", "_name", "_qty", "_unit"]].copy()
    merged = df.merge(m, left_on="material_id", right_on="_id", how="left")

    agg = merged.groupby("team_id").agg(
        total_items=("material_id", "count"),
        total_quantity=("_qty", "sum")
    ).reset_index()
    return agg


def _build_inventory_breakdown(
    materials: pd.DataFrame,
    link_df: pd.DataFrame,
    link_id_col: str,
    top_k_per_entity: int = 200,
) -> Dict[str, List[Dict]]:
    """为每个实体（仓库或队伍）构建聚合后的物资清单。

    聚合键：material_name + spec + unit；数量汇总。
    返回：{entity_id: [{material_name, spec_model, unit, quantity}]}
    """
    mid = _find_col(link_df.columns.tolist(), ["material_id"]) or "material_id"
    df = link_df[[mid, link_id_col]].copy()
    df.columns = ["material_id", "entity_id"]

    m = materials[["_id", "_name", "_spec", "_unit", "_qty"]].copy()
    merged = df.merge(m, left_on="material_id", right_on="_id", how="left")

    # 聚合到实体维度
    grp = (
        merged.groupby(["entity_id", "_name", "_spec", "_unit"], dropna=False)["_qty"].sum().reset_index()
    )
    # 对每个实体排序并截断 top_k
    grp["_qty"] = grp["_qty"].fillna(0)
    grp.sort_values(["entity_id", "_qty"], ascending=[True, False], inplace=True)

    result: Dict[str, List[Dict]] = {}
    for ent_id, sub in grp.groupby("entity_id"):
        items = []
        for _, r in sub.head(top_k_per_entity).iterrows():
            items.append({
                "material_name": (str(r["_name"]) if pd.notna(r["_name"]) else ""),
                "spec_model": (str(r["_spec"]) if pd.notna(r["_spec"]) else ""),
                "unit": (str(r["_unit"]) if pd.notna(r["_unit"]) else ""),
                "quantity": float(r["_qty"]) if pd.notna(r["_qty"]) else 0.0,
            })
        result[str(ent_id)] = items
    return result


def _infer_capabilities_from_items(items: List[Dict]) -> List[str]:
    """基于物资名称/规格的关键词提取能力标签。"""
    if not items:
        return []
    caps = set()
    rules = [
        ("排涝", ["水泵", "抽水", "排涝", "发电机", "沙袋", "排水"]),
        ("交通管制", ["反光锥", "警示", "路锥", "导向", "限速", "警戒线", "锥桶", "标志"]),
        ("破拆救援", ["破拆", "液压剪", "扩张器", "千斤顶", "切割", "救援三脚架"]),
        ("清障拖移", ["拖车", "牵引", "清障", "吊车", "绞盘"]),
        ("医疗急救", ["担架", "急救", "氧气", "AED", "绷带", "止血", "救护"]),
        ("危化处置", ["泡沫", "灭火", "干粉", "吸附棉", "围油栏", "防化"]),
        ("通信照明", ["对讲机", "照明", "探照灯", "手电", "信号"]),
    ]
    for it in items[:200]:  # 仅截取前200条材料以控制计算量
        text = (it.get("material_name", "") + " " + it.get("spec_model", "")).lower()
        for tag, kws in rules:
            if any(kw.lower() in text for kw in kws):
                caps.add(tag)
    return sorted(caps)


def _infer_team_type_to_resource_type(team_type: Optional[str]) -> str:
    s = (team_type or "").lower()
    if any(k in s for k in ["fire", "消防"]):
        return "fire"
    if any(k in s for k in ["police", "公安", "交警"]):
        return "police"
    if any(k in s for k in ["medical", "医院", "医", "急救", "120"]):
        return "medical"
    return "transport"  # 兜底


def build_resources_json(
    materials: pd.DataFrame,
    warehouses: pd.DataFrame,
    teams: pd.DataFrame,
    wh_map: pd.DataFrame,
    team_map: pd.DataFrame,
) -> Tuple[List[Dict], List[Dict]]:
    wh_capacity = _aggregate_capacity_for_warehouses(materials, wh_map)
    team_capacity = _aggregate_capacity_for_teams(materials, team_map)

    wh_cap_dict = {str(r["warehouse_id"]): {"total_items": int(r["total_items"]), "total_quantity": float(r["total_quantity"]) } for _, r in wh_capacity.iterrows()}
    team_cap_dict = {str(r["team_id"]): {"total_items": int(r["total_items"]), "total_quantity": float(r["total_quantity"]) } for _, r in team_capacity.iterrows()}

    today = datetime.now().date().isoformat()

    # 为资源构建“物资明细”索引
    wh_inventory = _build_inventory_breakdown(materials, wh_map, link_id_col="warehouse_id")
    team_inventory = _build_inventory_breakdown(materials, team_map, link_id_col="team_id")

    wh_resources: List[Dict] = []
    for _, row in warehouses.iterrows():
        _id = str(row.get("_id", "")).strip()
        if not _id:
            continue
        lat = row.get("_lat")
        lon = row.get("_lon")
        # 需要坐标用于地图检索
        if lat is None or lon is None:
            continue

        cap = wh_cap_dict.get(_id, {"total_items": 0, "total_quantity": 0.0})
        # 物资明细
        items = wh_inventory.get(_id, [])
        inferred_caps = _infer_capabilities_from_items(items)

        res = {
            "id": f"wh_{_id}",
            "name": str(row.get("_name", "")).strip() or f"仓库#{_id}",
            "type": "inventory",
            "status": "active",
            "location": {
                "latitude": lat,
                "longitude": lon,
                "address": str(row.get("_address", "") or "").strip(),
            },
            "description": {
                "summary": (str(row.get("_type", "") or "").strip() or "物资仓库"),
                "capabilities": inferred_caps,
                "capacity": {
                    "material_items": cap["total_items"],
                    "material_quantity_sum": round(cap["total_quantity"], 2),
                },
            },
            "inventory": {
                "items": items,
                "note": "items 为按(名称+规格+单位)聚合后的数量汇总，最多返回200条"
            },
            "contact": {
                "general_phone": _coerce_phone(row.get("_phone")),
                "duty_roster": [],
                "default_contact": {
                    "name": str(row.get("_principal", "") or "").strip() or "总值班",
                    "phone": _coerce_phone(row.get("_phone")),
                },
            },
            "metadata": {
                "last_updated": today,
                "priority_level": 2,
            },
        }
        wh_resources.append(res)

    team_resources: List[Dict] = []
    for _, row in teams.iterrows():
        _id = str(row.get("_id", "")).strip()
        if not _id:
            continue
        lat = row.get("_lat")
        lon = row.get("_lon")
        if lat is None or lon is None:
            continue

        cap = team_cap_dict.get(_id, {"total_items": 0, "total_quantity": 0.0})
        team_type = str(row.get("_type", "") or "")
        res_type = _infer_team_type_to_resource_type(team_type)
        items = team_inventory.get(_id, [])
        inferred_caps = _infer_capabilities_from_items(items)

        res = {
            "id": f"team_{_id}",
            "name": str(row.get("_name", "")).strip() or f"队伍#{_id}",
            "type": res_type,
            "status": "active",
            "location": {
                "latitude": lat,
                "longitude": lon,
                "address": str(row.get("_address", "") or "").strip(),
            },
            "description": {
                "summary": (team_type.strip() or "救援队伍"),
                "capabilities": sorted({*(inferred_caps or []), *(set([team_type.strip()]) if team_type.strip() else set())}),
                "capacity": {
                    "team_size": int(row.get("_size") or 0) if pd.notna(row.get("_size")) else 0,
                    "material_items": cap["total_items"],
                    "material_quantity_sum": round(cap["total_quantity"], 2),
                },
            },
            "inventory": {
                "items": items,
                "note": "items 为按(名称+规格+单位)聚合后的数量汇总，最多返回200条"
            },
            "contact": {
                "general_phone": _coerce_phone(row.get("_phone")),
                "duty_roster": [],
                "default_contact": {
                    "name": str(row.get("_leader", "") or "").strip() or "值班负责人",
                    "phone": _coerce_phone(row.get("_phone")),
                },
            },
            "metadata": {
                "last_updated": today,
                "priority_level": 2,
            },
        }
        team_resources.append(res)

    return wh_resources, team_resources


def main():
    parser = argparse.ArgumentParser(description="将仓库/队伍 .xls 数据导出为 Map Resources JSON")
    parser.add_argument("--input-dir", default=os.path.join("data", "仓库和队伍的物资数据"))
    parser.add_argument("--output-dir", default=os.path.join("data", "graph"))
    parser.add_argument("--pretty", action="store_true", help="美化 JSON 输出")
    args = parser.parse_args()

    tables = load_tables(args.input_dir)
    materials, warehouses, teams = clean_and_index(tables)

    wh_resources, team_resources = build_resources_json(
        materials, warehouses, teams, tables.wh_map, tables.team_map
    )

    os.makedirs(args.output_dir, exist_ok=True)
    indent = 2 if args.pretty else None

    out_wh = os.path.join(args.output_dir, "resources_warehouses.json")
    out_team = os.path.join(args.output_dir, "resources_teams.json")
    out_all = os.path.join(args.output_dir, "resources_all.json")

    with open(out_wh, "w", encoding="utf-8") as f:
        json.dump(wh_resources, f, ensure_ascii=False, indent=indent)
    with open(out_team, "w", encoding="utf-8") as f:
        json.dump(team_resources, f, ensure_ascii=False, indent=indent)
    with open(out_all, "w", encoding="utf-8") as f:
        json.dump(wh_resources + team_resources, f, ensure_ascii=False, indent=indent)

    print(f"导出完成：\n- {out_wh} ({len(wh_resources)} 条)\n- {out_team} ({len(team_resources)} 条)\n- {out_all} ({len(wh_resources) + len(team_resources)} 条)")


if __name__ == "__main__":
    main()
