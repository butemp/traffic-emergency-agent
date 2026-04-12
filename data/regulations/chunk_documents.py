import json
import os
import argparse
from pathlib import Path
import pdfplumber
import re

def clean_doc_name(filename: str) -> str:
    """保留原有的文件名清洗逻辑"""
    name = Path(filename).stem
    name = re.sub(r'^\d{10,}_', '', name)
    while re.match(r'^\d+_', name):
        name = re.sub(r'^\d+_', '', name)
    name = re.sub(r'^附件\s*\d*\s*', '', name)
    return name.strip()

def extract_full_text(filepath: str) -> str:
    """提取 PDF 全文并合并为单行或完整段落"""
    all_text = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # 移除页码等干扰信息（沿用原逻辑）
                text = re.sub(r'—\s*\d+\s*—', '', text)
                all_text.append(text)
    
    # 将所有页面的文字连接起来
    # 如果你想完全合成“一整段”，可以将所有换行符替换为空格或删除
    full_content = "".join(all_text) 
    # 清理掉过多的空白字符，合并成一个连续的长字符串
    full_content = re.sub(r'\s+', ' ', full_content).strip()
    return full_content

def process_and_save(input_path: str, output_path: str):
    input_p = Path(input_path)
    results = []

    # 获取待处理文件列表
    files = [input_p] if input_p.is_file() else list(input_p.glob("*.pdf"))

    for f_path in files:
        print(f"正在提取: {f_path.name}")
        try:
            content = extract_full_text(str(f_path))
            doc_name = clean_doc_name(f_path.name)
            
            # 构造简单的结构
            data = {
                "doc_name": doc_name,
                "file_name": f_path.name,
                "content": content,
                "char_count": len(content)
            }
            results.append(data)
        except Exception as e:
            print(f"文件 {f_path.name} 提取失败: {e}")

    # 输出为 JSONL
    with open(output_path, 'w', encoding='utf-8') as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print(f"\n提取完成！已保存至: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF全文完整提取工具")
    parser.add_argument("--input", required=True, help="输入PDF文件或目录")
    parser.add_argument("--output", required=True, help="输出JSONL文件路径")
    args = parser.parse_args()

    process_and_save(args.input, args.output)