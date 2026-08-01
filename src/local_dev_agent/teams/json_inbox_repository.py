"""带进程内锁和原子替换的 Team 收件箱 JSON 仓储。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from .errors import CorruptedTeamFileError, TeamMessageIdempotencyConflictError
from .json_codec import decode_inbox, encode_inbox
from .json_support import read_json_object, require_safe_identifier, write_json_atomically
from .schema import (
    InboxReservation,
    TeamMessage,
    TeamMessageDeliveryStatus,
    TeamMessageDraft,
)

_LOCK_REGISTRY_GUARD = Lock()
_INBOX_LOCKS: dict[str, Lock] = {}


class JsonFileTeamInboxRepository:
    """每个 Team/接收方使用一个完整 JSON 快照保存有序收件箱。"""

    def __init__(self, root_directory: Path) -> None:
        if not isinstance(root_directory, Path):
            raise TypeError("Team 收件箱仓储根目录必须是 Path 对象。")
        self._root_directory = root_directory

    def send(self, draft: TeamMessageDraft) -> TeamMessage:
        """在接收方锁内检查幂等键、分配下一个 sequence 并原子写回。"""

        if not isinstance(draft, TeamMessageDraft):
            raise TypeError("Team 收件箱只能发送 TeamMessageDraft 对象。")
        path = self._path_for(draft.team_id, draft.recipient_member_id)
        with self._lock_for(path):
            next_sequence, messages = self._load(path)
            existing = next(
                (
                    message
                    for message in messages
                    if message.idempotency_key == draft.idempotency_key
                ),
                None,
            )
            if existing is not None:
                if _same_delivery(existing, draft):
                    return existing
                raise TeamMessageIdempotencyConflictError(
                    idempotency_key=draft.idempotency_key
                )
            message = TeamMessage.create(
                message_id=draft.message_id,
                team_id=draft.team_id,
                sender_member_id=draft.sender_member_id,
                recipient_member_id=draft.recipient_member_id,
                sequence=next_sequence,
                message_type=draft.message_type,
                content=draft.content,
                idempotency_key=draft.idempotency_key,
                created_at=draft.created_at,
            )
            self._save(path, next_sequence=next_sequence + 1, messages=(*messages, message))
            return message

    def list_unread(
        self,
        *,
        team_id: str,
        recipient_member_id: str,
    ) -> tuple[TeamMessage, ...]:
        """返回未读消息快照，不改变其投递状态。"""

        path = self._path_for(team_id, recipient_member_id)
        with self._lock_for(path):
            _, messages = self._load(path)
            return tuple(
                message
                for message in messages
                if message.delivery_status is TeamMessageDeliveryStatus.UNREAD
            )

    def reserve_unread(
        self,
        *,
        team_id: str,
        recipient_member_id: str,
        reservation_id: str,
        reserved_at: datetime,
        limit: int,
    ) -> InboxReservation | None:
        """原子预留最早的一批未读消息，防止同进程 worker 重复取得它们。"""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("字段“limit”必须是正整数。")
        path = self._path_for(team_id, recipient_member_id)
        with self._lock_for(path):
            next_sequence, messages = self._load(path)
            selected = tuple(
                message
                for message in messages
                if message.delivery_status is TeamMessageDeliveryStatus.UNREAD
            )[:limit]
            if not selected:
                return None
            selected_ids = {message.message_id for message in selected}
            reserved_messages = tuple(
                message.reserve(reservation_id=reservation_id, occurred_at=reserved_at)
                if message.message_id in selected_ids
                else message
                for message in messages
            )
            self._save(path, next_sequence=next_sequence, messages=reserved_messages)
            reservation_messages = tuple(
                message for message in reserved_messages if message.message_id in selected_ids
            )
            return InboxReservation(
                team_id=team_id,
                recipient_member_id=recipient_member_id,
                reservation_id=reservation_id,
                messages=reservation_messages,
                reserved_at=reserved_at,
            )

    def acknowledge(
        self,
        reservation: InboxReservation,
        *,
        consumer_session_id: str,
        consumer_run_id: str,
        consumed_at: datetime,
    ) -> tuple[TeamMessage, ...]:
        """确认整批预留消息，拒绝缺失或被其他预留抢占的消息。"""

        if not isinstance(reservation, InboxReservation):
            raise TypeError("reservation 必须是 InboxReservation 对象。")
        path = self._path_for(reservation.team_id, reservation.recipient_member_id)
        with self._lock_for(path):
            next_sequence, messages = self._load(path)
            reservation_ids = {message.message_id for message in reservation.messages}
            current_by_id = {message.message_id: message for message in messages}
            if set(current_by_id).intersection(reservation_ids) != reservation_ids:
                raise ValueError("预留消息不完整，不能确认消费。")
            consumed_messages = tuple(
                message.consume(
                    reservation_id=reservation.reservation_id,
                    session_id=consumer_session_id,
                    run_id=consumer_run_id,
                    occurred_at=consumed_at,
                )
                if message.message_id in reservation_ids
                else message
                for message in messages
            )
            self._save(path, next_sequence=next_sequence, messages=consumed_messages)
            return tuple(
                message for message in consumed_messages if message.message_id in reservation_ids
            )

    def release(self, reservation: InboxReservation) -> tuple[TeamMessage, ...]:
        """释放整批预留消息，使失败 Run 的输入可以被后续 worker 重投。"""

        if not isinstance(reservation, InboxReservation):
            raise TypeError("reservation 必须是 InboxReservation 对象。")
        path = self._path_for(reservation.team_id, reservation.recipient_member_id)
        with self._lock_for(path):
            next_sequence, messages = self._load(path)
            reservation_ids = {message.message_id for message in reservation.messages}
            current_by_id = {message.message_id: message for message in messages}
            if set(current_by_id).intersection(reservation_ids) != reservation_ids:
                raise ValueError("预留消息不完整，不能释放预留。")
            if any(
                current_by_id[message_id].reservation_id != reservation.reservation_id
                for message_id in reservation_ids
            ):
                raise ValueError("预留消息不属于当前 reservation，不能释放预留。")
            released_messages = tuple(
                message.release() if message.message_id in reservation_ids else message
                for message in messages
            )
            self._save(path, next_sequence=next_sequence, messages=released_messages)
            return tuple(
                message for message in released_messages if message.message_id in reservation_ids
            )

    def recover_reserved(self, *, team_id: str) -> tuple[TeamMessage, ...]:
        """进程启动恢复时释放该 Team 全部遗留预留消息，不创建或执行 Run。"""

        safe_team_id = require_safe_identifier("team_id", team_id)
        inbox_directory = self._root_directory / safe_team_id / "inboxes"
        if not inbox_directory.exists():
            return ()
        recovered: list[TeamMessage] = []
        for path in sorted(inbox_directory.glob("*.json")):
            with self._lock_for(path):
                next_sequence, messages = self._load(path)
                reserved_ids = {
                    message.message_id
                    for message in messages
                    if message.delivery_status is TeamMessageDeliveryStatus.RESERVED
                }
                if not reserved_ids:
                    continue
                restored = tuple(
                    message.release()
                    if message.delivery_status is TeamMessageDeliveryStatus.RESERVED
                    else message
                    for message in messages
                )
                self._save(path, next_sequence=next_sequence, messages=restored)
                recovered.extend(
                    message
                    for message in restored
                    if message.message_id in reserved_ids
                )
        return tuple(sorted(recovered, key=lambda message: (message.created_at, message.message_id)))

    def _path_for(self, team_id: str, recipient_member_id: str) -> Path:
        return (
            self._root_directory
            / require_safe_identifier("team_id", team_id)
            / "inboxes"
            / f"{require_safe_identifier('recipient_member_id', recipient_member_id)}.json"
        )

    @staticmethod
    def _lock_for(path: Path) -> Lock:
        key = str(path.resolve())
        with _LOCK_REGISTRY_GUARD:
            return _INBOX_LOCKS.setdefault(key, Lock())

    @staticmethod
    def _load(path: Path) -> tuple[int, tuple[TeamMessage, ...]]:
        if not path.exists():
            return 1, ()
        try:
            return decode_inbox(read_json_object(path))
        except (OSError, ValueError) as error:
            raise CorruptedTeamFileError(path=path) from error

    @staticmethod
    def _save(
        path: Path,
        *,
        next_sequence: int,
        messages: tuple[TeamMessage, ...],
    ) -> None:
        write_json_atomically(path, encode_inbox(next_sequence=next_sequence, messages=messages))


def _same_delivery(message: TeamMessage, draft: TeamMessageDraft) -> bool:
    """相同幂等键只允许重放完全相同的投递事实。"""

    return (
        message.message_id == draft.message_id
        and message.team_id == draft.team_id
        and message.sender_member_id == draft.sender_member_id
        and message.recipient_member_id == draft.recipient_member_id
        and message.message_type is draft.message_type
        and message.content == draft.content
        and message.created_at == draft.created_at
    )
