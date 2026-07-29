"""S11 瞬态模型故障的纯退避与备用模型决策。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from local_dev_agent.models import ModelOverloadedError, ModelTransientError


DEFAULT_MAX_RETRIES = 10
"""一次模型调用最多允许的瞬态故障重试次数。"""

DEFAULT_BASE_DELAY_SECONDS = 0.5
"""指数退避的首个基础等待时间。"""

DEFAULT_MAX_DELAY_SECONDS = 32.0
"""指数退避基础等待时间的上限。"""

DEFAULT_JITTER_RATIO = 0.25
"""抖动相对于基础等待时间的最大比例。"""

DEFAULT_MAX_CONSECUTIVE_OVERLOADS = 3
"""连续服务过载后尝试切换备用模型的阈值。"""


def _require_nonempty_text(field_name: str, value: str) -> str:
    """拒绝无法作为模型标识的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")
    return value.strip()


def _require_nonnegative_integer(field_name: str, value: int) -> int:
    """验证计数和重试预算，避免布尔值进入恢复状态。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"字段“{field_name}”必须是非负整数。")
    return value


def _require_positive_integer(field_name: str, value: int) -> int:
    """验证至少执行一次才有意义的恢复阈值。"""

    _require_nonnegative_integer(field_name, value)
    if value < 1:
        raise ValueError(f"字段“{field_name}”必须是正整数。")
    return value


def _require_nonnegative_finite_number(field_name: str, value: float) -> float:
    """验证等待时间与比例，避免生成不可执行的退避决策。"""

    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(f"字段“{field_name}”必须是非负有限数值。")
    return float(value)


@dataclass(frozen=True, slots=True)
class TransientRecoveryState:
    """跨连续模型调用保留当前模型和过载计数。"""

    current_model_id: str
    consecutive_overloads: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "current_model_id",
            _require_nonempty_text("current_model_id", self.current_model_id),
        )
        _require_nonnegative_integer(
            "consecutive_overloads",
            self.consecutive_overloads,
        )


@dataclass(frozen=True, slots=True)
class TransientRetryDecision:
    """一次瞬态故障后由 Runtime 执行的重试与模型选择决定。"""

    should_retry: bool
    delay_seconds: float | None
    next_state: TransientRecoveryState
    fallback_switched: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.should_retry, bool):
            raise ValueError("字段“should_retry”必须是布尔值。")
        if not isinstance(self.next_state, TransientRecoveryState):
            raise ValueError("字段“next_state”必须是 TransientRecoveryState 对象。")
        if not isinstance(self.fallback_switched, bool):
            raise ValueError("字段“fallback_switched”必须是布尔值。")
        if self.should_retry:
            if self.delay_seconds is None:
                raise ValueError("重试决策必须提供等待时间。")
            _require_nonnegative_finite_number("delay_seconds", self.delay_seconds)
        elif self.delay_seconds is not None:
            raise ValueError("不重试的决策不能提供等待时间。")
        if self.fallback_switched and self.next_state.current_model_id == "":
            raise ValueError("备用模型切换决策必须保留有效模型标识。")


@dataclass(frozen=True, slots=True)
class TransientRecoveryPolicy:
    """将瞬态错误转换为有界重试、退避和备用模型选择决定。"""

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    jitter_ratio: float = DEFAULT_JITTER_RATIO
    max_consecutive_overloads: int = DEFAULT_MAX_CONSECUTIVE_OVERLOADS
    fallback_model_id: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_integer("max_retries", self.max_retries)
        base_delay_seconds = _require_nonnegative_finite_number(
            "base_delay_seconds",
            self.base_delay_seconds,
        )
        max_delay_seconds = _require_nonnegative_finite_number(
            "max_delay_seconds",
            self.max_delay_seconds,
        )
        if max_delay_seconds < base_delay_seconds:
            raise ValueError("字段“max_delay_seconds”不能小于“base_delay_seconds”。")
        jitter_ratio = _require_nonnegative_finite_number(
            "jitter_ratio",
            self.jitter_ratio,
        )
        if jitter_ratio > 1:
            raise ValueError("字段“jitter_ratio”不能大于 1。")
        _require_positive_integer(
            "max_consecutive_overloads",
            self.max_consecutive_overloads,
        )
        if self.fallback_model_id is not None:
            object.__setattr__(
                self,
                "fallback_model_id",
                _require_nonempty_text("fallback_model_id", self.fallback_model_id),
            )
        object.__setattr__(self, "base_delay_seconds", base_delay_seconds)
        object.__setattr__(self, "max_delay_seconds", max_delay_seconds)
        object.__setattr__(self, "jitter_ratio", jitter_ratio)

    def decide(
        self,
        error: ModelTransientError,
        state: TransientRecoveryState,
        *,
        retry_index: int,
        jitter_fraction: float,
    ) -> TransientRetryDecision:
        """为本次瞬态失败计算下一状态；不执行等待或模型调用。"""

        if not isinstance(error, ModelTransientError):
            raise ValueError("error 必须是 ModelTransientError 对象。")
        if not isinstance(state, TransientRecoveryState):
            raise ValueError("state 必须是 TransientRecoveryState 对象。")
        _require_nonnegative_integer("retry_index", retry_index)
        jitter_fraction = _require_nonnegative_finite_number(
            "jitter_fraction",
            jitter_fraction,
        )
        if jitter_fraction > 1:
            raise ValueError("字段“jitter_fraction”不能大于 1。")

        next_state, fallback_switched = self._next_state(error, state)
        if retry_index >= self.max_retries:
            return TransientRetryDecision(
                should_retry=False,
                delay_seconds=None,
                next_state=next_state,
                fallback_switched=fallback_switched,
            )
        return TransientRetryDecision(
            should_retry=True,
            delay_seconds=self._delay_seconds(error, retry_index, jitter_fraction),
            next_state=next_state,
            fallback_switched=fallback_switched,
        )

    @staticmethod
    def record_success(state: TransientRecoveryState) -> TransientRecoveryState:
        """成功响应会终止连续过载序列，但保留已选定的当前模型。"""

        if not isinstance(state, TransientRecoveryState):
            raise ValueError("state 必须是 TransientRecoveryState 对象。")
        return TransientRecoveryState(current_model_id=state.current_model_id)

    def _next_state(
        self,
        error: ModelTransientError,
        state: TransientRecoveryState,
    ) -> tuple[TransientRecoveryState, bool]:
        """仅连续 529 增加过载计数，并在阈值处尝试切换备用模型。"""

        if not isinstance(error, ModelOverloadedError):
            return TransientRecoveryState(current_model_id=state.current_model_id), False

        consecutive_overloads = state.consecutive_overloads + 1
        if consecutive_overloads < self.max_consecutive_overloads:
            return (
                TransientRecoveryState(
                    current_model_id=state.current_model_id,
                    consecutive_overloads=consecutive_overloads,
                ),
                False,
            )

        fallback_model_id = self.fallback_model_id
        fallback_switched = (
            fallback_model_id is not None
            and fallback_model_id != state.current_model_id
        )
        return (
            TransientRecoveryState(
                current_model_id=(
                    fallback_model_id if fallback_switched else state.current_model_id
                ),
            ),
            fallback_switched,
        )

    def _delay_seconds(
        self,
        error: ModelTransientError,
        retry_index: int,
        jitter_fraction: float,
    ) -> float:
        """优先使用 Provider 等待建议，否则应用有上限的指数退避与抖动。"""

        if error.retry_after_seconds is not None:
            return error.retry_after_seconds
        base_delay = min(
            self.base_delay_seconds * (2**retry_index),
            self.max_delay_seconds,
        )
        return base_delay + (base_delay * self.jitter_ratio * jitter_fraction)
