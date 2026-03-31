"""
BGE Reranker模型

使用BGE Reranker模型进行精排，提升检索准确率。
"""

import logging
import os
from typing import List, Tuple, Union

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)


class BGEReranker:
    """
    BGE Reranker模型类

    对粗排结果进行精细排序，返回更准确的相关性得分。
    """

    def __init__(
        self,
        model_path: str = "/workspace/traffic-emergency-agent/models/bge-reranker-v2-m3",
        device: str = "cuda:0",  # 使用GPU
        max_length: int = 512
    ):
        """
        初始化BGE Reranker模型

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

        logger.info(f"初始化BGE Reranker模型: {model_path}")
        logger.info(f"设备: {actual_device} (GPU 7)")

        # 加载tokenizer和模型
        logger.info("加载tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        logger.info("加载模型...")
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self.model.to(actual_device)
        self.model.eval()

        self.actual_device = actual_device
        logger.info("BGE Reranker模型初始化完成")

    def compute_score(
        self,
        pairs: List[Tuple[str, str]],
        batch_size: int = 32
    ) -> List[float]:
        """
        计算query-document对的相关性得分

        Args:
            pairs: query-document对列表，格式：[(query1, doc1), (query1, doc2), ...]
            batch_size: 批处理大小

        Returns:
            得分列表，值越大表示越相关
        """
        all_scores = []

        # 分批处理
        with torch.no_grad():
            for i in range(0, len(pairs), batch_size):
                batch_pairs = pairs[i:i + batch_size]

                # Tokenize
                # 对应用户的代码: tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=512)
                inputs = self.tokenizer(
                    batch_pairs,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors='pt'
                )
                inputs = {k: v.to(self.actual_device) for k, v in inputs.items()}

                # 模型推理
                outputs = self.model(**inputs, return_dict=True)

                # 取logits并展平
                # 对应用户的代码: .logits.view(-1)
                scores = outputs.logits.view(-1).float()

                all_scores.append(scores)

        # 合并所有批次的得分
        all_scores = torch.cat(all_scores, dim=0)

        return all_scores.cpu().tolist()

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = None
    ) -> List[Tuple[int, float, str]]:
        """
        对文档进行重排序

        Args:
            query: 查询文本
            documents: 候选文档列表
            top_k: 返回前k个结果

        Returns:
            排序后的结果列表，格式：[(doc_index, score, doc_text), ...]
        """
        # 构造query-doc对
        pairs = [[query, doc] for doc in documents]

        # 计算得分
        scores = self.compute_score(pairs)

        # 按得分排序（从高到低）
        indexed_scores = [(i, score, doc) for i, (score, doc) in enumerate(zip(scores, documents))]
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        # 返回top_k
        if top_k is not None:
            indexed_scores = indexed_scores[:top_k]

        return indexed_scores

    def save_pretrained(self, save_path: str):
        """
        保存模型

        Args:
            save_path: 保存路径
        """
        self.tokenizer.save_pretrained(save_path)
        self.model.save_pretrained(save_path)
        logger.info(f"模型已保存到: {save_path}")
