"""
RAG配置类

集中管理RAG相关的所有参数。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RAGConfig:
    """
    RAG配置类

    集中管理RAG相关的所有参数。
    """

    # ===== 模型路径配置 =====
    embedding_model_path: str = "/workspace/traffic-emergency-agent/models/bge-large-zh-v1.5"
    reranker_model_path: str = "/workspace/traffic-emergency-agent/models/bge-reranker-v2-m3"

    # ===== 检索参数配置 =====
    # 粗排：从所有文档中检索出的候选文档数量
    coarse_top_k: int = 20

    # 精排：对粗排结果重新排序后返回的文档数量
    rerank_top_k: int = 5

    # 最终返回给LLM的文档数量
    # 注意：这个数量应该 <= rerank_top_k
    final_top_k: int = 5

    # ===== 文档处理配置 =====
    # 是否使用重排（如果设为False，则直接使用粗排结果）
    use_rerank: bool = True

    # Embedding模型的最大文本长度
    embedding_max_length: int = 512

    # Reranker模型的最大文本长度
    reranker_max_length: int = 512

    # Embedding批处理大小
    embedding_batch_size: int = 64

    # Reranker批处理大小
    reranker_batch_size: int = 32

    # ===== 结果格式化配置 =====
    # 返回给LLM的文档最大字符数（超过则截断）
    max_doc_chars: int = 500

    # 是否显示文档元数据（doc_id、source等）
    show_metadata: bool = False

    # ===== 相似度阈值配置 =====
    # 最低相似度阈值（低于此值的文档将被过滤）
    min_similarity_score: float = 0.0

    def __post_init__(self):
        """初始化后验证参数"""
        if self.final_top_k > self.rerank_top_k:
            raise ValueError(
                f"final_top_k ({self.final_top_k}) 不能大于 "
                f"rerank_top_k ({self.rerank_top_k})"
            )

        if self.coarse_top_k < self.rerank_top_k:
            raise ValueError(
                f"coarse_top_k ({self.coarse_top_k}) 不能小于 "
                f"rerank_top_k ({self.rerank_top_k})"
            )

    @classmethod
    def from_dict(cls, config_dict: dict) -> "RAGConfig":
        """
        从字典创建配置

        Args:
            config_dict: 配置字典

        Returns:
            RAGConfig实例
        """
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        """
        转换为字典

        Returns:
            配置字典
        """
        from dataclasses import asdict
        return asdict(self)


# ===== 默认配置实例 =====
DEFAULT_RAG_CONFIG = RAGConfig()


# ===== 预设配置方案 =====

# 快速模式：速度快，但精度较低
FAST_RAG_CONFIG = RAGConfig(
    coarse_top_k=10,
    rerank_top_k=3,
    final_top_k=3,
    use_rerank=True,
    show_metadata=True
)

# 精确模式：精度高，但速度较慢
PRECISE_RAG_CONFIG = RAGConfig(
    coarse_top_k=50,
    rerank_top_k=10,
    final_top_k=10,
    use_rerank=True,
    show_metadata=True
)

# 平衡模式：速度与精度平衡（默认）
BALANCED_RAG_CONFIG = RAGConfig(
    coarse_top_k=20,
    rerank_top_k=5,
    final_top_k=5,
    use_rerank=True,
    show_metadata=True
)

# 仅粗排模式：最快，不使用重排
COARSE_ONLY_RAG_CONFIG = RAGConfig(
    coarse_top_k=10,
    rerank_top_k=10,  # 不使用重排时，这个参数无效
    final_top_k=5,
    use_rerank=False,
    show_metadata=True
)


# ===== 配置说明 =====
"""
参数调优建议：

1. coarse_top_k（粗排候选数量）
   - 范围：10-50
   - 影响：越大越可能找到相关文档，但检索越慢
   - 建议：
     * 文档库小（<1000条）：10-20
     * 文档库中等（1000-10000条）：20-30
     * 文档库大（>10000条）：30-50

2. rerank_top_k（精排候选数量）
   - 范围：3-10
   - 影响：越大返回结果越多，但送给LLM的上下文越长
   - 建议：5-7（通常前5个结果已经足够相关）

3. final_top_k（最终返回数量）
   - 范围：1-10
   - 影响：实际送给LLM的文档数量
   - 建议：
     * 简单问题：1-3
     * 复杂问题：3-5
     * 综合性问题：5-10

4. use_rerank（是否使用重排）
   - True：精度高，速度慢（推荐）
   - False：精度低，速度快

5. max_doc_chars（单文档最大字符数）
   - 范围：200-1000
   - 影响：控制送给LLM的单个文档长度
   - 建议：500（平衡信息量和上下文长度）
"""
