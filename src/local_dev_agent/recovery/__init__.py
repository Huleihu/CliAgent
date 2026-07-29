"""S11 瞬态模型故障的恢复决策契约。"""

from .transient import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_JITTER_RATIO,
    DEFAULT_MAX_CONSECUTIVE_OVERLOADS,
    DEFAULT_MAX_DELAY_SECONDS,
    DEFAULT_MAX_RETRIES,
    TransientRecoveryPolicy,
    TransientRecoveryState,
    TransientRetryDecision,
)

__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_JITTER_RATIO",
    "DEFAULT_MAX_CONSECUTIVE_OVERLOADS",
    "DEFAULT_MAX_DELAY_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "TransientRecoveryPolicy",
    "TransientRecoveryState",
    "TransientRetryDecision",
]
