#!/usr/bin/env python3
"""
交通应急Agent - 命令行界面

使用方法:
    # 交互模式
    python main.py interactive

    # 单次查询
    python main.py query "高速公路发生多车追尾事故，应该如何处置？"

    # 从文件读取查询
    python main.py query --file input.txt
"""

import logging
import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.agent import Agent
from src.providers import OpenAIProvider
from src.providers.defaults import DEFAULT_TEXT_API_KEY, DEFAULT_TEXT_BASE_URL, DEFAULT_TEXT_MODEL
from src.tools import QueryRegulations, QueryHistoricalCases, RiskAssessment, MediaCaption
from src.rag import (
    QueryRAG,
    RAGConfig,
    BALANCED_RAG_CONFIG,
    FAST_RAG_CONFIG,
    PRECISE_RAG_CONFIG,
    COARSE_ONLY_RAG_CONFIG,
)

# 加载环境变量
load_dotenv()

# 创建CLI应用
app = typer.Typer(
    name="traffic-agent",
    help="交通应急指挥助手 - 基于Agentic LLM的应急响应辅助系统"
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)


def create_agent(rag_config: RAGConfig = None) -> Agent:
    """
    创建Agent实例

    Args:
        rag_config: RAG配置（如果为None，使用默认配置）

    Returns:
        Agent实例
    """
    # 从环境变量获取配置，未显式配置时回退到项目默认文本模型设置
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or DEFAULT_TEXT_API_KEY
    if not api_key:
        typer.echo("错误: 未找到可用的文本模型 API Key", err=True)
        raise typer.Exit(1)

    base_url = os.getenv("OPENAI_BASE_URL") or DEFAULT_TEXT_BASE_URL
    model = os.getenv("OPENAI_MODEL", DEFAULT_TEXT_MODEL)

    # 使用默认配置（如果未提供）
    if rag_config is None:
        rag_config = BALANCED_RAG_CONFIG

    # 创建Provider（自动检测服务提供商）
    provider = OpenAIProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider="auto"
    )

    # 创建工具
    tools = [
        QueryRegulations(data_path="data/regulations"),
        QueryHistoricalCases(data_path="data/historical_cases"),
        RiskAssessment(),
        # RAG工具（使用配置）
        QueryRAG(data_dir="data/regulations/chunked_json", config=rag_config),
        MediaCaption(timeout=60)
    ]

    # 打印配置信息
    typer.echo(f"RAG配置: coarse_top_k={rag_config.coarse_top_k}, "
               f"rerank_top_k={rag_config.rerank_top_k}, "
               f"final_top_k={rag_config.final_top_k}")

    # 创建Agent
    agent = Agent(
        provider=provider,
        tools=tools,
        save_conversations=True,
        conversation_path="data/conversations"
    )

    return agent


@app.command()
def interactive(
    rag_mode: str = typer.Option("balanced", "--rag-mode", "-r",
                                  help="RAG模式: fast/balanced/precise/coarse-only")
):
    """
    交互模式

    启动交互式对话界面，支持多轮对话。
    """
    typer.echo("=" * 60)
    typer.echo("  交通应急指挥助手 - 交互模式")
    typer.echo("=" * 60)
    typer.echo("输入 'quit' 或 'exit' 退出")
    typer.echo("输入 'reset' 清空对话历史")
    typer.echo("")

    # 根据rag_mode选择配置
    rag_config_map = {
        "fast": FAST_RAG_CONFIG,
        "balanced": BALANCED_RAG_CONFIG,
        "precise": PRECISE_RAG_CONFIG,
        "coarse-only": COARSE_ONLY_RAG_CONFIG
    }
    rag_config = rag_config_map.get(rag_mode, BALANCED_RAG_CONFIG)

    # 创建Agent
    try:
        agent = create_agent(rag_config=rag_config)
    except Exception as e:
        logger.error(f"创建Agent失败: {e}")
        return

    while True:
        try:
            # 读取用户输入
            user_input = typer.prompt("\n你", prompt_suffix=": ").strip()

            if not user_input:
                continue

            # 退出命令
            if user_input.lower() in ["quit", "exit", "q"]:
                typer.echo("再见！")
                break

            # 重置命令
            if user_input.lower() == "reset":
                agent.reset()
                typer.echo("对话历史已清空")
                continue

            # 调用Agent
            typer.echo(f"\n助手: ", nl=False)
            response = agent.chat(user_input)
            typer.echo(response)

        except KeyboardInterrupt:
            typer.echo("\n\n再见！")
            break
        except Exception as e:
            logger.error(f"处理失败: {e}")
            typer.echo(f"抱歉，处理请求时出错: {e}")


@app.command()
def query(
    question: str = typer.Argument(..., help="要询问的问题"),
    file: str = typer.Option(None, "--file", "-f", help="从文件读取问题"),
    rag_mode: str = typer.Option("balanced", "--rag-mode", "-r",
                                  help="RAG模式: fast/balanced/precise/coarse-only")
):
    """
    单次查询模式

    提交一个问题并获取答案，然后退出。
    """
    # 如果指定了文件，从文件读取
    if file:
        try:
            with open(file, "r", encoding="utf-8") as f:
                question = f.read().strip()
        except Exception as e:
            typer.echo(f"读取文件失败: {e}", err=True)
            raise typer.Exit(1)

    typer.echo(f"问题: {question}")
    typer.echo("")

    # 根据rag_mode选择配置
    from src.rag.config import FAST_RAG_CONFIG, PRECISE_RAG_CONFIG, COARSE_ONLY_RAG_CONFIG
    rag_config_map = {
        "fast": FAST_RAG_CONFIG,
        "balanced": BALANCED_RAG_CONFIG,
        "precise": PRECISE_RAG_CONFIG,
        "coarse-only": COARSE_ONLY_RAG_CONFIG
    }
    rag_config = rag_config_map.get(rag_mode, BALANCED_RAG_CONFIG)

    # 创建Agent
    try:
        agent = create_agent(rag_config=rag_config)
    except Exception as e:
        logger.error(f"创建Agent失败: {e}")
        return

    try:
        # 调用Agent
        response = agent.chat(question)
        typer.echo(f"回答:\n{response}")

    except Exception as e:
        logger.error(f"查询失败: {e}")
        typer.echo(f"查询失败: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def version():
    """显示版本信息"""
    typer.echo("交通应急Agent v0.1.0")
    typer.echo("基于Agentic LLM的应急响应辅助系统")


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="启用详细日志")
):
    """
    交通应急Agent - 命令行工具
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


if __name__ == "__main__":
    app()
