"""
风险评估工具

对应急方案进行风险评估，通过调用LLM进行智能分析。
"""

import json
import logging
import os
from typing import Dict, Any, Optional
from .base import BaseTool
from ..providers.defaults import (
    DEFAULT_TEXT_API_KEY,
    DEFAULT_TEXT_BASE_URL,
    DEFAULT_TEXT_MAX_TOKENS,
    DEFAULT_TEXT_MODEL,
)

logger = logging.getLogger(__name__)


class RiskAssessment(BaseTool):
    """
    风险评估工具

    基于预设规则和LLM对应急方案进行多维度风险评估。
    """

    # 评估规则Prompt模板
    ASSESSMENT_RULES = """你是专业的交通应急风险评估专家。请基于以下规则对应急方案进行全面评估：

## 评估维度

### 1. 信息完整性 (权重: 20%)
评估方案是否包含以下关键信息：
- 事故类型、规模、位置
- 人员伤亡情况
- 天气、道路等环境因素
- 可用资源情况

### 2. 响应及时性 (权重: 20%)
评估响应时间安排是否合理：
- 接警响应时间
- 现场到达时间
- 救援展开时间
- 交通管制时间

### 3. 措施有效性 (权重: 25%)
评估处置措施是否得当：
- 人员救援措施
- 交通疏导方案
- 现场管控措施
- 应急资源调配
- 二次事故防范

### 4. 资源充足性 (权重: 15%)
评估资源配置是否充足：
- 人员力量（消防、医疗、交警等）
- 装备设备
- 物资储备
- 支援力量

### 5. 风险可控性 (权重: 20%)
评估潜在风险是否可控：
- 人员伤亡风险
- 交通拥堵风险
- 二次事故风险
- 舆情风险

## 评分标准
- 90-100分：优秀，方案完善、风险可控
- 75-89分：良好，方案基本完善，需微调
- 60-74分：及格，方案存在不足，需改进
- 60分以下：不及格，方案存在重大问题

## 输出格式要求
请严格按照以下JSON格式输出评估结果（不要添加其他文字）：

```json
{
  "overall_score": 数字(0-100),
  "risk_level": "低风险|较低风险|中等风险|较高风险|高风险",
  "dimensions": [
    {
      "name": "信息完整性",
      "score": 数字(0-100),
      "strengths": ["优点1", "优点2"],
      "weaknesses": ["不足1", "不足2"],
      "missing_info": ["缺失信息1", "缺失信息2"]
    }
  ],
  "excellent_points": ["整体优点1", "整体优点2"],
  "potential_risks": ["风险1", "风险2"],
  "suggestions": ["改进建议1", "改进建议2"]
}
```

请基于以上规则，对以下场景和方案进行评估。"""

    def __init__(self, data_path: str = None, provider=None, timeout: int = 60):
        """
        初始化工具

        Args:
            data_path: 不需要数据路径，保留接口兼容性
            provider: LLM Provider（可选，默认自动创建）
            timeout: API调用超时时间（秒）
        """
        super().__init__(data_path)
        self.timeout = timeout

        # 如果没有提供provider，创建默认的
        if provider is None:
            # 延迟导入避免循环依赖
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

            # 导入OpenAIProvider
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or DEFAULT_TEXT_API_KEY
            eval_model = os.getenv("EVAL_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_TEXT_MODEL
            eval_base_url = os.getenv("EVAL_BASE_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_TEXT_BASE_URL

            # 简单的provider包装，避免循环导入
            class SimpleProvider:
                def __init__(self, api_key, model, base_url, timeout):
                    from openai import OpenAI
                    self.api_key = api_key
                    self.client = OpenAI(
                        api_key=api_key,
                        base_url=base_url,
                        timeout=timeout
                    )
                    self.model = model
                    self.base_url = base_url
                    self.timeout = timeout

                def chat(self, messages, tools=None):
                    from openai import OpenAI
                    import httpx
                    # 创建带超时的客户端
                    client = OpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url,
                        timeout=httpx.Timeout(self.timeout, connect=10.0)
                    )
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=DEFAULT_TEXT_MAX_TOKENS,
                    )
                    return response.choices[0].message.content or ""

            provider = SimpleProvider(api_key, eval_model, eval_base_url, timeout)

        self.provider = provider
        logger.info(f"初始化风险评估工具（LLM驱动，超时={timeout}秒）")

    @property
    def name(self) -> str:
        """工具名称"""
        return "risk_assessment"

    @property
    def description(self) -> str:
        """工具描述"""
        return """对应急方案进行智能风险评估。

分析方案的信息完整性、响应及时性、措施有效性、资源充足性、风险可控性等维度，返回量化评分、优点分析、风险识别和改进建议。"""

    @property
    def parameters(self) -> Dict[str, Any]:
        """参数定义"""
        return {
            "type": "object",
            "properties": {
                "scenario": {
                    "type": "string",
                    "description": "灾害/事故场景描述，包括时间、地点、类型、规模等"
                },
                "plan": {
                    "type": "string",
                    "description": "应急方案描述，包括采取的措施、资源部署、时间安排等"
                },
                "focus_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要重点关注的评估领域（可选），如['信息完整性', '响应及时性']等",
                    "enum": ["信息完整性", "响应及时性", "措施有效性", "资源充足性", "风险可控性"]
                }
            },
            "required": ["scenario", "plan"]
        }

    def execute(self, scenario: str, plan: str, focus_areas: list = None) -> str:
        """
        执行风险评估

        Args:
            scenario: 灾害/事故场景描述
            plan: 应急方案描述
            focus_areas: 需要重点关注的评估领域（可选）

        Returns:
            评估结果（JSON格式字符串）
        """
        import time
        start_time = time.time()

        logger.info(f"执行风险评估: scenario长度={len(scenario)}, plan长度={len(plan)}")

        # 构建评估Prompt
        assessment_prompt = self._build_prompt(scenario, plan, focus_areas)
        logger.info(f"评估Prompt长度: {len(assessment_prompt)} 字符")

        try:
            # 调用LLM进行评估
            logger.info("正在调用LLM进行风险评估...")
            response = self._call_assessment_llm(assessment_prompt)

            elapsed = time.time() - start_time
            logger.info(f"LLM调用完成，耗时: {elapsed:.2f}秒")

            # 解析LLM返回的JSON结果
            result = self._parse_llm_response(response)

            logger.info(f"评估完成: 综合得分={result['overall_score']}, 风险等级={result['risk_level']}")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"风险评估失败 (耗时{elapsed:.2f}秒): {e}")
            import traceback
            traceback.print_exc()

            # 返回错误结果
            error_result = {
                "status": "error",
                "message": f"评估失败: {str(e)}",
                "overall_score": 0,
                "risk_level": "未知"
            }
            return json.dumps(error_result, ensure_ascii=False, indent=2)

    def _build_prompt(self, scenario: str, plan: str, focus_areas: Optional[list]) -> str:
        """
        构建评估Prompt

        Args:
            scenario: 场景描述
            plan: 方案描述
            focus_areas: 重点关注的领域

        Returns:
            完整的评估Prompt
        """
        prompt_parts = [self.ASSESSMENT_RULES]

        # 添加重点关注领域（如果有）
        if focus_areas:
            prompt_parts.append(f"\n## 重点关注领域\n本次评估需重点关注：{', '.join(focus_areas)}\n")

        # 添加场景和方案
        prompt_parts.append("## 评估对象")
        prompt_parts.append(f"\n### 事故场景\n{scenario}\n")
        prompt_parts.append(f"\n### 应急方案\n{plan}\n")
        prompt_parts.append("\n请开始评估，严格按照JSON格式输出：")

        return "\n".join(prompt_parts)

    def _call_assessment_llm(self, prompt: str) -> str:
        """
        调用LLM进行评估

        Args:
            prompt: 评估Prompt

        Returns:
            LLM的原始响应
        """
        # 构建消息
        messages = [
            {"role": "user", "content": prompt}
        ]

        # 调用LLM（不使用工具调用）
        response = self.provider.chat(messages, tools=None)

        logger.debug(f"LLM响应（前500字符）: {response[:500]}...")
        return response

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """
        解析LLM的响应，提取JSON结果

        Args:
            response: LLM的原始响应

        Returns:
            解析后的评估结果字典
        """
        # 尝试直接解析JSON
        try:
            result = json.loads(response)
            # 验证必要字段
            if "overall_score" not in result or "risk_level" not in result:
                raise ValueError("缺少必要字段")
            result["status"] = "success"
            return result
        except json.JSONDecodeError:
            pass

        # 尝试提取JSON块（如果响应包含markdown代码块）
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                if "overall_score" in result and "risk_level" in result:
                    result["status"] = "success"
                    return result
            except json.JSONDecodeError:
                pass

        # 如果都失败，返回一个基本的结果
        logger.warning("无法解析LLM响应为JSON，返回默认结果")
        return {
            "status": "partial",
            "overall_score": 60,
            "risk_level": "中等风险",
            "dimensions": [],
            "excellent_points": ["LLM响应格式异常，无法完整解析"],
            "potential_risks": ["评估可能不完整"],
            "suggestions": ["请检查LLM响应格式"],
            "raw_response": response[:1000]  # 保存前1000字符用于调试
        }
