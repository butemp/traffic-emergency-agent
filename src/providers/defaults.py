"""项目内统一的模型默认配置。"""

import os


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

DEFAULT_TEXT_API_KEY = "sk-TBi6zDfq2SkTvyZQCusU7g"
DEFAULT_TEXT_MODEL = "deepseek-ai/DeepSeek-V3.2"
DEFAULT_TEXT_BASE_URL = "https://ai.gxtri.cn/llm/v1"
DEFAULT_TEXT_MAX_TOKENS = _int_env("OPENAI_MAX_TOKENS", 65536)
DEFAULT_CAPTION_MODEL = "qwen-vl-plus"
