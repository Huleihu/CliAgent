"""S08 上下文预算与压缩边界的领域契约。"""

from .artifacts import (
    ArtifactReadError,
    FileSystemToolResultArtifactStore,
    ToolResultArtifact,
    ToolResultArtifactPage,
    ToolResultArtifactReader,
    ToolResultArtifactStore,
)
from .budget import (
    ContextBudget,
    ContextBudgetEstimator,
    ContextBudgetReport,
    ContextInputSnapshot,
    Utf8ByteContextBudgetEstimator,
)
from .checkpoints import (
    HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION,
    HistorySummaryCheckpoint,
    HistorySummaryCheckpointSourceMismatchError,
    calculate_history_source_checksum,
    select_safe_history_checkpoint_boundary,
    validate_history_summary_checkpoint,
)
from .checkpoint_ports import HistorySummaryCheckpointRepository
from .checkpoint_ports import HistorySummaryCheckpointRebuilder
from .checkpoint_rebuilder import FullHistorySummaryCheckpointRebuilder
from .checkpoint_service import HistorySummaryCheckpointService
from .checkpoint_views import (
    build_history_summary_checkpoint_messages,
    build_history_summary_checkpoint_view,
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
    "HISTORY_SUMMARY_CHECKPOINT_SCHEMA_VERSION",
    "HistorySummaryCheckpoint",
    "HistorySummaryCheckpointSourceMismatchError",
    "HistorySummaryCheckpointRepository",
    "HistorySummaryCheckpointRebuilder",
    "HistorySummaryCheckpointService",
    "ArtifactReadError",
    "ConversationSummarizer",
    "ConversationSnipCompactor",
    "FileSystemToolResultArtifactStore",
    "HistorySummaryCompactor",
    "HistorySummaryGenerationError",
    "FullHistorySummaryCheckpointRebuilder",
    "ModelConversationSummarizer",
    "ToolResultArtifact",
    "ToolResultArtifactPage",
    "ToolResultArtifactReader",
    "ToolResultArtifactStore",
    "ToolResultBudgetCompactor",
    "ToolResultBudgetResult",
    "ToolResultMicroCompactor",
    "Utf8ByteContextBudgetEstimator",
    "calculate_history_source_checksum",
    "build_history_summary_checkpoint_messages",
    "build_history_summary_checkpoint_view",
    "select_safe_history_checkpoint_boundary",
    "validate_history_summary_checkpoint",
]
