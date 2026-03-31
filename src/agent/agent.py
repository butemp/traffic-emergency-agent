"""
Agent核心类

实现Agent的主逻辑，包括消息处理、工具调用、对话管理等。
"""

import logging
import time
from typing import List, Optional

from .message import Message, MessageRole, ToolCall
from .state import ConversationState
from ..providers import OpenAIProvider
from ..tools import BaseTool

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Agent:
    """
    交通应急Agent

    核心功能：
    1. 维护对话状态和历史
    2. 调用LLM进行推理
    3. 处理工具调用
    4. 返回最终响应
    """

    # System Prompt：定义Agent的角色和行为
    SYSTEM_PROMPT = """你是一个交通应急指挥助手，专门协助处理交通事故应急响应相关的工作。

你的职责：
1. 根据用户描述的情况，查询相关的法规、规则和应急预案
2. 参考历史类似案例，提供处置建议
3. 根据用户需求对应急方案进行风险评估，给出改进意见

工作流程：
- 首先理解用户的问题和场景
- **优先调用 query_rag 工具**查询相关法规、预案和技术文档（这是最全面的知识库）
- 必要时补充调用 query_historical_cases 查询历史案例
- **获得工具结果后，必须先进行分析和推理，然后再给出处置建议**

工具使用说明：
- query_rag：查询法规、预案、指南（最全面，优先使用）
- query_historical_cases：查询历史案例（补充参考）
- geocode_address：将地址转换为坐标（用户提供地址时使用）
- check_traffic_status：查询交通拥堵状况
- get_weather_by_location：查询天气信息
- search_map_resources：**优先使用**。查询内部调度资源（如专属救援队、协议物资库、值班人员）。这些资源是可控的，应优先于公开POI使用。
- search_nearby_pois：**作为备选**。搜索公开的周边设施（如加油站、公共停车场）。仅在 search_map_resources 查无结果时使用。
- risk_assessment：仅在用户明确要求评估时才调用，不要自动调用

工具调用说明：
**重要：每次只能调用一个工具**
在调用工具之前，你必须先说明：
1. 为什么需要调用这个工具
2. 你希望通过这个工具获取什么信息
3. 这个工具如何帮助回答用户的问题

示例格式：
"我需要调用query_rag工具来检索关于[主题]的文档资料，以便找到相关的法规要求和处置流程。"

重要注意事项：
1. **每次只能调用一个工具**：不要在一次响应中调用多个工具，每次只调用一个，获得结果并分析后再决定是否需要下一个
2. **处理空结果**：如果工具返回空结果（如找不到POI、没有交通数据等），说明这个情况，然后继续基于已有信息回答
3. **禁止重复调用工具**：每个工具只能调用一次，绝对不要用不同的参数或关键词反复调用同一个工具
4. **及时总结**：在调用2-3个关键工具后，必须综合信息给出处置建议，而不是继续调用更多工具
5. 所有回答必须基于工具查询的结果，不要编造信息
6. 如果查询结果不足，明确告知用户需要更多信息
7. 对于紧急情况，优先考虑人员安全
8. **处理交通应急问题时，优先使用query_rag工具**
9. **资源调度优先权**：在查询救援力量（医院、消防、物资）时，必须**优先调用 search_map_resources**。只有当库内资源不足或距离过远时，才使用 search_nearby_pois 搜索社会公开资源。
10. **仅在用户明确要求"评估"、"分析风险"等时才调用risk_assessment工具**

## 回答格式要求

在调用工具并获得结果后，你的回答必须包含以下两个部分：

### 第一部分：工具调用结果分析
必须对每个工具的返回结果进行分析：
- 从query_rag结果中提取了哪些关键信息
- 历史案例提供了哪些参考
- 地理信息、交通状况、天气等数据说明了什么问题
- 这些信息之间有什么关联

格式示例：
---
**📊 工具调用结果分析**

1. **法规依据**：从query_rag结果中，我找到了《XXX预案》第X条，要求...
2. **案例参考**：历史案例显示，类似情况下的处置流程是...
3. **现场情况**：根据交通状况和天气信息，当前...
4. **综合判断**：结合以上信息，我认为...
---

### 第二部分：处置建议
基于上述分析，给出具体、可操作的处置建议。

格式示例：
---
**💡 处置建议**

1. **立即措施**：
   - ...
2. **后续行动**：
   - ...
3. **注意事项**：
   - ...
---

记住：**先分析，后建议**。不要跳过分析过程直接给出答案。"""

    def __init__(
        self,
        provider: OpenAIProvider,
        tools: List[BaseTool],
        max_iterations: int = 5,
        save_conversations: bool = True,
        conversation_path: str = "data/conversations"
    ):
        """
        初始化Agent

        Args:
            provider: LLM Provider（OpenAI）
            tools: 工具列表
            max_iterations: 最大工具调用迭代次数
            save_conversations: 是否保存对话历史
            conversation_path: 对话历史保存路径
        """
        self.provider = provider
        self.tools = {tool.name: tool for tool in tools}
        self.max_iterations = max_iterations

        # 初始化对话状态
        conv_path = conversation_path if save_conversations else None
        self.state = ConversationState(
            max_history=50,
            save_path=conv_path
        )

        # 添加system消息
        system_msg = Message(role=MessageRole.SYSTEM, content=self.SYSTEM_PROMPT)
        self.state.add_message(system_msg)

        logger.info(f"初始化Agent: 工具数量={len(tools)}, max_iterations={max_iterations}")

    def chat(self, user_message: str) -> str:
        """
        与Agent对话（主入口）

        Args:
            user_message: 用户消息

        Returns:
            Agent的响应内容
        """
        logger.info(f"用户输入: {user_message[:100]}...")

        # 添加用户消息到历史
        user_msg = Message(role=MessageRole.USER, content=user_message)
        self.state.add_message(user_msg)

        # 迭代处理：可能需要多次工具调用
        iteration = 0
        final_response = ""

        # 跟踪已调用的工具，防止重复调用
        called_tools = set()

        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"--- 迭代 {iteration} ---")

            # 获取对话历史
            messages = self.state.get_history()

            # 获取工具定义
            tool_definitions = [tool.to_openai_format() for tool in self.tools.values()]

            # 调用LLM
            try:
                start_time = time.time()
                response = self.provider.chat(messages, tools=tool_definitions)
                elapsed = time.time() - start_time
                logger.info(f"LLM响应耗时: {elapsed:.2f}秒")

            except Exception as e:
                logger.error(f"LLM调用失败: {e}")
                return f"抱歉，系统出现错误：{str(e)}"

            # 检查是否有工具调用
            if response.tool_calls:
                # 只执行第一个工具调用，实现逐步调用
                tool_call = response.tool_calls[0]

                # 检测是否是重复工具调用
                if tool_call.name in called_tools:
                    logger.warning(f"检测到重复工具调用: {tool_call.name}，已自动跳过")
                    # 添加跳过消息
                    skip_msg = Message(
                        role=MessageRole.ASSISTANT,
                        content=f"（工具 {tool_call.name} 已经调用过，跳过重复调用）"
                    )
                    self.state.add_message(skip_msg)
                    continue

                # 如果有多个工具调用，记录提示
                if len(response.tool_calls) > 1:
                    other_tools = [tc.name for tc in response.tool_calls[1:]]
                    logger.info(f"检测到多个工具调用，本次只执行第一个: {tool_call.name}，其他工具将在后续轮次中考虑: {other_tools}")

                # 添加助手消息（只包含第一个工具调用）
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=[tool_call]
                )
                self.state.add_message(assistant_msg)

                # 标记工具已调用
                called_tools.add(tool_call.name)
                logger.info(f"执行工具: {tool_call.name}（已调用工具列表: {called_tools}）")

                try:
                    # 执行工具
                    tool_result = self._execute_tool(tool_call)

                    # 添加工具结果到历史
                    tool_msg = Message(
                        role=MessageRole.TOOL,
                        content=tool_result,
                        tool_call_id=tool_call.id
                    )
                    self.state.add_message(tool_msg)

                except Exception as e:
                    logger.error(f"工具执行失败: {e}")
                    # 添加错误信息
                    error_msg = Message(
                        role=MessageRole.TOOL,
                        content=f"工具执行失败: {str(e)}",
                        tool_call_id=tool_call.id
                    )
                    self.state.add_message(error_msg)

                # 在工具调用完成后，插入一个系统消息，要求模型先分析工具结果
                logger.info("=== 工具调用完成，插入分析指令 ===")
                analysis_prompt = f"""【重要】你刚刚调用了以下工具并获得了结果：

{tool_call.name}

现在请按照以下步骤进行：

**第一步：分析工具结果（必须完成）**
请对刚才的工具调用结果进行简要分析：
- 每个工具返回了什么关键信息？
- 这些信息之间有什么关联？
- 基于这些结果，你发现了什么？

**第二步：决定下一步操作**
根据你的分析，选择以下之一：
- 如果信息已经足够，直接给出处置建议（按照"📊 工具调用结果分析"和"💡 处置建议"的格式）
- 如果还需要更多信息，说明需要调用什么工具并调用

注意：请确保你的回答包含第一步的分析内容。"""
                analysis_msg = Message(role=MessageRole.SYSTEM, content=analysis_prompt)
                self.state.add_message(analysis_msg)

                # 继续下一轮迭代，让LLM基于工具结果生成最终回答
                continue

            else:
                # 没有工具调用，这是最终回答
                final_response = response.content

                # 添加助手消息到历史
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=final_response
                )
                self.state.add_message(assistant_msg)

                logger.info(f"最终响应: {final_response[:100]}...")
                break

        # 保存对话历史
        self.state.save()

        return final_response

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """
        执行工具调用

        Args:
            tool_call: 工具调用信息

        Returns:
            工具执行结果

        Raises:
            KeyError: 工具不存在
            Exception: 工具执行失败
        """
        tool_name = tool_call.name
        arguments = tool_call.arguments

        logger.info(f"执行工具: {tool_name}, 参数: {arguments}")

        # 获取工具
        if tool_name not in self.tools:
            raise KeyError(f"工具不存在: {tool_name}")

        tool = self.tools[tool_name]

        # 执行工具
        try:
            result = tool.execute(**arguments)
            logger.info(f"工具执行成功: 结果长度={len(result)}")
            return result

        except Exception as e:
            logger.error(f"工具执行失败: {e}")
            raise

    def reset(self) -> None:
        """
        重置对话状态

        清空对话历史，但保留system message。
        """
        self.state.clear()
        # 重新添加system message
        system_msg = Message(role=MessageRole.SYSTEM, content=self.SYSTEM_PROMPT)
        self.state.add_message(system_msg)
        logger.info("对话状态已重置")

    def set_system_prompt(self, prompt: str) -> None:
        """
        设置System Prompt

        Args:
            prompt: 新的system prompt
        """
        self.__class__.SYSTEM_PROMPT = prompt
        logger.info("System Prompt已更新")
