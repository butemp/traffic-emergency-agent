"""
应急物资分类脚本

功能：读取 em_material.jsonl，使用 LLM 批量为每条物资打上类别标签，输出新的 jsonl 文件。
支持多线程并发、断点续跑、失败重试。

使用方式：
python run_llm.py \
    --input em_material.jsonl \
    --output em_material_classified.jsonl \
    --api-key sk-TBi6zDfq2SkTvyZQCusU7g \
    --base-url https://ai.gxtri.cn/llm/v1 \
    --model deepseek-ai/DeepSeek-V3.2 \
    --workers 4 \
    --batch-size 4

环境依赖：
    pip install openai
"""

import json
import time
import argparse
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from openai import OpenAI

DEFAULT_TEXT_API_KEY = "sk-TBi6zDfq2SkTvyZQCusU7g"
DEFAULT_TEXT_BASE_URL = "https://ai.gxtri.cn/llm/v1"
DEFAULT_TEXT_MODEL = "deepseek-ai/DeepSeek-V3.2"

# ========== 分类体系 ==========

VALID_CATEGORIES = {
    "SIGN", "WARNING", "PPE", "FIRE", "TOOL",
    "VEHICLE", "MATERIAL", "RESCUE", "COMMS",
    "DEICE", "OTHER"
}

SYSTEM_PROMPT = """你是交通应急物资分类专家。将物资名称分类到指定类别。

## 类别

| 编码 | 名称 | 示例 |
|------|------|------|
| SIGN | 交通标志/标牌 | 限速牌、施工牌、导向牌、改道牌 |
| WARNING | 警示/防护设备 | 锥桶、爆闪灯、水马、防撞桶、警戒带 |
| PPE | 个人防护用品 | 安全帽、反光背心、防护手套、雨衣 |
| FIRE | 消防器材 | 灭火器、消防服、消防水带、呼吸器 |
| TOOL | 工具/工程机械 | 扳手、千斤顶、发电机、切割机、铁锹 |
| VEHICLE | 车辆 | 清障车、皮卡、巡查车、拖车 |
| MATERIAL | 抢险材料 | 沥青冷补料、水泥、沙袋、钢护栏、碎石 |
| RESCUE | 救生装备 | 救生衣、救生圈、担架、急救包 |
| COMMS | 通讯/照明 | 对讲机、喊话器、探照灯、头灯 |
| DEICE | 防冰除雪 | 融雪剂、工业盐、防滑链、撒盐机 |
| OTHER | 其他 | 不属于以上任何类别 |

## 规则
- 按主要用途判断，每条只归一个类别
- "反光背心"→PPE，"防撞桶"→WARNING，"消防手套"→FIRE，"发电机"→TOOL
- 名称明显不是物资（如仓库名、站点名）→OTHER

## 输出格式
每行一个类别编码，顺序与输入一一对应，不要输出任何其他内容。

示例输入：
1. 锥桶
2. 安全帽
3. 灭火器

示例输出：
WARNING
PPE
FIRE"""

# ========== 核心逻辑 ==========

# 用于线程安全写文件和打印
write_lock = Lock()
print_lock = Lock()


def safe_print(msg: str):
    with print_lock:
        print(msg, flush=True)


def load_jsonl(path: str) -> list[dict]:
    """加载 jsonl 文件"""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                safe_print(f"  跳过第 {line_num} 行（JSON解析失败）：{e}")
    return records


def load_progress(output_path: str) -> int:
    """检查已有输出文件，返回已处理的记录数（用于断点续跑）"""
    if not os.path.exists(output_path):
        return 0
    count = 0
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def classify_batch(
    client: OpenAI,
    model: str,
    names: list[str],
    max_retries: int = 3
) -> list[str]:
    """
    将一批物资名称发送给 LLM 分类。
    返回与输入等长的类别编码列表。
    """
    # 构造用户 prompt：带编号的物资列表
    numbered_list = "\n".join(f"{i+1}. {name}" for i, name in enumerate(names))
    user_prompt = f"请对以下 {len(names)} 条物资进行分类，每行只输出一个类别编码：\n\n{numbered_list}"

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ]
            )
            content = response.choices[0].message.content.strip()
            
            print(f"  LLM 输出（第 {attempt+1} 次尝试）：\n{content}\n")

            # 解析：每行一个类别编码
            lines = [l.strip() for l in content.split("\n") if l.strip()]

            # 有些模型可能输出 "1. WARNING" 格式，清理一下
            categories = []
            for line in lines:
                # 去掉可能的编号前缀："1. WARNING" -> "WARNING"
                parts = line.split(".", 1)
                cat = parts[-1].strip().upper()
                # 去掉可能的其他前缀字符
                cat = cat.strip("- ·")
                categories.append(cat)

            # 校验数量
            if len(categories) != len(names):
                safe_print(
                    f"  批次返回数量不匹配：期望 {len(names)}，"
                    f"实际 {len(categories)}，重试 ({attempt+1}/{max_retries})"
                )
                time.sleep(2)
                continue

            # 校验类别编码合法性，非法的标记为 OTHER
            for i, cat in enumerate(categories):
                if cat not in VALID_CATEGORIES:
                    safe_print(f"  非法类别 '{cat}' -> OTHER（物资：{names[i]}）")
                    categories[i] = "OTHER"

            return categories

        except Exception as e:
            safe_print(f"  API 调用失败 ({attempt+1}/{max_retries})：{e}")
            time.sleep(3 * (attempt + 1))  # 递增等待

    # 全部重试失败，返回 OTHER
    safe_print(f"  批次全部重试失败，{len(names)} 条标记为 OTHER")
    return ["OTHER"] * len(names)


def process_batch_group(
    client: OpenAI,
    model: str,
    batch_index: int,
    total_batches: int,
    records: list[dict],
    output_path: str
):
    """
    处理一个批次：分类 + 写入结果。
    供线程池调用。
    """
    names = [r.get("material_name", "") or "" for r in records]
    safe_print(f"[{batch_index+1}/{total_batches}] 分类 {len(names)} 条物资...")

    categories = classify_batch(client, model, names)

    # 给每条记录加上 category 字段
    output_lines = []
    for record, category in zip(records, categories):
        record_copy = dict(record)
        record_copy["category"] = category
        output_lines.append(json.dumps(record_copy, ensure_ascii=False))

    # 线程安全地追加写入
    with write_lock:
        with open(output_path, "a", encoding="utf-8") as f:
            for line in output_lines:
                f.write(line + "\n")

    safe_print(f"[{batch_index+1}/{total_batches}] 完成 ✓")
    return len(records)


# ========== 主流程 ==========

def main():
    parser = argparse.ArgumentParser(description="应急物资 LLM 批量分类工具")
    parser.add_argument("--input", required=True, help="输入 jsonl 文件路径")
    parser.add_argument("--output", required=True, help="输出 jsonl 文件路径")
    parser.add_argument("--api-key", default=DEFAULT_TEXT_API_KEY, help="API Key")
    parser.add_argument("--base-url", default=DEFAULT_TEXT_BASE_URL, help="API Base URL")
    parser.add_argument("--model", default=DEFAULT_TEXT_MODEL, help=f"模型名称（默认 {DEFAULT_TEXT_MODEL}）")
    parser.add_argument("--batch-size", type=int, default=60, help="每批物资数量（默认 60）")
    parser.add_argument("--workers", type=int, default=4, help="并发线程数（默认 4）")
    parser.add_argument("--resume", action="store_true", help="断点续跑（跳过已处理的记录）")
    args = parser.parse_args()

    # 1. 加载数据
    print(f"加载数据：{args.input}")
    all_records = load_jsonl(args.input)
    print(f"共 {len(all_records)} 条记录")

    # 2. 过滤已删除记录（del_flag=1）
    active_records = [r for r in all_records if r.get("del_flag") != 1]
    deleted_records = [r for r in all_records if r.get("del_flag") == 1]
    print(f"有效记录：{len(active_records)} 条，已删除：{len(deleted_records)} 条")

    # 3. 断点续跑：跳过已处理的记录
    skip_count = 0
    if args.resume:
        skip_count = load_progress(args.output)
        if skip_count > 0:
            print(f"断点续跑：跳过前 {skip_count} 条已处理记录")
            active_records = active_records[skip_count:]
            if not active_records:
                print("所有记录已处理完毕")
                return
    else:
        # 非续跑模式，清空输出文件
        Path(args.output).write_text("")

    # 4. 对已删除的记录直接标记 category=null，写入输出（仅非续跑模式）
    if not args.resume and deleted_records:
        print(f"已删除记录直接标记 category=null...")
        with open(args.output, "a", encoding="utf-8") as f:
            for r in deleted_records:
                r_copy = dict(r)
                r_copy["category"] = None
                f.write(json.dumps(r_copy, ensure_ascii=False) + "\n")

    # 5. 分批
    batches = []
    for i in range(0, len(active_records), args.batch_size):
        batches.append(active_records[i:i + args.batch_size])
    total_batches = len(batches)
    print(f"\n开始分类：{len(active_records)} 条有效记录，分 {total_batches} 批，{args.workers} 线程并发\n")

    # 6. 创建客户端
    client = OpenAI(api_key=args.api_key, base_url=args.base_url)

    # 7. 多线程处理
    processed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for i, batch in enumerate(batches):
            future = executor.submit(
                process_batch_group,
                client, args.model,
                i, total_batches,
                batch, args.output
            )
            futures[future] = i

        for future in as_completed(futures):
            try:
                count = future.result()
                processed += count
            except Exception as e:
                batch_idx = futures[future]
                safe_print(f"[{batch_idx+1}/{total_batches}] 异常：{e}")

    # 8. 统计
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"分类完成！")
    print(f"处理记录：{processed} 条")
    print(f"耗时：{elapsed:.1f} 秒（{processed/elapsed:.1f} 条/秒）")
    print(f"输出文件：{args.output}")

    # 9. 读取输出文件做分布统计
    print(f"\n分类分布统计：")
    category_counts = {}
    output_records = load_jsonl(args.output)
    for r in output_records:
        cat = r.get("category") or "null"
        category_counts[cat] = category_counts.get(cat, 0) + 1
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:12s}: {count:>5d} 条")


if __name__ == "__main__":
    main()
