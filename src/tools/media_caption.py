#!/usr/bin/env python3
"""
多模态媒体Caption工具

- 输入图片/视频文件路径，调用多模态大模型生成caption
- 视频通过均匀抽帧（N帧）转成多图输入，让模型综合理解后输出一段caption
- 输出为JSON字符串，方便Agent后续使用

依赖（视频抽帧二选一）：
1) 推荐：opencv-python
   pip install opencv-python
2) 或者：系统安装 ffmpeg（本工具默认走opencv；若无opencv，会提示安装）
"""

import base64
import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class CaptionConfig:
    # 视频抽帧数量
    num_frames: int = 6
    # 图片最长边（用于可选压缩；本示例不强制压缩，仅保留字段）
    max_image_side: int = 1024
    # 生成温度
    temperature: float = 0.2
    # 最大输出长度（不同服务可能不支持该字段，保留给你后续扩展）
    max_tokens: int = 512
    # 默认caption风格
    style: str = "brief"  # brief / detailed / structured


class MediaCaption(BaseTool):
    """
    多模态媒体Caption工具
    """

    CAPTION_SYSTEM = """你是交通应急领域的多模态内容理解助手。
你的任务：根据用户提供的图片/视频帧内容，生成清晰、准确、可用于检索与指挥记录的中文caption。
要求：
- 不编造看不见的内容；不确定就说“不确定/疑似/可能”
- 优先描述：场景（地点/道路类型）、事件（事故/拥堵/施工/抛洒物等）、参与者（车辆/人员）、关键风险（火情/泄漏/二次事故风险）、显著标志（路牌/车道/警示设施）
- 输出必须严格为JSON（不加额外文字）
"""

    def __init__(
        self,
        data_path: str = None,
        provider=None,
        timeout: int = 60,
        config: Optional[CaptionConfig] = None,
        model: Optional[str] = None,
    ):
        super().__init__(data_path)
        self.timeout = timeout
        self.config = config or CaptionConfig()

        # 允许通过环境变量覆盖模型
        # 你可以设置 CAPTION_MODEL=qwen-vl-plus / gpt-4o-mini / 你自己的多模态模型名
        self.model = model or os.getenv("CAPTION_MODEL") or os.getenv("OPENAI_MODEL", "qwen-vl-plus")

        # 若未传入provider，做一个“最小provider”避免循环导入（参考你RiskAssessment写法）
        if provider is None:
            api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("请设置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY 环境变量")

            base_url = os.getenv("OPENAI_BASE_URL")
            # 如果你明确用百炼 compatible-mode，也可以把 base_url 写死
            # base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"

            class SimpleProvider:
                def __init__(self, api_key: str, base_url: Optional[str], model: str, timeout: int):
                    from openai import OpenAI
                    import httpx

                    self.api_key = api_key
                    self.base_url = base_url
                    self.model = model
                    self.timeout = timeout

                    self.client = OpenAI(
                        api_key=api_key,
                        base_url=base_url,
                        timeout=httpx.Timeout(timeout, connect=10.0),
                    )

                def chat(self, messages: List[Dict[str, Any]], tools=None):
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.2,
                    )
                    return resp.choices[0].message.content or ""

            provider = SimpleProvider(api_key=api_key, base_url=base_url, model=self.model, timeout=timeout)

        self.provider = provider
        logger.info(f"初始化MediaCaption工具: model={self.model}, timeout={timeout}s, num_frames={self.config.num_frames}")

    @property
    def name(self) -> str:
        return "media_caption"

    @property
    def description(self) -> str:
        return (
            "对上传的图片/视频生成中文caption（交通应急场景优先），"
            "视频通过抽帧进行多图理解，输出结构化JSON，便于RAG/检索/指挥记录。"
        )

    def _to_text(self, resp) -> str:
        if resp is None:
            return ""
        if isinstance(resp, str):
            return resp
        # 兼容你项目里的 ChatResponse
        if hasattr(resp, "content") and isinstance(resp.content, str):
            return resp.content
        # 兼容 OpenAI SDK 返回
        if hasattr(resp, "choices"):
            try:
                return resp.choices[0].message.content or ""
            except Exception:
                pass
        return str(resp)

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "media_path": {
                    "type": "string",
                    "description": "图片或视频的本地路径（Agent运行机器可访问）"
                },
                "media_type": {
                    "type": "string",
                    "description": "媒体类型，可选：image/video；不填则自动判断",
                    "enum": ["image", "video"]
                },
                "style": {
                    "type": "string",
                    "description": "caption风格：brief简要 / detailed更详细 / structured结构化要点",
                    "enum": ["brief", "detailed", "structured"]
                },
                "hint": {
                    "type": "string",
                    "description": "可选提示词：例如事故类型/地点等先验信息（会帮助模型聚焦，但不会强制编造）"
                },
                "num_frames": {
                    "type": "integer",
                    "description": "仅视频：抽帧数量（默认6）",
                    "minimum": 1,
                    "maximum": 16
                }
            },
            "required": ["media_path"]
        }

    def execute(
        self,
        media_path: str,
        media_type: Optional[str] = None,
        style: str = "brief",
        hint: Optional[str] = None,
        num_frames: Optional[int] = None,
    ) -> str:
        """
        生成caption，返回JSON字符串
        """
        start = time.time()

        if not os.path.exists(media_path):
            return json.dumps(
                {"status": "error", "message": f"文件不存在: {media_path}"},
                ensure_ascii=False, indent=2
            )

        style = style or self.config.style
        if num_frames is not None:
            self.config.num_frames = int(num_frames)

        # 自动判断媒体类型
        if not media_type:
            media_type = self._infer_media_type(media_path)

        try:
            if media_type == "image":
                result = self._caption_image(media_path, style=style, hint=hint)
            elif media_type == "video":
                result = self._caption_video(media_path, style=style, hint=hint)
            else:
                raise ValueError(f"不支持的media_type: {media_type}")

            result["elapsed_sec"] = round(time.time() - start, 3)
            result["status"] = "success"
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.exception("MediaCaption执行失败")
            return json.dumps(
                {"status": "error", "message": str(e), "media_path": media_path, "media_type": media_type},
                ensure_ascii=False, indent=2
            )

    # -------------------------
    # Core: image / video
    # -------------------------

    def _caption_image(self, image_path: str, style: str, hint: Optional[str]) -> Dict[str, Any]:
        mime = self._guess_mime(image_path) or "image/png"
        data_uri = self._file_to_data_uri(image_path, mime=mime)

        prompt = self._build_user_prompt(style=style, hint=hint, is_video=False)

        # OpenAI-compatible multimodal message format（data URI）
        messages = [
            {"role": "system", "content": self.CAPTION_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ]

        resp = self.provider.chat(messages, tools=None)
        raw_text = self._to_text(resp)
        parsed = self._safe_parse_json(raw_text)

        return {
            "media_type": "image",
            "media_path": image_path,
            "model": self.model,
            "style": style,
            "caption": parsed.get("caption"),
            "key_points": parsed.get("key_points", []),
            "risks": parsed.get("risks", []),
            "raw": raw_text[:2000],
        }

    def _caption_video(self, video_path: str, style: str, hint: Optional[str]) -> Dict[str, Any]:
        frames = self._sample_video_frames(video_path, self.config.num_frames)
        if not frames:
            raise RuntimeError("视频抽帧失败：未获得任何帧（请检查opencv/视频编码/路径权限）")

        prompt = self._build_user_prompt(style=style, hint=hint, is_video=True, num_frames=len(frames))

        # 多帧作为多张图输入
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for idx, (data_uri, _meta) in enumerate(frames):
            content.append({"type": "image_url", "image_url": {"url": data_uri}})

        messages = [
            {"role": "system", "content": self.CAPTION_SYSTEM},
            {"role": "user", "content": content},
        ]

        resp = self.provider.chat(messages, tools=None)
        raw_text = self._to_text(resp)
        parsed = self._safe_parse_json(raw_text)

        return {
            "media_type": "video",
            "media_path": video_path,
            "model": self.model,
            "style": style,
            "num_frames": len(frames),
            "caption": parsed.get("caption"),
            "key_points": parsed.get("key_points", []),
            "risks": parsed.get("risks", []),
            "raw": raw_text[:2000],
        }

    # -------------------------
    # Prompt / parsing helpers
    # -------------------------

    def _build_user_prompt(self, style: str, hint: Optional[str], is_video: bool, num_frames: int = 0) -> str:
        style_rules = {
            "brief": "生成1-2句话的简要caption。",
            "detailed": "生成更详细caption（建议4-8句），覆盖场景/事件/参与者/风险。",
            "structured": "以要点形式输出，caption一句话 + key_points数组（3-8条）+ risks数组（0-5条）。",
        }.get(style, "生成简要caption。")

        hint_part = f"\n先验提示（仅供参考，不要据此编造）：{hint}" if hint else ""
        video_part = f"\n这是视频抽取的{num_frames}帧，请综合这些帧进行整体描述。" if is_video else ""

        # 要求模型输出严格JSON：caption/key_points/risks
        return f"""请对媒体内容生成caption。
{style_rules}{video_part}{hint_part}

输出必须是JSON，格式如下：
{{
  "caption": "中文caption字符串",
  "key_points": ["要点1", "要点2"],
  "risks": ["潜在风险1", "潜在风险2"]
}}
"""

    def _safe_parse_json(self, text: str) -> Dict[str, Any]:
        # 1) 直接json.loads
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # 2) 提取markdown代码块
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

        # 3) 兜底：返回空结构，caption用原文截断
        return {"caption": text.strip()[:500], "key_points": [], "risks": []}

    # -------------------------
    # Media helpers
    # -------------------------

    def _infer_media_type(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            return "image"
        if ext in [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"]:
            return "video"
        # fallback by mime
        mime = self._guess_mime(path) or ""
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
        # 默认当图片（更安全），也可以raise
        return "image"

    def _guess_mime(self, path: str) -> Optional[str]:
        mime, _ = mimetypes.guess_type(path)
        return mime

    def _file_to_data_uri(self, path: str, mime: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    def _sample_video_frames(self, video_path: str, num_frames: int) -> List[Tuple[str, Dict[str, Any]]]:
        """
        均匀采样视频帧，返回[(data_uri, meta), ...]
        依赖opencv-python；如果你更想用ffmpeg也可以后续替换。
        """
        try:
            import cv2
        except ImportError:
            raise RuntimeError("缺少依赖opencv-python：请执行 `pip install opencv-python` 后重试")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频: {video_path}")

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

        if total <= 0:
            # 有些编码取不到frame_count，退化成按时间读
            total = 0

        # 均匀取样索引
        indices = self._uniform_indices(total, num_frames)

        results: List[Tuple[str, Dict[str, Any]]] = []
        for idx in indices:
            if total > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)

            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            # 编码为jpg（更通用）
            ok2, buf = cv2.imencode(".jpg", frame)
            if not ok2:
                continue

            b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
            data_uri = f"data:image/jpeg;base64,{b64}"

            meta = {"frame_index": int(idx), "fps": fps, "total_frames": total}
            results.append((data_uri, meta))

        cap.release()
        return results

    def _uniform_indices(self, total_frames: int, num_frames: int) -> List[int]:
        """
        total_frames可能为0（未知），此时就顺序取前num_frames帧（由VideoCapture.read推进）
        """
        if num_frames <= 1:
            return [0]

        if total_frames <= 0:
            # 让上层按顺序read
            return [0] * num_frames

        # 避免取到首尾全是黑帧：稍微避开边界（可按需调整）
        start = int(total_frames * 0.05)
        end = max(start + 1, int(total_frames * 0.95))

        span = end - start
        if span <= 0:
            return [0]

        step = span / float(num_frames)
        indices = [int(start + i * step) for i in range(num_frames)]
        # 去重&裁剪
        indices = [max(0, min(total_frames - 1, x)) for x in indices]
        # 保持数量（若重复，用递增补齐）
        fixed: List[int] = []
        seen = set()
        for x in indices:
            if x not in seen:
                fixed.append(x); seen.add(x)
        while len(fixed) < num_frames and fixed:
            nxt = min(total_frames - 1, fixed[-1] + 1)
            if nxt in seen:
                break
            fixed.append(nxt); seen.add(nxt)
        return fixed[:num_frames]
