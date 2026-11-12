"""
order_agent_a2a.py
An A2A agent server. It speaks A2A 1.0 and, on the same endpoint, the older 0.3 wire format.
The layout matches the Amazon Bedrock AgentCore Runtime A2A contract: 0.0.0.0:9000,
JSON-RPC on "/", the agent card on /.well-known/agent-card.json and a /ping health route.
"""
import logging
import os

import uvicorn
from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from order_agent import answer

# The address callers use. On AgentCore Runtime this is the runtime's invocation URL, not localhost.
log = logging.getLogger("order_agent")
PUBLIC_URL = os.environ.get("AGENT_PUBLIC_URL", "http://localhost:9000/")

AGENT_CARD = AgentCard(
    name="Order Status Agent",
    description="Answers questions about the fulfilment status of customer orders.",
    version="1.0.0",
    supported_interfaces=[
        # Listed in order of preference. Clients take the first entry they can speak.
        AgentInterface(url=PUBLIC_URL, protocol_binding="JSONRPC", protocol_version="1.0"),
        AgentInterface(url=PUBLIC_URL, protocol_binding="JSONRPC", protocol_version="0.3"),
    ],
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="order_status",
            name="Order status",
            description="Looks up where an order is, given an order number such as ORD-10042.",
            tags=["orders", "fulfilment"],
            examples=["Where is order ORD-10042?"],
        )
    ],
)


class OrderStatusExecutor(AgentExecutor):
    """Bridges A2A requests to the business logic and reports progress as task events."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task is None:
            # First message of a conversation: the task must exist before any status event refers to it.
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        task = TaskUpdater(event_queue, context.task_id, context.context_id)
        await task.start_work()
        try:
            text = await answer(context.get_user_input())
        except Exception:
            # Log the cause here; tell the caller only that the task failed.
            log.exception("order lookup failed task_id=%s", context.task_id)
            await task.failed()
            return
        await task.add_artifact([new_text_part(text)], name="order_status")
        await task.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


async def ping(_request) -> JSONResponse:
    return JSONResponse({"status": "Healthy"})


def build_app() -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=OrderStatusExecutor(),
        task_store=InMemoryTaskStore(),      # per-process; use a database-backed store beyond one instance
        agent_card=AGENT_CARD,
    )
    return Starlette(routes=[
        Route("/ping", ping),
        *create_agent_card_routes(AGENT_CARD),
        *create_jsonrpc_routes(handler, rpc_url="/", enable_v0_3_compat=True),
    ])


if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=9000)
