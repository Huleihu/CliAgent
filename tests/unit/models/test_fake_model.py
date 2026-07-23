import pytest

from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import ModelRequest


def test_fake_model_returns_its_configured_response_and_records_requests() -> None:
    model = FakeModel("已完成任务。")
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="检查项目状态。",
    )

    response = model.generate(request)

    assert response.text == "已完成任务。"
    assert model.requests == (request,)


def test_fake_model_rejects_an_empty_response() -> None:
    with pytest.raises(ValueError, match="响应文本不能为空"):
        FakeModel("")
