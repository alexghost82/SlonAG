"""In-process Desktop Control route handlers.

Wire these from ``server.app`` later; handlers accept injected principals
and stores and do not open listening sockets.
"""

from server.routes._common import DevicePrincipal, IdempotencyStore, RouteResponse
from server.routes.approvals import ApprovalsHandler, ApprovalStore
from server.routes.chat import ChatHandler, post_chat
from server.routes.files import FilesHandler
from server.routes.memory import MemoryHandler, MemoryStore, RuntimeMemoryStore
from server.routes.models import ModelsHandler, ModelStore
from server.routes.screen import ScreenHandler
from server.routes.status import get_status, health_check
from server.routes.tasks import TasksHandler, TaskStore

__all__ = [
    "ApprovalStore",
    "ApprovalsHandler",
    "ChatHandler",
    "DevicePrincipal",
    "FilesHandler",
    "IdempotencyStore",
    "MemoryHandler",
    "MemoryStore",
    "RuntimeMemoryStore",
    "ModelStore",
    "ModelsHandler",
    "RouteResponse",
    "ScreenHandler",
    "TaskStore",
    "TasksHandler",
    "get_status",
    "health_check",
    "post_chat",
]
