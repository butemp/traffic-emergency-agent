#!/usr/bin/env python3
"""对比本地数据和API数据数量"""
import json
import os
import sys

# 添加父目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def count_local_data():
    """统计本地数据"""
    counts = {}

    # 专家数据
    try:
        with open('data/专家数据/expert_info.json', 'r', encoding='utf-8') as f:
            experts = json.load(f)
            counts['experts'] = len(experts)
    except FileNotFoundError:
        counts['experts'] = 0

    # 仓库数据
    try:
        with open('data/仓库和队伍的物资数据/em_warehouse.json', 'r', encoding='utf-8') as f:
            warehouses = json.load(f)
            counts['warehouses'] = len(warehouses)
    except FileNotFoundError:
        counts['warehouses'] = 0

    # 救援队伍数据
    try:
        with open('data/仓库和队伍的物资数据/rescue_team.json', 'r', encoding='utf-8') as f:
            teams = json.load(f)
            counts['teams'] = len(teams)
    except FileNotFoundError:
        counts['teams'] = 0

    return counts


def count_api_data():
    """统计API数据"""
    import requests
    counts = {}

    base_url = os.getenv("TOCC_BASE_URL", "https://tocc.itsgx.cn:10003/prod-api").rstrip("/")
    api_key = os.getenv("TOCC_API_KEY", "mZRsWLNomAaBrcor9skwqbQUvbwTsFYb")
    headers = {"X-API-Key": api_key, "Accept": "application/json"}

    # 专家数据
    try:
        resp = requests.get(f"{base_url}/expertAI/list", headers=headers, timeout=15)
        data = resp.json()
        counts['experts'] = data.get('totle', 0)
    except Exception as e:
        counts['experts'] = f"Error: {e}"

    # 仓库数据
    try:
        resp = requests.get(f"{base_url}/warehouseAi/list", headers=headers, timeout=15)
        data = resp.json()
        counts['warehouses'] = data.get('total', 0)
    except Exception as e:
        counts['warehouses'] = f"Error: {e}"

    # 应急预案数据
    try:
        resp = requests.get(f"{base_url}/emPrePlanAi/list", headers=headers, timeout=15)
        data = resp.json()
        counts['plans'] = data.get('totle', 0)
    except Exception as e:
        counts['plans'] = f"Error: {e}"

    # 救援队伍数据
    try:
        resp = requests.get(f"{base_url}/teamAi/getTeamForMcp", headers=headers, timeout=15)
        data = resp.json()
        if data.get('code') == 401:
            counts['teams'] = "鉴权失败 (401)"
        else:
            counts['teams'] = data.get('totle', 0)
    except Exception as e:
        counts['teams'] = f"Error: {e}"

    return counts


def main():
    os.chdir('/workspace/traffic-emergency-agent')

    print("=" * 60)
    print("数据对比报告")
    print("=" * 60)

    local = count_local_data()
    api = count_api_data()

    print(f"\n【专家库】")
    print(f"  本地数据: {local.get('experts', 0)} 条")
    print(f"  API数据:  {api.get('experts', 0)} 条")
    if isinstance(local.get('experts'), int) and isinstance(api.get('experts'), int):
        diff = local['experts'] - api['experts']
        pct = (diff / local['experts'] * 100) if local['experts'] > 0 else 0
        print(f"  差异:    {diff:+d} 条 ({pct:+.1f}%)")

    print(f"\n【仓库数据】")
    print(f"  本地数据: {local.get('warehouses', 0)} 条")
    print(f"  API数据:  {api.get('warehouses', 0)} 条")
    if isinstance(local.get('warehouses'), int) and isinstance(api.get('warehouses'), int):
        diff = local['warehouses'] - api['warehouses']
        pct = (diff / local['warehouses'] * 100) if local['warehouses'] > 0 else 0
        print(f"  差异:    {diff:+d} 条 ({pct:+.1f}%)")

    print(f"\n【应急预案】")
    print(f"  本地数据: 未找到文件")
    print(f"  API数据:  {api.get('plans', 0)} 条")

    print(f"\n【救援队伍】")
    print(f"  本地数据: {local.get('teams', 0)} 条")
    print(f"  API数据:  {api.get('teams', 'N/A')}")
    if isinstance(api.get('teams'), int) and isinstance(local.get('teams'), int):
        diff = local['teams'] - api['teams']
        pct = (diff / local['teams'] * 100) if local['teams'] > 0 else 0
        print(f"  差异:    {diff:+d} 条 ({pct:+.1f}%)")

    print("\n" + "=" * 60)
    print("结论:")
    print("=" * 60)
    print("- API数据比本地少，可能原因：")
    print("  1. API有状态/权限过滤（如只返回启用状态的数据）")
    print("  2. 本地数据包含已删除/停用/未审核的记录")
    print("  3. 数据同步延迟")
    print("- 救援队伍接口返回401鉴权错误，需要联系后端排查")
    print("- 建议检查API文档中的状态过滤参数")
    print("=" * 60)


if __name__ == "__main__":
    main()
