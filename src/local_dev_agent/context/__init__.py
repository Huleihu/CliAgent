"""S08 上下文预算与压缩边界的领域契约。"""

from .artifacts import (
    FileSystemToolResultArtifactStore,
    ToolResultArtifact,
    ToolResultArtifactStore,
)
from .budget import (
    ContextBudget,
    ContextBudgetEstimator,
    ContextBudgetReport,
    ContextInputSnapshot,
    Utf8ByteContextBudgetEstimator,
)
from .manager import ContextBudgetExceededError, ContextManager, ContextPackage
from .tool_result_budget import ToolResultBudgetCompactor, ToolResultBudgetResult
from .structural_compaction import (
    ConversationSnipCompactor,
    ToolResultMicroCompactor,
)
from .summary import (
    ConversationSummarizer,
    HistorySummaryCompactor,
    HistorySummaryGenerationError,
    ModelConversationSummarizer,
)

__all__ = [
    "ContextBudget",
    "ContextBudgetExceededError",
    "ContextBudgetEstimator",
    "ContextBudgetReport",
    "ContextInputSnapshot",
    "ContextManager",
    "ContextPackage",
    "ConversationSummarizer",
    "ConversationSnipCompactor",
    "FileSystemToolResultArtifactStore",
    "HistorySummaryCompactor",
    "HistorySummaryGenerationError",
    "ModelConversationSummarizer",
    "ToolResultArtifact",
    "ToolResultArtifactStore",
    "ToolResultBudgetCompactor",
    "ToolResultBudgetResult",
    "ToolResultMicroCompactor",
    "Utf8ByteContextBudgetEstimator",
]
