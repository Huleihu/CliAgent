import pytest

from local_dev_agent.models.fake import FakeModel
from local_dev_agent.models.ports import ModelRequest, ModelResponse


def test_fake_model_returns_its_configured_response_and_records_requests() -> None:
    configured_response = ModelResponse.text_completion("已完成任务。")
    model = FakeModel(configured_response)
    request = ModelRequest(
        session_id="session-1",
        run_id="run-1",
        user_input="检查项目状态。",
    )

    response = model.generate(request)

    assert response is configured_response
    assert model.requests == (request,)


def test_text_completion_rejects_an_empty_text_block() -> None:
    with pytest.raises(ValueError, match="文本块不能为空"):
        ModelResponse.text_completion("")
