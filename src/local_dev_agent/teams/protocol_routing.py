"""将单条协议 dispatch 结果汇总为 Runner 可执行的收件箱批次路由计划。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .ports import TeamProtocolMessageDispatcher
from .protocol_dispatch import (
    TeamProtocolDispatchDisposition,
    TeamProtocolDispatchResult,
)
from .schema import TeamMessage


@dataclass(frozen=True, slots=True)
class TeamProtocolBatchRoute:
    """同一预留批次中哪些消息交给 Agent、由协议系统确认或留待释放。"""

    results: tuple[TeamProtocolDispatchResult, ...]
    messages_for_agent: tuple[TeamMessage, ...]
    messages_for_system: tuple[TeamMessage, ...]
    remaining_messages: tuple[TeamMessage, ...]
    should_stop_member: bool

    def __post_init__(self) -> None:
        """防止一个消息同时属于多个后续消费分支。"""

        if not all(isinstance(result, TeamProtocolDispatchResult) for result in self.results):
            raise TypeError("results 只能包含 TeamProtocolDispatchResult。")
        message_groups = (
            self.messages_for_agent,
            self.messages_for_system,
            self.remaining_messages,
        )
        if not all(
            isinstance(messages, tuple)
            and all(isinstance(message, TeamMessage) for message in messages)
            for messages in message_groups
        ):
            raise TypeError("批次路由中的消息必须是 TeamMessage 元组。")
        message_ids = tuple(
            message.message_id for messages in message_groups for message in messages
        )
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("同一收件箱消息不能同时属于多个协议路由分支。")
        if not isinstance(self.should_stop_member, bool):
            raise ValueError("字段“should_stop_member”必须是布尔值。")

    @property
    def failures(self) -> tuple[TeamProtocolDispatchResult, ...]:
        """返回已由系统确认消费、但需要记录诊断日志的协议失败。"""

        return tuple(
            result
            for result in self.results
            if result.disposition is TeamProtocolDispatchDisposition.FAILED
        )


class TeamProtocolInboxRouter:
    """将有序收件箱消息交给协议分派器，并在关闭请求后保留后续消息。"""

    def __init__(self, *, dispatcher: TeamProtocolMessageDispatcher) -> None:
        if not callable(getattr(dispatcher, "dispatch", None)):
            raise TypeError("dispatcher 必须提供 dispatch 方法。")
        self._dispatcher = dispatcher

    def route(self, messages: Iterable[TeamMessage]) -> TeamProtocolBatchRoute:
        """按顺序分派消息；shutdown 后的未处理消息交还 Runner 释放，避免越过停止边界。"""

        ordered_messages = tuple(messages)
        if not all(isinstance(message, TeamMessage) for message in ordered_messages):
            raise TypeError("messages 只能包含 TeamMessage。")
        results: list[TeamProtocolDispatchResult] = []
        messages_for_agent: list[TeamMessage] = []
        messages_for_system: list[TeamMessage] = []
        for index, message in enumerate(ordered_messages):
            result = self._dispatcher.dispatch(message)
            results.append(result)
            if result.should_forward_to_agent:
                messages_for_agent.append(message)
                continue
            messages_for_system.append(message)
            if result.disposition is TeamProtocolDispatchDisposition.STOP_MEMBER:
                return TeamProtocolBatchRoute(
                    results=tuple(results),
                    messages_for_agent=tuple(messages_for_agent),
                    messages_for_system=tuple(messages_for_system),
                    remaining_messages=ordered_messages[index + 1 :],
                    should_stop_member=True,
                )
        return TeamProtocolBatchRoute(
            results=tuple(results),
            messages_for_agent=tuple(messages_for_agent),
            messages_for_system=tuple(messages_for_system),
            remaining_messages=(),
            should_stop_member=False,
        )
