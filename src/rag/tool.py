"""
RAG查询工具

基于检索增强生成（RAG）的文档查询工具。
"""

import json
import logging
from typing import Dict, Any

from ..tools.base import BaseTool
from .config import RAGConfig, BALANCED_RAG_CONFIG
from .embedding import BGEEmbedding
from .reranker import BGEReranker
from .retriever import Retriever

logger = logging.getLogger(__name__)


class QueryRAG(BaseTool):
    """
    RAG查询工具

    使用Embedding和Reranker进行文档检索，返回最相关的文档内容。
    """

    def __init__(
        self,
        data_dir: str = "data/regulations/chunked_json",
        config: RAGConfig = None
    ):
        """
        初始化RAG工具

        Args:
            data_dir: 数据目录路径
            config: RAG配置（如果为None，使用默认平衡配置）
        """
        # 使用默认配置（如果未提供）
        self.config = config or BALANCED_RAG_CONFIG

        # 调用父类初始化（data_path用于兼容BaseTool接口）
        super().__init__(data_dir)

        # 记录配置信息
        logger.info("初始化RAG工具...")
        logger.info(f"  数据目录: {data_dir}")
        logger.info(f"  配置: coarse_top_k={self.config.coarse_top_k}, "
                   f"rerank_top_k={self.config.rerank_top_k}, "
                   f"final_top_k={self.config.final_top_k}")

        # 初始化Embedding模型
        logger.info("加载Embedding模型...")
        self.embedding_model = BGEEmbedding(
            model_path=self.config.embedding_model_path,
            max_length=self.config.embedding_max_length
        )

        # 初始化Reranker模型
        logger.info("加载Reranker模型...")
        self.reranker_model = BGEReranker(
            model_path=self.config.reranker_model_path,
            max_length=self.config.reranker_max_length
        )

        # 初始化检索器
        self.retriever = Retriever(
            embedding_model=self.embedding_model,
            reranker_model=self.reranker_model,
            config=self.config
        )

        # 加载文档
        doc_count = self.retriever.load_documents(data_dir)
        logger.info(f"RAG工具初始化完成，共加载 {doc_count} 个文档块")

    @property
    def name(self) -> str:
        """工具名称"""
        return "query_rag"

    @property
    def description(self) -> str:
        """工具描述"""
        return """【首要推荐】查询交通应急相关的法规、预案、技术指南和标准文档。

这是最全面的文档查询工具，包含：
- 国家和地方法律法规
- 应急预案和处置流程
- 技术指南和操作规范
- 标准作业程序

使用场景：当用户询问"如何处置"、"有什么规定"、"标准流程"、"具体要求"等问题时，应优先调用此工具。

优势：基于语义检索，能理解查询意图，返回最相关的文档片段，比关键词匹配更准确。"""

    @property
    def parameters(self) -> Dict[str, Any]:
        """参数定义"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "查询问题，如'高速公路交通事故如何处置？'"
                },
                "top_k": {
                    "type": "integer",
                    "description": f"返回结果数量，默认{self.config.final_top_k}，最多{self.config.rerank_top_k}",
                    "default": self.config.final_top_k,
                    "minimum": 1,
                    "maximum": self.config.rerank_top_k
                }
            },
            "required": ["query"]
        }

    def execute(self, query: str, top_k: int = None) -> str:
        """
        执行RAG查询

        Args:
            query: 查询问题
            top_k: 返回结果数量（不能超过配置的rerank_top_k）

        Returns:
            查询结果（JSON格式字符串）
        """
        logger.info(f"执行RAG查询: query='{query[:100]}...', top_k={top_k}")

        # 使用配置中的默认值
        if top_k is None:
            top_k = self.config.final_top_k

        # 验证top_k不超过rerank_top_k
        if top_k > self.config.rerank_top_k:
            top_k = self.config.rerank_top_k
            logger.warning(f"top_k超过rerank_top_k，已调整为{top_k}")

        # 执行检索
        try:
            results = self.retriever.retrieve(query, use_rerank=self.config.use_rerank)

            if not results:
                logger.warning("未找到相关文档")
                return json.dumps({
                    "status": "not_found",
                    "message": "未找到相关文档，请尝试其他关键词",
                    "query": query,
                    "count": 0
                }, ensure_ascii=False, indent=2)

            # 限制返回数量
            results = results[:top_k]

            # 过滤低于相似度阈值的结果
            if self.config.min_similarity_score > 0:
                results = [
                    r for r in results
                    if r.get("score", 0) >= self.config.min_similarity_score
                ]

            # 构建返回结果
            formatted_results = []
            for i, result in enumerate(results):
                # 截断文档文本
                text = result["text"]
                if len(text) > self.config.max_doc_chars:
                    text = text[:self.config.max_doc_chars] + "..."

                formatted_result = {
                    "rank": i + 1,
                    "score": round(result["score"], 4),
                    "text": text
                }

                # 可选：添加元数据
                if self.config.show_metadata:
                    formatted_result.update({
                        "doc_id": result.get("doc_id", ""),
                        "chunk_id": result.get("chunk_id", ""),
                        "source": result.get("metadata", {}).get("source_path", "")
                    })

                formatted_results.append(formatted_result)

            response = {
                "status": "success",
                "query": query,
                "count": len(formatted_results),
                "results": formatted_results
            }

            logger.info(f"RAG查询成功: 找到{len(formatted_results)}条相关文档")

            return json.dumps(response, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"RAG查询失败: {e}")
            import traceback
            traceback.print_exc()

            return json.dumps({
                "status": "error",
                "message": f"查询失败: {str(e)}",
                "query": query,
                "count": 0
            }, ensure_ascii=False, indent=2)
