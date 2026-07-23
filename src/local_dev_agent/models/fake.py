"""用于确定性测试的内存 Fake Model。"""

from .ports import ModelRequest, ModelResponse


class FakeModel:
    """始终返回预设文本，并记录收到的请求以便断言。"""

    def __init__(self, response_text: str) -> None:
        if not response_text:
            raise ValueError("模拟模型的响应文本不能为空。")
        self._response_text = response_text
        self._requests: list[ModelRequest] = []

    @property
    def requests(self) -> tuple[ModelRequest, ...]:
        """返回不可被调用方修改的已接收请求快照。"""

        return tuple(self._requests)

    def generate(self, request: ModelRequest) -> ModelResponse:
        """记录请求并返回固定响应，不调用任何外部服务。"""

        self._requests.append(request)
        return ModelResponse(text=self._response_text)
