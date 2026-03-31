"""
文档检索器

结合Embedding和Reranker实现高效的文档检索。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import RAGConfig
from .embedding import BGEEmbedding
from .reranker import BGEReranker

logger = logging.getLogger(__name__)


class Retriever:
    """
    文档检索器

    使用Embedding进行粗排，使用Reranker进行精排，实现高效的文档检索。
    """

    def __init__(
        self,
        embedding_model: BGEEmbedding,
        reranker_model: BGEReranker,
        config: RAGConfig = None
    ):
        """
        初始化检索器

        Args:
            embedding_model: Embedding模型实例
            reranker_model: Reranker模型实例
            config: RAG配置（如果为None，使用默认配置）
        """
        self.embedding_model = embedding_model
        self.reranker_model = reranker_model
        self.config = config or RAGConfig()

        # 从配置中获取参数
        self.top_k = self.config.coarse_top_k
        self.rerank_top_k = self.config.rerank_top_k

        # 文档索引
        self.documents: List[Dict] = []
        self.doc_embeddings = None

        logger.info(
            f"初始化检索器: coarse_top_k={self.top_k}, "
            f"rerank_top_k={self.rerank_top_k}, "
            f"use_rerank={self.config.use_rerank}"
        )

    def load_documents(self, data_dir: str) -> int:
        """
        从目录加载分块后的JSON文档

        Args:
            data_dir: JSON文件目录路径

        Returns:
            加载的文档数量
        """
        logger.info(f"加载文档: {data_dir}")
        data_path = Path(data_dir)

        if not data_path.exists():
            logger.error(f"目录不存在: {data_dir}")
            return 0

        doc_count = 0

        # 遍历所有JSON文件
        for json_file in data_path.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    doc_data = json.load(f)

                    # 检查是否是chunked格式
                    if "chunks" in doc_data:
                        # 分块格式
                        for chunk in doc_data["chunks"]:
                            self.documents.append({
                                "text": chunk["text"],
                                "doc_id": doc_data.get("doc_id"),
                                "chunk_id": chunk.get("chunk_id"),
                                "source_path": doc_data.get("source_path"),
                                "metadata": chunk.get("metadata", {})
                            })
                            doc_count += 1
                    else:
                        # 普通格式
                        self.documents.append({
                            "text": doc_data.get("text", ""),
                            "doc_id": doc_data.get("doc_id"),
                            "source_path": doc_data.get("source_path"),
                            "metadata": doc_data.get("metadata", {})
                        })
                        doc_count += 1

                logger.debug(f"加载文件: {json_file.name}, chunks: {len(doc_data.get('chunks', []))}")

            except Exception as e:
                logger.error(f"加载文件失败 {json_file}: {e}")

        logger.info(f"共加载 {doc_count} 个文档块")

        # 构建文档索引（计算embeddings）
        self._build_index()

        return doc_count

    def _build_index(self):
        """构建文档向量索引"""
        if not self.documents:
            logger.warning("没有文档需要索引")
            return

        logger.info("构建文档向量索引...")

        # 提取文档文本
        doc_texts = [doc["text"] for doc in self.documents]

        # 计算embeddings
        self.doc_embeddings = self.embedding_model.encode(
            doc_texts,
            batch_size=64,
            normalize=True
        )

        logger.info(f"索引构建完成，向量shape: {self.doc_embeddings.shape}")

    def retrieve(
        self,
        query: str,
        use_rerank: bool = True
    ) -> List[Dict]:
        """
        检索相关文档

        Args:
            query: 查询文本
            use_rerank: 是否使用重排

        Returns:
            检索结果列表，格式：
            [{
                "text": "文档文本",
                "score": 相关性得分,
                "doc_id": 文档ID,
                "chunk_id": 块ID,
                "metadata": 元数据
            }, ...]
        """
        if self.doc_embeddings is None:
            logger.error("文档索引未构建，请先调用 load_documents()")
            return []

        # ===== 粗排：使用Embedding检索 =====
        logger.debug(f"粗排检索: query='{query[:50]}...'")

        # 计算查询向量
        query_embedding = self.embedding_model.encode(query, normalize=True)

        # 如果是一维，转为二维
        if query_embedding.dim() == 1:
            query_embedding = query_embedding.unsqueeze(0)

        # 计算相似度（矩阵乘法）
        similarity_scores = query_embedding @ self.doc_embeddings.T
        similarity_scores = similarity_scores[0].cpu().numpy()

        # 获取top_k索引
        top_k_indices = np.argsort(similarity_scores)[::-1][:self.top_k]

        # 提取粗排结果
        coarse_results = []
        for idx in top_k_indices:
            if similarity_scores[idx] > 0:  # 只保留相关的
                coarse_results.append({
                    "index": idx,
                    "score": float(similarity_scores[idx]),
                    "text": self.documents[idx]["text"],
                    "doc_id": self.documents[idx].get("doc_id"),
                    "chunk_id": self.documents[idx].get("chunk_id"),
                    "metadata": self.documents[idx].get("metadata", {})
                })

        logger.debug(f"粗排完成，候选文档数: {len(coarse_results)}")

        # 如果不需要重排，直接返回粗排结果
        if not use_rerank:
            return coarse_results[:self.rerank_top_k]

        # ===== 精排：使用Reranker =====
        logger.debug(f"精排检索: {len(coarse_results)}个候选文档")

        # 提取候选文档文本
        candidate_docs = [result["text"] for result in coarse_results]

        # 使用Reranker重新排序
        rerank_results = self.reranker_model.rerank(
            query=query,
            documents=candidate_docs,
            top_k=self.rerank_top_k
        )

        # 构建最终结果
        final_results = []
        for rank, (original_idx, rerank_score, _) in enumerate(rerank_results):
            original_result = coarse_results[original_idx]
            final_results.append({
                "text": original_result["text"],
                "score": float(rerank_score),
                "coarse_score": original_result["score"],
                "rank": rank + 1,
                "doc_id": original_result["doc_id"],
                "chunk_id": original_result["chunk_id"],
                "metadata": original_result["metadata"]
            })

        logger.debug(f"精排完成，返回top {len(final_results)}结果")

        return final_results

    def add_documents(self, documents: List[Dict]):
        """
        添加新文档

        Args:
            documents: 文档列表
        """
        logger.info(f"添加 {len(documents)} 个新文档")
        self.documents.extend(documents)

        # 重建索引
        self._build_index()

    def clear(self):
        """清空所有文档"""
        self.documents.clear()
        self.doc_embeddings = None
        logger.info("已清空所有文档")
