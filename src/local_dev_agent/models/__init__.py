"""模型调用端口与本地测试实现。"""

from .fake import FakeModel
from .ports import ModelClient, ModelRequest, ModelResponse

__all__ = ["FakeModel", "ModelClient", "ModelRequest", "ModelResponse"]
