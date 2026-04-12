"""
构建 resource_dispatch 使用的标准化仓库表和救援队伍表。

输入文件：
- em_warehouse.json
- rescue_team.json
- em_material.json
- em_material_classified.jsonl
- em_warehouse_material.json
- rescue_team_material.json

输出文件：
- warehouse_dispatch_resources.json
- warehouse_dispatch_resources.jsonl
- rescue_team_dispatch_resources.json
- rescue_team_dispatch_resources.jsonl
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent

WAREHOUSE_SOURCE = BASE_DIR / "em_warehouse.json"
TEAM_SOURCE = BASE_DIR / "rescue_team.json"
MATERIAL_SOURCE = BASE_DIR / "em_material.json"
MATERIAL_CLASSIFIED_SOURCE = BASE_DIR / "em_material_classified.jsonl"
WAREHOUSE_MATERIAL_SOURCE = BASE_DIR / "em_warehouse_material.json"
TEAM_MATERIAL_SOURCE = BASE_DIR / "rescue_team_material.json"

WAREHOUSE_OUTPUT_JSON = BASE_DIR / "warehouse_dispatch_resources.json"
WAREHOUSE_OUTPUT_JSONL = BASE_DIR / "warehouse_dispatch_resources.jsonl"
TEAM_OUTPUT_JSON = BASE_DIR / "rescue_team_dispatch_resources.json"
TEAM_OUTPUT_JSONL = BASE_DIR / "rescue_team_dispatch_resources.jsonl"

DEFAULT_CATEGORY = "OTHER"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def save_json(path: Path, records: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)


def save_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_phone(value: Any) -> Optional[str]:
    text = clean_text(value)
    return text


def clean_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def clean_quantity(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number.is_integer():
        return int(number)
    return round(number, 3)


def normalize_category(value: Any) -> str:
    text = clean_text(value)
    return text.upper() if text else DEFAULT_CATEGORY


def build_material_index() -> Dict[str, Dict[str, Any]]:
    raw_materials = load_json(MATERIAL_SOURCE)
    classified_records = load_jsonl(MATERIAL_CLASSIFIED_SOURCE)

    materials_by_id: Dict[str, Dict[str, Any]] = {}
    for record in raw_materials:
        material_id = clean_text(record.get("id"))
        if material_id:
            materials_by_id[material_id] = dict(record)

    for record in classified_records:
        material_id = clean_text(record.get("id"))
        if material_id:
            merged = materials_by_id.get(material_id, {})
            merged.update(record)
            materials_by_id[material_id] = merged

    return materials_by_id


def should_keep_material(record: Dict[str, Any]) -> bool:
    if not record:
        return False
    if record.get("del_flag") == 1:
        return False
    if clean_quantity(record.get("quantity")) <= 0:
        return False
    if not clean_text(record.get("material_name")):
        return False
    return True


def build_owner_material_map(
    materials_by_id: Dict[str, Dict[str, Any]],
    owner_key: str,
    relation_records: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    owner_materials: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[Tuple[str, str]] = set()

    for material in materials_by_id.values():
        if not should_keep_material(material):
            continue
        owner_id = clean_text(material.get(owner_key))
        material_id = clean_text(material.get("id"))
        if not owner_id or not material_id:
            continue
        owner_materials[owner_id].append(material)
        seen_pairs.add((owner_id, material_id))

    for relation in relation_records:
        owner_id = clean_text(relation.get(owner_key))
        material_id = clean_text(relation.get("material_id"))
        if not owner_id or not material_id:
            continue
        if (owner_id, material_id) in seen_pairs:
            continue

        material = materials_by_id.get(material_id)
        if not should_keep_material(material):
            continue

        owner_materials[owner_id].append(material)
        seen_pairs.add((owner_id, material_id))

    return owner_materials


def material_sort_key(item: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(item.get("category", "")),
        str(item.get("name", "")),
        str(item.get("unit", "")),
    )


def aggregate_materials(materials: Iterable[Dict[str, Any]]) -> Tuple[List[str], Dict[str, List[Dict[str, Any]]], int]:
    grouped: Dict[str, Dict[Tuple[str, str, str], Dict[str, Any]]] = defaultdict(dict)
    total_material_rows = 0

    for material in materials:
        total_material_rows += 1
        category = normalize_category(material.get("category"))
        name = clean_text(material.get("material_name")) or "未命名物资"
        unit = clean_text(material.get("unit")) or ""
        spec_model = clean_text(material.get("spec_model")) or ""
        key = (name, unit, spec_model)

        current = grouped[category].get(key)
        quantity = clean_quantity(material.get("quantity"))
        if current is None:
            grouped[category][key] = {
                "name": name,
                "quantity": quantity,
                "unit": unit,
                "spec_model": spec_model or None,
                "material_type": clean_text(material.get("material_type")),
                "material_ids": [clean_text(material.get("id"))] if clean_text(material.get("id")) else [],
            }
        else:
            current["quantity"] += quantity
            material_id = clean_text(material.get("id"))
            if material_id:
                current["material_ids"].append(material_id)

    materials_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for category, items in grouped.items():
        ordered_items = sorted(items.values(), key=material_sort_key)
        for item in ordered_items:
            if isinstance(item["quantity"], float) and item["quantity"].is_integer():
                item["quantity"] = int(item["quantity"])
        materials_by_category[category] = ordered_items

    categories = sorted(materials_by_category.keys())
    return categories, materials_by_category, total_material_rows


def build_warehouse_records(
    warehouses: List[Dict[str, Any]],
    owner_materials: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for warehouse in warehouses:
        warehouse_id = clean_text(warehouse.get("id"))
        if not warehouse_id:
            continue

        materials = owner_materials.get(warehouse_id, [])
        categories, materials_by_category, total_material_rows = aggregate_materials(materials)

        record = {
            "warehouse_id": warehouse_id,
            "warehouse_name": clean_text(warehouse.get("warehouse_name")),
            "warehouse_type": clean_text(warehouse.get("warehouse_type")),
            "belong_org_code": clean_text(warehouse.get("belong_org_code")),
            "belong_org_name": clean_text(warehouse.get("belong_org_name")),
            "address": clean_text(warehouse.get("address")),
            "latitude": clean_float(warehouse.get("latitude")),
            "longitude": clean_float(warehouse.get("longitude")),
            "road_code": clean_text(warehouse.get("road_code")),
            "stake": clean_text(warehouse.get("stake")),
            "principal": clean_text(warehouse.get("principal")),
            "contact_phone": clean_phone(warehouse.get("contact_phone")),
            "verification_state": warehouse.get("verification_state"),
            "last_verified_at": clean_text(warehouse.get("last_verified_at")),
            "next_due_at": clean_text(warehouse.get("next_due_at")),
            "remark": clean_text(warehouse.get("remark")),
            "categories": categories,
            "material_item_count": total_material_rows,
            "material_kind_count": sum(len(items) for items in materials_by_category.values()),
            "materials_by_category": materials_by_category,
        }
        records.append(record)

    records.sort(key=lambda item: (item.get("warehouse_name") or "", item.get("warehouse_id") or ""))
    return records


def build_team_records(
    teams: List[Dict[str, Any]],
    owner_materials: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for team in teams:
        team_id = clean_text(team.get("id"))
        if not team_id:
            continue

        materials = owner_materials.get(team_id, [])
        categories, materials_by_category, total_material_rows = aggregate_materials(materials)

        record = {
            "team_id": team_id,
            "team_name": clean_text(team.get("team_name")),
            "team_code": clean_text(team.get("team_code")),
            "team_type": clean_text(team.get("team_type")),
            "team_size": clean_int(team.get("team_size")),
            "status": team.get("status"),
            "leader_name": clean_text(team.get("leader_name")),
            "leader_phone": clean_phone(team.get("leader_phone")),
            "jurisdiction_unit": clean_text(team.get("jurisdiction_unit")),
            "jurisdiction_leader": clean_text(team.get("jurisdiction_leader")),
            "jurisdiction_phone": clean_phone(team.get("jurisdiction_phone")),
            "specialties": clean_text(team.get("specialties")),
            "address": clean_text(team.get("address")),
            "latitude": clean_float(team.get("latitude")),
            "longitude": clean_float(team.get("longitude")),
            "road_code": clean_text(team.get("road_code")),
            "stake": clean_text(team.get("stake")),
            "verification_state": team.get("verification_state"),
            "last_verified_at": clean_text(team.get("last_verified_at")),
            "next_due_at": clean_text(team.get("next_due_at")),
            "remark": clean_text(team.get("remark")),
            "categories": categories,
            "material_item_count": total_material_rows,
            "material_kind_count": sum(len(items) for items in materials_by_category.values()),
            "materials_by_category": materials_by_category,
        }
        records.append(record)

    records.sort(key=lambda item: (item.get("team_name") or "", item.get("team_id") or ""))
    return records


def print_summary(warehouses: List[Dict[str, Any]], teams: List[Dict[str, Any]]) -> None:
    warehouse_with_materials = sum(1 for item in warehouses if item["material_item_count"] > 0)
    team_with_materials = sum(1 for item in teams if item["material_item_count"] > 0)

    print(f"仓库标准表: {len(warehouses)} 条，其中有物资的仓库 {warehouse_with_materials} 条")
    print(f"队伍标准表: {len(teams)} 条，其中有物资的队伍 {team_with_materials} 条")
    print(f"输出文件: {WAREHOUSE_OUTPUT_JSON.name}, {WAREHOUSE_OUTPUT_JSONL.name}")
    print(f"输出文件: {TEAM_OUTPUT_JSON.name}, {TEAM_OUTPUT_JSONL.name}")


def main() -> None:
    warehouses = load_json(WAREHOUSE_SOURCE)
    teams = load_json(TEAM_SOURCE)
    materials_by_id = build_material_index()
    warehouse_links = load_json(WAREHOUSE_MATERIAL_SOURCE)
    team_links = load_json(TEAM_MATERIAL_SOURCE)

    warehouse_materials = build_owner_material_map(
        materials_by_id=materials_by_id,
        owner_key="warehouse_id",
        relation_records=warehouse_links,
    )
    team_materials = build_owner_material_map(
        materials_by_id=materials_by_id,
        owner_key="team_id",
        relation_records=team_links,
    )

    warehouse_records = build_warehouse_records(warehouses, warehouse_materials)
    team_records = build_team_records(teams, team_materials)

    save_json(WAREHOUSE_OUTPUT_JSON, warehouse_records)
    save_jsonl(WAREHOUSE_OUTPUT_JSONL, warehouse_records)
    save_json(TEAM_OUTPUT_JSON, team_records)
    save_jsonl(TEAM_OUTPUT_JSONL, team_records)

    print_summary(warehouse_records, team_records)


if __name__ == "__main__":
    main()
