# RAG配置说明

## 配置位置

所有RAG相关的关键参数都集中在 `src/rag/config.py` 中的 `RAGConfig` 类。

```python
from src.rag import RAGConfig, BALANCED_RAG_CONFIG

# 使用预设配置
config = BALANCED_RAG_CONFIG

# 或者自定义配置
config = RAGConfig(
    coarse_top_k=20,      # 粗排候选数
    rerank_top_k=5,       # 精排返回数
    final_top_k=5         # 最终送入LLM的文档数
)
```

---

## 关键参数说明

### 1. coarse_top_k（粗排候选数量）
- **位置**: `RAGConfig.coarse_top_k`
- **默认值**: 20
- **含义**: Embedding检索后返回的候选文档数量
- **影响范围**: 10-50

**调优建议**:
- 文档库小（<1000条）: 10-20
- 文档库中等（1000-10000条）: 20-30
- 文档库大（>10000条）: 30-50

```python
# 例子：从小文档库检索
config = RAGConfig(coarse_top_k=10)
```

### 2. rerank_top_k（精排返回数量）
- **位置**: `RAGConfig.rerank_top_k`
- **默认值**: 5
- **含义**: Reranker精排后返回的文档数量
- **影响范围**: 3-10

**调优建议**:
- 简单问题: 3-5
- 复杂问题: 5-7
- 综合性问题: 7-10

```python
# 例子：需要更多候选结果
config = RAGConfig(rerank_top_k=10)
```

### 3. final_top_k（最终返回数量）
- **位置**: `RAGConfig.final_top_k`
- **默认值**: 5
- **含义**: 实际送给LLM的文档数量
- **限制**: 必须 ≤ rerank_top_k

**调优建议**:
- 快速响应: 1-3
- 标准查询: 3-5
- 深度分析: 5-10

```python
# 例子：只返回最相关的3个文档
config = RAGConfig(
    rerank_top_k=10,
    final_top_k=3  # 从精排的10个中选最相关的前3个
)
```

### 4. use_rerank（是否使用重排）
- **位置**: `RAGConfig.use_rerank`
- **默认值**: True
- **含义**: 是否使用Reranker进行精排

**选择建议**:
- **True**: 精度高，速度慢（推荐）
- **False**: 精度低，速度快

```python
# 例子：仅使用粗排（最快）
config = RAGConfig(use_rerank=False)
```

### 5. max_doc_chars（单文档最大字符数）
- **位置**: `RAGConfig.max_doc_chars`
- **默认值**: 500
- **含义**: 返回给LLM的单个文档最大字符数

**调优建议**:
- 快速响应: 200-300
- 标准查询: 500
- 深度分析: 800-1000

```python
# 例子：返回更长的文档片段
config = RAGConfig(max_doc_chars=800)
```

---

## 使用方式

### 方式1: 使用预设配置

```python
from src.rag import QueryRAG, FAST_RAG_CONFIG, PRECISE_RAG_CONFIG

# 快速模式（最快）
rag_tool = QueryRAG(config=FAST_RAG_CONFIG)

# 精确模式（最准确）
rag_tool = QueryRAG(config=PRECISE_RAG_CONFIG)
```

### 方式2: 自定义配置

```python
from src.rag import QueryRAG, RAGConfig

# 自定义配置
config = RAGConfig(
    coarse_top_k=30,      # 粗排检索30个候选
    rerank_top_k=8,       # 精排返回8个
    final_top_k=5,        # 最终返回5个
    max_doc_chars=600     # 单文档最多600字符
)

rag_tool = QueryRAG(config=config)
```

### 方式3: 命令行模式

```bash
# 快速模式
python main.py interactive --rag-mode fast

# 平衡模式（默认）
python main.py interactive --rag-mode balanced

# 精确模式
python main.py interactive --rag-mode precise

# 仅粗排模式（最快，不使用重排）
python main.py interactive --rag-mode coarse-only
```

---

## 预设配置对比

| 模式 | coarse_top_k | rerank_top_k | final_top_k | 特点 |
|-----|-------------|-------------|-------------|-----|
| **fast** | 10 | 3 | 3 | 最快响应 |
| **balanced** | 20 | 5 | 5 | 平衡速度和精度 |
| **precise** | 50 | 10 | 10 | 最高精度 |
| **coarse-only** | 10 | - | 5 | 仅粗排，不使用重排 |

---

## 配置验证

`RAGConfig` 会自动验证参数合法性：

```python
# ❌ 错误：final_top_k 不能大于 rerank_top_k
config = RAGConfig(
    rerank_top_k=5,
    final_top_k=10  # ValueError: final_top_k 不能大于 rerank_top_k
)

# ❌ 错误：coarse_top_k 不能小于 rerank_top_k
config = RAGConfig(
    coarse_top_k=10,
    rerank_top_k=20  # ValueError: coarse_top_k 不能小于 rerank_top_k
)

# ✅ 正确
config = RAGConfig(
    coarse_top_k=20,
    rerank_top_k=10,
    final_top_k=5
)
```
