"""
BGE Embedding模型

使用BGE系列模型进行文本向量化，支持粗排检索。
"""

import logging
import os
from pathlib import Path
from typing import List, Union

import torch
from transformers import AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)


class BGEEmbedding:
    """
    BGE Embedding模型类

    使用BGE模型将文本转换为向量表示，用于语义检索。
    """

    def __init__(
        self,
        model_path: str = "/workspace/traffic-emergency-agent/models/bge-large-zh-v1.5",
        device: str = "cuda:0",  # 使用GPU
        max_length: int = 512
    ):
        """
        初始化BGE Embedding模型

        Args:
            model_path: 模型路径
            device: 运行设备（cuda/cpu）
            max_length: 最大文本长度
        """
        self.model_path = model_path
        self.device = device
        self.max_length = max_length

        # 设置使用GPU 7
        import os
        os.environ["CUDA_VISIBLE_DEVICES"] = "7"
        actual_device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(f"初始化BGE Embedding模型: {model_path}")
        logger.info(f"设备: {actual_device} (GPU 7)")

        # 加载tokenizer和模型
        logger.info("加载tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        logger.info("加载模型...")
        self.model = AutoModel.from_pretrained(model_path)
        self.model.to(actual_device)
        self.model.eval()

        self.actual_device = actual_device
        logger.info("BGE Embedding模型初始化完成")

    def encode(
        self,
        sentences: Union[str, List[str]],
        batch_size: int = 32,
        normalize: bool = True
    ) -> torch.Tensor:
        """
        将文本编码为向量

        Args:
            sentences: 单个文本或文本列表
            batch_size: 批处理大小
            normalize: 是否归一化向量

        Returns:
            文本向量，shape为 (num_sentences, hidden_size)
        """
        # 处理单个文本的情况
        single_sentence = False
        if isinstance(sentences, str):
            sentences = [sentences]
            single_sentence = True

        all_embeddings = []

        # 分批处理
        with torch.no_grad():
            for i in range(0, len(sentences), batch_size):
                batch_sentences = sentences[i:i + batch_size]

                # Tokenize
                encoded_input = self.tokenizer(
                    batch_sentences,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors='pt'
                )
                encoded_input = {k: v.to(self.actual_device) for k, v in encoded_input.items()}

                # 模型推理
                model_output = self.model(**encoded_input)

                # 取[CLS] token的向量作为句子表示
                # 对应用户的代码: model_output[0][:, 0]
                embeddings = model_output[0][:, 0]

                all_embeddings.append(embeddings)

        # 合并所有批次的向量
        all_embeddings = torch.cat(all_embeddings, dim=0)

        # 归一化（用于余弦相似度计算）
        if normalize:
            all_embeddings = torch.nn.functional.normalize(all_embeddings, p=2, dim=1)

        # 如果是单个文本，返回一维向量
        if single_sentence:
            all_embeddings = all_embeddings[0]

        return all_embeddings

    def compute_similarity(
        self,
        queries: Union[str, List[str]],
        documents: Union[str, List[str]]
    ) -> torch.Tensor:
        """
        计算查询和文档之间的相似度

        Args:
            queries: 查询文本或列表
            documents: 文档文本或列表

        Returns:
            相似度矩阵，shape为 (num_queries, num_documents)
        """
        query_embeddings = self.encode(queries)
        doc_embeddings = self.encode(documents)

        # 确保是二维矩阵
        if query_embeddings.dim() == 1:
            query_embeddings = query_embeddings.unsqueeze(0)
        if doc_embeddings.dim() == 1:
            doc_embeddings = doc_embeddings.unsqueeze(0)

        # 计算相似度（矩阵乘法）
        # 对应用户的代码: embeddings_1 @ embeddings_2.T
        similarity = query_embeddings @ doc_embeddings.T

        return similarity

    def save_pretrained(self, save_path: str):
        """
        保存模型

        Args:
            save_path: 保存路径
        """
        self.tokenizer.save_pretrained(save_path)
        self.model.save_pretrained(save_path)
        logger.info(f"模型已保存到: {save_path}")
