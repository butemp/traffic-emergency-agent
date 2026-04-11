"""
将仓库和队伍物资数据从 XLS 格式转换为 JSON / JSONL 格式。

输出文件（与本脚本同目录）：
  em_material.json / em_material.jsonl
  em_warehouse.json / em_warehouse.jsonl
  em_warehouse_material.json / em_warehouse_material.jsonl
  rescue_team.json / rescue_team.jsonl
  rescue_team_material.json / rescue_team_material.jsonl
"""

import json
import os
from datetime import datetime, timedelta

import xlrd

# ── 日期字段列表（Excel 序列号 → ISO 日期字符串）────────────────────────────
DATE_FIELDS = {
    "create_time", "update_time", "expiry_date",
    "last_verified_at", "next_due_at",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_BASE_DATE = datetime(1899, 12, 30)   # Excel 日期起点（Windows 模式）


def excel_serial_to_date(serial: float) -> str:
    """将 Excel 日期序列号转为 YYYY-MM-DD 字符串。"""
    try:
        date = EXCEL_BASE_DATE + timedelta(days=serial)
        return date.strftime("%Y-%m-%d")
    except Exception:
        return str(serial)


def cell_value(sheet, row: int, col: int, header: str):
    """读取单元格，处理类型转换：日期→字符串，数字整数化，错误→None。"""
    ctype = sheet.cell_type(row, col)
    value = sheet.cell_value(row, col)

    # xlrd cell type: 0=empty, 1=text, 2=number, 3=date, 4=bool, 5=error
    if ctype == xlrd.XL_CELL_EMPTY or value == "":
        return None
    if ctype == xlrd.XL_CELL_ERROR:
        return None
    if ctype == xlrd.XL_CELL_DATE:
        return excel_serial_to_date(value)
    if ctype == xlrd.XL_CELL_NUMBER:
        # 如果是日期字段（存为数字类型但实为日期序列号）
        if header in DATE_FIELDS and value > 0:
            return excel_serial_to_date(value)
        # 整数数字去掉多余小数点
        if value == int(value):
            return int(value)
        return value
    if ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    # text
    return str(value).strip() if isinstance(value, str) else value


def xls_to_records(xls_path: str) -> list[dict]:
    """将 xls 文件的第一个 sheet 转为字典列表。"""
    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheets()[0]

    if sh.nrows == 0:
        return []

    headers = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    records = []

    for r in range(1, sh.nrows):
        row_dict = {}
        for c, header in enumerate(headers):
            row_dict[header] = cell_value(sh, r, c, header)
        records.append(row_dict)

    return records


def save_json(records: list[dict], out_path: str):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  ✅ JSON  → {os.path.relpath(out_path, BASE_DIR)}  ({len(records)} 条)")


def save_jsonl(records: list[dict], out_path: str):
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  ✅ JSONL → {os.path.relpath(out_path, BASE_DIR)}  ({len(records)} 条)")


def convert(xls_filename: str):
    xls_path = os.path.join(BASE_DIR, xls_filename)
    stem = os.path.splitext(xls_filename)[0]

    print(f"\n📂 处理: {xls_filename}")
    records = xls_to_records(xls_path)

    save_json(records, os.path.join(BASE_DIR, stem + ".json"))
    save_jsonl(records, os.path.join(BASE_DIR, stem + ".jsonl"))


if __name__ == "__main__":
    for fname in [
        "em_material.xls",
        "em_warehouse.xls",
        "em_warehouse_material.xls",
        "rescue_team.xls",
        "rescue_team_material.xls",
    ]:
        convert(fname)

    print("\n🎉 全部转换完成！")
