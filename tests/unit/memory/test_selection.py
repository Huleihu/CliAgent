"""长期记忆选择策略的单元测试。"""

from local_dev_agent.memory import (
    KeywordMemorySelector,
    MemoryCatalog,
    MemoryEntry,
    MemorySelectionRequest,
    MemoryType,
    ModelMemorySelector,
)
from local_dev_agent.models import FakeModel, ModelResponse


def _catalog() -> MemoryCatalog:
    return MemoryCatalog(
        entries=(
            MemoryEntry("feedback-no-mocks", MemoryType.FEEDBACK, "不要 mock 数据库", "正文"),
            MemoryEntry("project-auth", MemoryType.PROJECT, "认证重构由合规驱动", "正文"),
            MemoryEntry("user-tabs", MemoryType.USER, "使用 tab 缩进", "正文"),
        )
    )


def _request(query: str = "认证重构的合规要求") -> MemorySelectionRequest:
    return MemorySelectionRequest(
        session_id="session-1",
        run_id="run-1",
        query=query,
        catalog=_catalog(),
    )


def test_keyword_selector_returns_stable_relevant_ids() -> None:
    assert KeywordMemorySelector().select(_request()) == ("project-auth",)


def test_model_selector_uses_tool_free_request_and_filters_unknown_ids() -> None:
    model = FakeModel(ModelResponse.text_completion('["user-tabs", "unknown", "user-tabs"]'))

    selected = ModelMemorySelector(model).select(_request("如何设置缩进"))

    assert selected == ("user-tabs",)
    request = model.requests[0]
    assert request.tools == ()
    assert request.system_prompt is not None


def test_model_selector_falls_back_when_response_is_not_json() -> None:
    model = FakeModel(ModelResponse.text_completion("不能提供 JSON"))

    assert ModelMemorySelector(model).select(_request()) == ("project-auth",)
