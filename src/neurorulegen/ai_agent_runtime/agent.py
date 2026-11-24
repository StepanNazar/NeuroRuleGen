"""LangGraph / DeepAgents agent setup, checkpointer, and tools for PR analysis."""

import inspect
from typing import Any, Callable

from deepagents.backends import StoreBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain.agents import create_agent
from langgraph.store.memory import InMemoryStore

from neurorulegen.ai_configuration.providers import AIProviderRegistry
from neurorulegen.analysis_management.models import DiffSide


def create_record_finding_tool(on_finding: Callable[[dict[str, Any]], Any]):
    @tool
    async def record_finding(
        file_path: str,
        diff_side: str,
        start_line: int,
        end_line: int,
        description: str,
    ) -> str:
        """
        Record a detected code quality, security or architectural issue.
        Args:
            file_path: The relative path of the file containing the issue (e.g. 'src/service.py').
            diff_side: 'LEFT' (old/deleted code) or 'RIGHT' (new/added code).
            start_line: Starting line number (1-based integer).
            end_line: Ending line number (1-based integer, >= start_line).
            description: Concise and clear explanation of the defect, vulnerability, or violation.
        """
        side = DiffSide.RIGHT if diff_side.upper() == "RIGHT" else DiffSide.LEFT
        data = {
            "file_path": file_path,
            "diff_side": side,
            "start_line": int(start_line),
            "end_line": int(end_line),
            "description": description.strip(),
        }
        res = on_finding(data)
        if inspect.isawaitable(res):
            await res
        return f"Finding successfully recorded for {file_path}:{start_line}-{end_line}."

    return record_finding


async def build_pr_analysis_agent(
    model_name: str,
    provider_name: str,
    api_key: str,
    provider_config: dict[str, Any],
    system_prompt: str,
    mcp_servers_config: dict[str, Any],
    skills_files: dict[str, str],
    project_files: dict[str, str],
    checkpointer: AsyncPostgresSaver,
    on_finding: Callable[[dict[str, Any]], Any],
) -> tuple[Any, UsageMetadataCallbackHandler, MultiServerMCPClient | None]:
    """
    Construct the agent with MCP tools, filesystem middleware, skills, and checkpointer.
    """
    llm = AIProviderRegistry.create_chat_model(
        provider_name=provider_name,
        model_identifier=model_name,
        api_key=api_key,
        config=provider_config,
    )

    tools = [create_record_finding_tool(on_finding)]
    mcp_client = None

    if mcp_servers_config:
        try:
            mcp_client = MultiServerMCPClient(mcp_servers_config)
            mcp_tools = await mcp_client.get_tools()
            tools.extend(mcp_tools)
        except Exception:
            pass

    store = InMemoryStore()

    for path, content in project_files.items():
        clean_path = "/" + path.lstrip("/")
        store.put(("files",), clean_path, create_file_data(content))

    for skill_name, content in skills_files.items():
        store.put(("files",), f"/skills/{skill_name}/SKILL.md", create_file_data(content))

    files_backend = StoreBackend(store=store, namespace=lambda _: ("files",))
    middleware = [
        SkillsMiddleware(
            backend=files_backend,
            sources=["/skills/"],
        ),
        FilesystemMiddleware(backend=files_backend),
    ]
    callback_handler = UsageMetadataCallbackHandler()

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        store=store,
        middleware=middleware,
    )

    return agent, callback_handler, mcp_client
