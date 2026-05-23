"""LLM 配置：OpenAI 兼容，配置驱动，全 LLM 通吃。

DeepSeek / OpenAI / 本地 Ollama / 任何 OpenAI 兼容端点 —— 只是 base_url+key+model 不同。
从 .env 读，也可代码覆盖。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).parent.parent


def _load_dotenv() -> None:
    """轻量加载 .env（不强依赖 python-dotenv，但有就用）。"""
    try:
        from dotenv import load_dotenv
        load_dotenv(_HERE / ".env")
    except Exception:
        # 手动兜底解析
        env_path = _HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@dataclass
class LLMConfig:
    """一个 OpenAI 兼容 LLM 端点的全部配置。"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.8          # 叙事要点温度，但别太放飞
    max_tokens: int = 2048
    debug: bool = False
    # ── 上下文压缩（独立运行 agent loop；引擎才是长程记忆，历史可激进裁剪）──
    history_char_budget: int = 40000  # 历史体量超此（粗估字符≈token）就压缩；≤0 关闭压缩
    keep_recent_turns: int = 6        # 至少完整保留最近 N 个玩家回合（保叙事连贯）
    old_tool_result_cap: int = 600    # 旧回合工具结果截断到此长度（最新一轮保留完整）

    @classmethod
    def from_env(cls) -> "LLMConfig":
        _load_dotenv()
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("LLM_MODEL", "gpt-4o"),
            temperature=float(os.environ.get("LLM_TEMPERATURE", "0.8")),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "2048")),
            debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
            history_char_budget=int(os.environ.get("HISTORY_CHAR_BUDGET", "40000")),
            keep_recent_turns=int(os.environ.get("KEEP_RECENT_TURNS", "6")),
            old_tool_result_cap=int(os.environ.get("OLD_TOOL_RESULT_CAP", "600")),
        )

    def validate(self) -> str | None:
        """返回错误说明，或 None 表示 OK。"""
        if not self.api_key or self.api_key in ("your-api-key-here", "***"):
            return ("未配置 LLM API key。请在 .env 设 OPENAI_API_KEY"
                    "（DeepSeek/OpenAI/本地皆可，配 OPENAI_BASE_URL + LLM_MODEL）。")
        return None
