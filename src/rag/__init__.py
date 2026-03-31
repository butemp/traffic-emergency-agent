"""
RAG模块

实现检索增强生成（RAG）功能，包括文档检索、排序和问答。
"""

from .config import (
    RAGConfig,
    DEFAULT_RAG_CONFIG,
    FAST_RAG_CONFIG,
    PRECISE_RAG_CONFIG,
    BALANCED_RAG_CONFIG,
    COARSE_ONLY_RAG_CONFIG
)
from .embedding import BGEEmbedding
from .reranker import BGEReranker
from .retriever import Retriever
from .tool import QueryRAG

__all__ = [
    "BGEEmbedding",
    "BGEReranker",
    "Retriever",
    "QueryRAG",
    "RAGConfig",
    "DEFAULT_RAG_CONFIG",
    "FAST_RAG_CONFIG",
    "PRECISE_RAG_CONFIG",
    "BALANCED_RAG_CONFIG",
    "COARSE_ONLY_RAG_CONFIG",
]
