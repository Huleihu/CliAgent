"""DeepSeek Anthropic 兼容接口的本地配置。"""

from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping


class DeepSeekConfigurationError(ValueError):
    """当 DeepSeek 本地配置缺失或无效时抛出。"""


def _required_value(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise DeepSeekConfigurationError(f"环境变量“{name}”必须设置为非空值。")
    return value


@dataclass(frozen=True, slots=True)
class DeepSeekSettings:
    """创建 DeepSeek Anthropic 客户端所需的不可变运行配置。"""

    api_key: str
    base_url: str
    model: str
    max_tokens: int

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str] | None = None,
    ) -> "DeepSeekSettings":
        """从环境变量读取显式配置，不依赖 SDK 的隐式变量命名。"""

        environment = values if values is not None else environ
        max_tokens_text = _required_value(environment, "DEEPSEEK_MAX_TOKENS")
        try:
            max_tokens = int(max_tokens_text)
        except ValueError as error:
            raise DeepSeekConfigurationError(
                "环境变量“DEEPSEEK_MAX_TOKENS”必须是正整数。"
            ) from error
        if max_tokens < 1:
            raise DeepSeekConfigurationError(
                "环境变量“DEEPSEEK_MAX_TOKENS”必须是正整数。"
            )

        return cls(
            api_key=_required_value(environment, "DEEPSEEK_API_KEY"),
            base_url=_required_value(
                environment,
                "DEEPSEEK_ANTHROPIC_BASE_URL",
            ),
            model=_required_value(environment, "DEEPSEEK_MODEL"),
            max_tokens=max_tokens,
        )
