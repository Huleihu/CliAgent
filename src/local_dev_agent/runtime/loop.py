"""有界 Agent Loop：模型调用、工具执行与结果回填。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from local_dev_agent.context import ContextInputSnapshot, ContextManager
from local_dev_agent.domain.state import (
    RunState,
    RunStatus,
    SessionState,
    StepState,
    StepStatus,
    StepType,
)
from local_dev_agent.hooks import (
    HookEvent,
    HookExecutionError,
    HookRunner,
    StopContext,
    UserPromptSubmitContext,
)
from local_dev_agent.models import (
    MessageRole,
    ModelClient,
    ModelContextWindowExceededError,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from local_dev_agent.storage.ports import StateRepository
from local_dev_agent.storage.conversation_ports import ConversationRepository
from local_dev_agent.todos import TodoReminderPolicy
from local_dev_agent.tools import (
    CONTEXT_COMPACTION_TOOL_TAG,
    DELEGATION_TOOL_TAG,
    ToolCallRequest,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)
from local_dev_agent.tools.errors import ToolNotFoundError
from local_dev_agent.tools.schema import ToolCallResult

from .errors import AgentLoopExhaustedError, UnsupportedModelResponseError
from .input_service import RuntimeStartResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    """一次 Agent Loop 成功结束后的状态快照、最终响应和步骤历史。"""

    session: SessionState
    run: RunState
    step: StepState
    response: ModelResponse
    steps: tuple[StepState, ...] = ()


class MinimalAgentLoop:
    """驱动有界的模型—工具—结果回填循环，直到模型完成任务。"""

    def __init__(
        self,
        repository: StateRepository,
        model: ModelClient,
        registry: ToolRegistry | None = None,
        conversation_repository: ConversationRepository | None = None,
        *,
        max_turns: int = 10,
        hook_runner: HookRunner | None = None,
        system_prompt: str | None = None,
        todo_reminder_policy: TodoReminderPolicy | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        if max_turns < 1:
            raise ValueError("Agent Loop 的最大模型调用轮次必须大于或等于 1。")
        if system_prompt is not None and (
            not isinstance(system_prompt, str) or not system_prompt.strip()
        ):
            raise ValueError("Agent Loop 的系统提示必须是非空字符串。")
        self._repository = repository
        self._model = model
        self._registry = registry or ToolRegistry()
        self._conversation_repository = conversation_repository
        self._hook_runner = hook_runner
        self._executor = ToolExecutor(self._registry, hook_runner=hook_runner)
        self._max_turns = max_turns
        self._system_prompt = system_prompt
        self._todo_reminder_policy = todo_reminder_policy
        self._context_manager = context_manager

    def execute(
        self,
        start: RuntimeStartResult,
        *,
        occurred_at: datetime | None = None,
    ) -> AgentLoopResult:
        """持续执行模型和工具，直到得到最终文本或耗尽允许轮次。"""

        timestamp = occurred_at or datetime.now(timezone.utc)
        log_context = {
            "event_id": start.event.event_id,
            "session_id": start.session.session_id,
            "run_id": start.run.run_id,
            "step_id": start.first_step.step_id,
        }
        logger.info("运行开始恢复。", extra=log_context)
        running_run = self._start_run(start.run, timestamp)
        current_step = self._start_step(start.first_step, timestamp)
        completed_steps: list[StepState] = []
        user_message = ModelMessage(
            role=MessageRole.USER,
            content=(TextBlock(text=start.event.content),),
        )
        conversation = self._load_conversation(start.session.session_id)
        conversation.append(user_message)
        self._append_messages(start.session.session_id, (user_message,))
        self._trigger_user_prompt_submit(
            session_id=start.session.session_id,
            run_id=running_run.run_id,
            step_id=current_step.step_id,
            prompt=start.event.content,
            log_context=log_context,
        )
        force_context_compaction_next = False

        for turn_number in range(1, self._max_turns + 1):
            response = self._generate(
                session_id=start.session.session_id,
                run_id=running_run.run_id,
                conversation=tuple(conversation),
                log_context=log_context,
                force_history_compaction=force_context_compaction_next,
            )
            force_context_compaction_next = False
            assistant_message = ModelMessage(
                role=MessageRole.ASSISTANT,
                content=response.content,
            )
            conversation.append(assistant_message)
            self._append_messages(start.session.session_id, (assistant_message,))
            tool_blocks = tuple(
                block for block in response.content if isinstance(block, ToolUseBlock)
            )

            if tool_blocks:
                current_step = self._succeed_step(current_step, timestamp)
                completed_steps.append(current_step)
                tool_results, tool_steps = self._execute_tools(
                    session_id=start.session.session_id,
                    run_id=running_run.run_id,
                    tool_blocks=tool_blocks,
                    timestamp=timestamp,
                    log_context=log_context,
                )
                completed_steps.extend(tool_steps)
                self._record_todo_tool_turn(tool_blocks, tool_results)
                force_context_compaction_next = self._requested_context_compaction(
                    tool_blocks,
                    tool_results,
                )
                tool_result_message = ModelMessage(
                    role=MessageRole.USER,
                    content=tool_results,
                )
                conversation.append(tool_result_message)
                self._append_messages(
                    start.session.session_id,
                    (tool_result_message,),
                )

                if turn_number == self._max_turns:
                    exhausted_run = running_run.transition_to(
                        RunStatus.EXHAUSTED,
                        occurred_at=timestamp,
                        reason="达到 Agent Loop 最大模型调用轮次。",
                    )
                    self._repository.save_run(exhausted_run)
                    available_session = start.session.finish_run(
                        exhausted_run.run_id,
                        occurred_at=timestamp,
                    )
                    self._repository.save_session(available_session)
                    logger.warning("运行已耗尽最大模型调用轮次。", extra=log_context)
                    raise AgentLoopExhaustedError(max_turns=self._max_turns)

                current_step = self._create_and_start_step(
                    run_id=running_run.run_id,
                    step_type=StepType.MODEL,
                    timestamp=timestamp,
                )
                continue

            if response.stop_reason is not StopReason.END_TURN or not response.text_blocks:
                logger.warning("模型响应需要尚未实现的处理分支。", extra=log_context)
                raise UnsupportedModelResponseError(stop_reason=response.stop_reason)

            current_step = self._succeed_step(current_step, timestamp)
            completed_steps.append(current_step)
            self._trigger_stop(
                session_id=start.session.session_id,
                run_id=running_run.run_id,
                step_id=current_step.step_id,
                response=response,
                log_context=log_context,
            )
            completed_run = running_run.transition_to(
                RunStatus.COMPLETED,
                occurred_at=timestamp,
            )
            self._repository.save_run(completed_run)
            available_session = start.session.finish_run(
                completed_run.run_id,
                occurred_at=timestamp,
            )
            self._repository.save_session(available_session)
            logger.info("运行已完成。", extra=log_context)
            return AgentLoopResult(
                session=available_session,
                run=completed_run,
                step=current_step,
                response=response,
                steps=tuple(completed_steps),
            )

        raise AssertionError("最大轮次控制未覆盖所有循环分支。")

    def _load_conversation(self, session_id: str) -> list[ModelMessage]:
        if self._conversation_repository is None:
            return []
        return list(self._conversation_repository.get_messages(session_id))

    def _append_messages(
        self,
        session_id: str,
        messages: tuple[ModelMessage, ...],
    ) -> None:
        if self._conversation_repository is not None:
            self._conversation_repository.append_messages(session_id, messages)

    def _trigger_user_prompt_submit(
        self,
        *,
        session_id: str,
        run_id: str,
        step_id: str,
        prompt: str,
        log_context: dict[str, str],
    ) -> None:
        """在输入持久化后触发观察型 Hook，不允许其改变既有用户消息。"""

        if self._hook_runner is None:
            return
        try:
            self._hook_runner.trigger(
                HookEvent.USER_PROMPT_SUBMIT,
                UserPromptSubmitContext(
                    session_id=session_id,
                    run_id=run_id,
                    step_id=step_id,
                    prompt=prompt,
                ),
            )
        except HookExecutionError:
            logger.warning(
                "用户输入提交 Hook 失败，不影响模型调用。",
                exc_info=True,
                extra=log_context,
            )

    def _trigger_stop(
        self,
        *,
        session_id: str,
        run_id: str,
        step_id: str,
        response: ModelResponse,
        log_context: dict[str, str],
    ) -> None:
        """在运行完成前触发观察型 Stop Hook，不允许其阻止收尾。"""

        if self._hook_runner is None:
            return
        try:
            self._hook_runner.trigger(
                HookEvent.STOP,
                StopContext(
                    session_id=session_id,
                    run_id=run_id,
                    step_id=step_id,
                    response=response,
                ),
            )
        except HookExecutionError:
            logger.warning(
                "停止 Hook 失败，不影响运行完成。",
                exc_info=True,
                extra=log_context,
            )

    def _start_run(self, run: RunState, timestamp: datetime) -> RunState:
        recovering_run = run.transition_to(RunStatus.RECOVERING, occurred_at=timestamp)
        self._repository.save_run(recovering_run)
        running_run = recovering_run.transition_to(RunStatus.RUNNING, occurred_at=timestamp)
        self._repository.save_run(running_run)
        return running_run

    def _start_step(self, step: StepState, timestamp: datetime) -> StepState:
        executing_step = step.transition_to(StepStatus.EXECUTING, occurred_at=timestamp)
        self._repository.save_step(executing_step)
        return executing_step

    def _create_and_start_step(
        self,
        *,
        run_id: str,
        step_type: StepType,
        timestamp: datetime,
    ) -> StepState:
        pending_step = StepState.create(
            run_id=run_id,
            step_type=step_type,
            created_at=timestamp,
        )
        self._repository.save_step(pending_step)
        return self._start_step(pending_step, timestamp)

    def _generate(
        self,
        *,
        session_id: str,
        run_id: str,
        conversation: tuple[ModelMessage, ...],
        log_context: dict[str, str],
        force_history_compaction: bool = False,
    ) -> ModelResponse:
        logger.info("开始模型调用。", extra=log_context)
        system_prompt = self._request_system_prompt()
        tools = self._registry.list_definitions()
        snapshot = ContextInputSnapshot(
            session_id=session_id,
            run_id=run_id,
            messages=conversation,
            tools=tools,
            system_prompt=system_prompt,
        )
        try:
            response = self._model.generate(
                self._build_model_request(
                    snapshot,
                    force_history_compaction=force_history_compaction,
                )
            )
        except ModelContextWindowExceededError:
            if self._context_manager is None:
                logger.error("模型上下文超限，且未配置应急压缩。", exc_info=True, extra=log_context)
                raise
            logger.warning("模型上下文超限，开始一次应急压缩并重试。", extra=log_context)
            try:
                response = self._model.generate(
                    self._build_model_request(
                        snapshot,
                        force_history_compaction=True,
                    )
                )
            except Exception:
                logger.error("模型上下文超限后的应急重试失败。", exc_info=True, extra=log_context)
                raise
        except Exception:
            logger.error("模型调用失败。", exc_info=True, extra=log_context)
            raise
        logger.info("模型调用完成。", extra=log_context)
        return response

    def _build_model_request(
        self,
        snapshot: ContextInputSnapshot,
        *,
        force_history_compaction: bool = False,
    ) -> ModelRequest:
        """仅从完整内存历史派生 Provider 请求，避免重试污染 Conversation Transcript。"""

        messages = snapshot.messages
        tools = snapshot.tools
        system_prompt = snapshot.system_prompt
        if self._context_manager is not None:
            context_package = self._context_manager.prepare(
                snapshot,
                force_history_compaction=force_history_compaction,
            )
            messages = context_package.snapshot.messages
            tools = context_package.snapshot.tools
            system_prompt = context_package.snapshot.system_prompt
        return ModelRequest.from_messages(
            session_id=snapshot.session_id,
            run_id=snapshot.run_id,
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
        )

    def _requested_context_compaction(
        self,
        tool_blocks: tuple[ToolUseBlock, ...],
        tool_results: tuple[ToolResultBlock, ...],
    ) -> bool:
        """只接受成功的本地控制工具结果，避免失败或伪造调用触发上下文变更。"""

        for block, result in zip(tool_blocks, tool_results, strict=True):
            if result.is_error:
                continue
            try:
                tool = self._registry.get(block.name)
            except ToolNotFoundError:
                continue
            if CONTEXT_COMPACTION_TOOL_TAG in tool.definition.tags:
                return True
        return False

    def _request_system_prompt(self) -> str | None:
        """合并稳定系统提示与一次性待办提醒，不写入会话消息。"""

        reminder = (
            self._todo_reminder_policy.consume_reminder()
            if self._todo_reminder_policy is not None
            else None
        )
        prompt_parts = tuple(
            prompt for prompt in (self._system_prompt, reminder) if prompt is not None
        )
        return "\n\n".join(prompt_parts) if prompt_parts else None

    def _record_todo_tool_turn(
        self,
        tool_blocks: tuple[ToolUseBlock, ...],
        tool_results: tuple[ToolResultBlock, ...],
    ) -> None:
        """仅在成功执行 todo_write 后重置提醒计数。"""

        if self._todo_reminder_policy is None:
            return
        todo_updated = any(
            block.name == "todo_write" and not result.is_error
            for block, result in zip(tool_blocks, tool_results, strict=True)
        )
        self._todo_reminder_policy.record_tool_turn(todo_updated=todo_updated)

    def _execute_tools(
        self,
        *,
        session_id: str,
        run_id: str,
        tool_blocks: tuple[ToolUseBlock, ...],
        timestamp: datetime,
        log_context: dict[str, str],
    ) -> tuple[tuple[ToolResultBlock, ...], tuple[StepState, ...]]:
        tool_results: list[ToolResultBlock] = []
        tool_steps: list[StepState] = []
        for block in tool_blocks:
            tool_step = self._create_and_start_step(
                run_id=run_id,
                step_type=self._tool_step_type(block.name),
                timestamp=timestamp,
            )
            logger.info(
                "开始工具调用。",
                extra={**log_context, "step_id": tool_step.step_id},
            )
            request = ToolCallRequest(
                name=block.name,
                arguments=block.input,
                call_id=block.tool_use_id,
            )
            result = self._executor.execute(
                request,
                context=ToolExecutionContext(
                    session_id=session_id,
                    run_id=run_id,
                    step_id=tool_step.step_id,
                    call_id=request.call_id,
                ),
            )
            tool_steps.append(self._finish_tool_step(tool_step, result, timestamp))
            tool_results.append(self._to_tool_result_block(block, result))
        return tuple(tool_results), tuple(tool_steps)

    def _tool_step_type(self, tool_name: str) -> StepType:
        """按本地工具标签区分普通工具与委派步骤，未知工具仍按普通调用记录。"""

        try:
            tool = self._registry.get(tool_name)
        except ToolNotFoundError:
            return StepType.TOOL
        if DELEGATION_TOOL_TAG in tool.definition.tags:
            return StepType.DELEGATE
        return StepType.TOOL

    def _finish_tool_step(
        self,
        step: StepState,
        result: ToolCallResult,
        timestamp: datetime,
    ) -> StepState:
        target_status = StepStatus.SUCCEEDED if result.success else StepStatus.FAILED
        reason = None if result.success else "工具调用返回失败结果。"
        completed_step = step.transition_to(
            target_status,
            reason=reason,
            occurred_at=timestamp,
        )
        self._repository.save_step(completed_step)
        return completed_step

    def _succeed_step(self, step: StepState, timestamp: datetime) -> StepState:
        succeeded_step = step.transition_to(StepStatus.SUCCEEDED, occurred_at=timestamp)
        self._repository.save_step(succeeded_step)
        return succeeded_step

    @staticmethod
    def _to_tool_result_block(
        block: ToolUseBlock,
        result: ToolCallResult,
    ) -> ToolResultBlock:
        if result.success:
            return ToolResultBlock(
                tool_use_id=block.tool_use_id,
                content=dict(result.data or {}),
            )
        return ToolResultBlock(
            tool_use_id=block.tool_use_id,
            content={"error": dict(result.error or {})},
            is_error=True,
        )
