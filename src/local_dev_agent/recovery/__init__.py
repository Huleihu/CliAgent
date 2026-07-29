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
from .executor import (
    RandomRecoveryJitterSource,
    RecoveryJitterSource,
    RecoverySleeper,
    SystemRecoverySleeper,
    TransientModelRecoveryExecutor,
    TransientModelRecoveryResult,
    TransientRecoveryExhaustedError,
)
from .output_budget import (
    DEFAULT_ESCALATED_MAX_OUTPUT_TOKENS,
    DEFAULT_MAX_OUTPUT_CONTINUATIONS,
    OUTPUT_CONTINUATION_PROMPT,
    OutputContinuationPolicy,
    OutputBudgetUpgradePolicy,
)

__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_ESCALATED_MAX_OUTPUT_TOKENS",
    "DEFAULT_MAX_OUTPUT_CONTINUATIONS",
    "DEFAULT_JITTER_RATIO",
    "DEFAULT_MAX_CONSECUTIVE_OVERLOADS",
    "DEFAULT_MAX_DELAY_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "RandomRecoveryJitterSource",
    "RecoveryJitterSource",
    "RecoverySleeper",
    "OutputBudgetUpgradePolicy",
    "OutputContinuationPolicy",
    "OUTPUT_CONTINUATION_PROMPT",
    "SystemRecoverySleeper",
    "TransientModelRecoveryExecutor",
    "TransientModelRecoveryResult",
    "TransientRecoveryExhaustedError",
    "TransientRecoveryPolicy",
    "TransientRecoveryState",
    "TransientRetryDecision",
]
