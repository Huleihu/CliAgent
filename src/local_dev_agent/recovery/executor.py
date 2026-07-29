"""在父 Agent Runtime 中执行瞬态模型故障恢复。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import random
import time
from typing import Protocol

from local_dev_agent.models import ModelResponse, ModelTransientError

from .transient import (
    TransientRecoveryPolicy,
    TransientRecoveryState,
)


class RecoverySleeper(Protocol):
    """隔离真实等待，避免恢复策略测试依赖墙上时钟。"""

    def sleep(self, delay_seconds: float) -> None:
        """等待给定的非负秒数。"""


class RecoveryJitterSource(Protocol):
    """为每次退避提供 0 到 1 之间的抖动分数。"""

    def next_fraction(self) -> float:
        """返回下一次退避使用的抖动分数。"""


class SystemRecoverySleeper:
    """使用标准库等待真实重试延迟。"""

    def sleep(self, delay_seconds: float) -> None:
        """将等待交给标准库，具体延迟已由策略验证。"""

        time.sleep(delay_seconds)


class RandomRecoveryJitterSource:
    """使用标准库随机源分散并发重试时间。"""

    def next_fraction(self) -> float:
        """返回闭区间内的随机分数，由策略再次验证边界。"""

        return random.random()


class TransientRecoveryExhaustedError(RuntimeError):
    """当瞬态故障已耗尽本次模型调用允许的重试次数时抛出。"""

    def __init__(self, *, max_retries: int) -> None:
        super().__init__(f"模型瞬态故障重试已达到最大次数“{max_retries}”。")
        self.max_retries = max_retries


@dataclass(frozen=True, slots=True)
class TransientModelRecoveryResult:
    """一次最终成功模型调用的响应和后续恢复状态。"""

    response: ModelResponse
    state: TransientRecoveryState

    def __post_init__(self) -> None:
        if not isinstance(self.response, ModelResponse):
            raise ValueError("字段“response”必须是 ModelResponse 对象。")
        if not isinstance(self.state, TransientRecoveryState):
            raise ValueError("字段“state”必须是 TransientRecoveryState 对象。")


class TransientModelRecoveryExecutor:
    """以纯策略决定为依据，执行有界等待和同请求模型重试。"""

    def __init__(
        self,
        policy: TransientRecoveryPolicy,
        *,
        primary_model_id: str,
        sleeper: RecoverySleeper | None = None,
        jitter_source: RecoveryJitterSource | None = None,
    ) -> None:
        if not isinstance(policy, TransientRecoveryPolicy):
            raise ValueError("policy 必须是 TransientRecoveryPolicy 对象。")
        if not isinstance(primary_model_id, str) or not primary_model_id.strip():
            raise ValueError("字段“primary_model_id”必须是非空字符串。")
        if sleeper is not None and not hasattr(sleeper, "sleep"):
            raise ValueError("sleeper 必须提供 sleep 方法。")
        if jitter_source is not None and not hasattr(jitter_source, "next_fraction"):
            raise ValueError("jitter_source 必须提供 next_fraction 方法。")
        self._policy = policy
        self._primary_model_id = primary_model_id.strip()
        self._sleeper = sleeper or SystemRecoverySleeper()
        self._jitter_source = jitter_source or RandomRecoveryJitterSource()

    def initial_state(self) -> TransientRecoveryState:
        """为一个父 Agent Run 创建独立的恢复状态。"""

        return TransientRecoveryState(current_model_id=self._primary_model_id)

    def execute(
        self,
        operation: Callable[[str], ModelResponse],
        state: TransientRecoveryState,
    ) -> TransientModelRecoveryResult:
        """以当前模型调用操作；仅对瞬态错误按策略等待并重试。"""

        if not callable(operation):
            raise ValueError("operation 必须是可调用对象。")
        if not isinstance(state, TransientRecoveryState):
            raise ValueError("state 必须是 TransientRecoveryState 对象。")

        retry_index = 0
        current_state = state
        while True:
            try:
                response = operation(current_state.current_model_id)
            except ModelTransientError as error:
                decision = self._policy.decide(
                    error,
                    current_state,
                    retry_index=retry_index,
                    jitter_fraction=self._jitter_source.next_fraction(),
                )
                current_state = decision.next_state
                if not decision.should_retry:
                    raise TransientRecoveryExhaustedError(
                        max_retries=self._policy.max_retries,
                    ) from error
                delay_seconds = decision.delay_seconds
                if delay_seconds is None:
                    raise AssertionError("可重试决策必须包含等待时间。")
                self._sleeper.sleep(delay_seconds)
                retry_index += 1
                continue
            return TransientModelRecoveryResult(
                response=response,
                state=self._policy.record_success(current_state),
            )
