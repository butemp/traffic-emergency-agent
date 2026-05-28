"""
从导出的 resources_all.json 汇总物资“品类”数量：
- distinct_material_name: 按名称去重的种类数
- distinct_name_spec_unit: 按 (名称+规格+单位) 聚合后的种类数

用法：
  python -m scripts.summarize_materials_from_json \
      --input data/仓库和队伍的物资数据/resources_all.json \
      --output data/仓库和队伍的物资数据/materials_summary.json
"""

import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    names = set()
    combos = set()
    name_list_for_count = []
    for res in data:
        inv = (res.get('inventory') or {}).get('items') or []
        for it in inv:
            name = (it.get('material_name') or '').strip()
            spec = (it.get('spec_model') or '').strip()
            unit = (it.get('unit') or '').strip()
            if name:
                names.add(name)
                name_list_for_count.append(name)
            combos.add((name, spec, unit))

    # 输出名称列表（按拼音/字典序排序，避免随机顺序），并附上按出现次数的Top20
    material_names = sorted(names)
    from collections import Counter
    top20 = Counter(name_list_for_count).most_common(20)

    summary = {
        'distinct_material_name': len(names),
        'distinct_name_spec_unit': len(combos),
        'material_names': material_names,
        'top20_material_name_by_entries': [
            {'material_name': n, 'count': c} for n, c in top20
        ],
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
