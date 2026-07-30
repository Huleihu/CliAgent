"""后台命令任务的不可变生命周期契约。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum

from .errors import InvalidBackgroundTaskTransitionError


def _require_nonempty_text(field_name: str, value: str) -> None:
    """拒绝无法关联、展示或持久化的空白文本。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段“{field_name}”必须是非空字符串。")


def _normalize_utc_timestamp(value: datetime, *, field_name: str) -> datetime:
    """统一保存带时区的 UTC 时间，避免仓储恢复后产生歧义。"""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"字段“{field_name}”必须是带时区的 datetime。")
    return value.astimezone(timezone.utc)


def _validate_exit_code(value: int | None) -> None:
    """校验进程退出码，保留异常中断时的空值语义。"""

    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError("字段“exit_code”必须是整数或 None。")


class BackgroundTaskStatus(StrEnum):
    """首版后台任务的最小生命周期状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    """命令执行适配器返回的原始退出信息与输出文本。"""

    exit_code: int
    output: str

    def __post_init__(self) -> None:
        """确保领域服务可根据稳定的退出码决定终态。"""

        _validate_exit_code(self.exit_code)
        if not isinstance(self.output, str):
            raise ValueError("字段“output”必须是字符串。")


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    """一项归属明确、可由不同基础设施保存的后台命令任务快照。"""

    task_id: str
    session_id: str
    run_id: str
    tool_call_id: str
    command: str
    status: BackgroundTaskStatus
    created_at: datetime
    finished_at: datetime | None = None
    exit_code: int | None = None
    output_summary: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        """验证状态与终态字段的一致性，并冻结 UTC 时间快照。"""

        for field_name, value in (
            ("task_id", self.task_id),
            ("session_id", self.session_id),
            ("run_id", self.run_id),
            ("tool_call_id", self.tool_call_id),
            ("command", self.command),
        ):
            _require_nonempty_text(field_name, value)
        if not isinstance(self.status, BackgroundTaskStatus):
            raise ValueError("字段“status”必须是 BackgroundTaskStatus。")
        created_at = _normalize_utc_timestamp(self.created_at, field_name="created_at")
        object.__setattr__(self, "created_at", created_at)
        if self.finished_at is not None:
            finished_at = _normalize_utc_timestamp(
                self.finished_at,
                field_name="finished_at",
            )
            if finished_at < created_at:
                raise ValueError("字段“finished_at”不能早于“created_at”。")
            object.__setattr__(self, "finished_at", finished_at)
        _validate_exit_code(self.exit_code)
        if self.output_summary is not None and not isinstance(self.output_summary, str):
            raise ValueError("字段“output_summary”必须是字符串或 None。")
        if self.failure_reason is not None:
            _require_nonempty_text("failure_reason", self.failure_reason)
        self._validate_lifecycle_fields()

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        session_id: str,
        run_id: str,
        tool_call_id: str,
        command: str,
        created_at: datetime | None = None,
    ) -> "BackgroundTask":
        """创建尚未结束的后台任务，不预设任何执行结果。"""

        return cls(
            task_id=task_id,
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            command=command,
            status=BackgroundTaskStatus.RUNNING,
            created_at=created_at or datetime.now(timezone.utc),
        )

    @property
    def is_terminal(self) -> bool:
        """判断任务是否已经产生可通知的最终事实。"""

        return self.status in {
            BackgroundTaskStatus.COMPLETED,
            BackgroundTaskStatus.FAILED,
        }

    def complete(
        self,
        *,
        output_summary: str,
        finished_at: datetime | None = None,
    ) -> "BackgroundTask":
        """以成功退出码结束任务，并返回新的不可变快照。"""

        self._require_running(BackgroundTaskStatus.COMPLETED)
        if not isinstance(output_summary, str):
            raise ValueError("字段“output_summary”必须是字符串。")
        return replace(
            self,
            status=BackgroundTaskStatus.COMPLETED,
            finished_at=finished_at or datetime.now(timezone.utc),
            exit_code=0,
            output_summary=output_summary,
            failure_reason=None,
        )

    def fail(
        self,
        *,
        output_summary: str,
        exit_code: int | None = None,
        failure_reason: str | None = None,
        finished_at: datetime | None = None,
    ) -> "BackgroundTask":
        """以非零退出码或执行异常结束任务，并保留可展示的诊断摘要。"""

        self._require_running(BackgroundTaskStatus.FAILED)
        if not isinstance(output_summary, str):
            raise ValueError("字段“output_summary”必须是字符串。")
        _validate_exit_code(exit_code)
        if exit_code == 0:
            raise ValueError("失败的后台任务不能使用退出码 0。")
        if failure_reason is not None:
            _require_nonempty_text("failure_reason", failure_reason)
        if exit_code is None and failure_reason is None:
            raise ValueError("失败的后台任务必须提供非零退出码或失败原因。")
        return replace(
            self,
            status=BackgroundTaskStatus.FAILED,
            finished_at=finished_at or datetime.now(timezone.utc),
            exit_code=exit_code,
            output_summary=output_summary,
            failure_reason=failure_reason,
        )

    def _require_running(self, target_status: BackgroundTaskStatus) -> None:
        if self.status is not BackgroundTaskStatus.RUNNING:
            raise InvalidBackgroundTaskTransitionError(
                task_id=self.task_id,
                status=self.status.value,
                target_status=target_status.value,
            )

    def _validate_lifecycle_fields(self) -> None:
        """确保运行中与终态快照均可被未来仓储无歧义恢复。"""

        if self.status is BackgroundTaskStatus.RUNNING:
            if any(
                value is not None
                for value in (
                    self.finished_at,
                    self.exit_code,
                    self.output_summary,
                    self.failure_reason,
                )
            ):
                raise ValueError("运行中的后台任务不能包含终态结果。")
            return
        if self.finished_at is None or self.output_summary is None:
            raise ValueError("已结束的后台任务必须包含结束时间和输出摘要。")
        if self.status is BackgroundTaskStatus.COMPLETED:
            if self.exit_code != 0 or self.failure_reason is not None:
                raise ValueError("已完成的后台任务必须使用退出码 0 且不包含失败原因。")
            return
        if self.exit_code is None and self.failure_reason is None:
            raise ValueError("失败的后台任务必须包含非零退出码或失败原因。")
        if self.exit_code == 0:
            raise ValueError("失败的后台任务不能使用退出码 0。")

