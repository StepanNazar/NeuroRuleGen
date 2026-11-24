"""Services for analysis management: PR analysis requests, forks, results, and token monitoring."""

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from typing import Any
import uuid

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from neurorulegen.common.config import get_settings

from neurorulegen.ai_configuration.models import AIModel
from neurorulegen.ai_configuration.repository import (
    AIConfigurationRepository,
)
from neurorulegen.analysis_management.models import (
    AIAnalysis,
    AIFinding,
    DiffSide,
    PullRequest,
    PullRequestState,
)
from neurorulegen.analysis_management.repository import (
    AIAnalysisRepository,
    AIFindingRepository,
    PullRequestRepository,
)
from neurorulegen.common.enums import RunStatus
from neurorulegen.project_management.repository import (
    ProjectRepository,
)


def _message_field(message: Any, field: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(field, default)
    return getattr(message, field, default)


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        if content is None:
            return []
        return [{"type": "text", "text": str(content)}]

    blocks: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            blocks.append({"type": "text", "text": block})
        elif isinstance(block, dict):
            blocks.append(block)
        else:
            block_type = getattr(block, "type", "non_standard")
            blocks.append(
                {
                    "type": str(block_type),
                    "data": getattr(block, "data", None),
                    "text": getattr(block, "text", None),
                }
            )
    return blocks


def _parse_tool_arguments(arguments: Any) -> Any:
    if not isinstance(arguments, str):
        return _json_safe(arguments)
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def _normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for call in value:
        if isinstance(call, dict):
            arguments = call.get(
                "args",
                call.get(
                    "arguments",
                    call.get("function", {}).get("arguments", {}),
                ),
            )
            normalized.append({
                "name": call.get("name") or call.get("function", {}).get("name") or "unknown",
                "arguments": _parse_tool_arguments(arguments),
                "id": call.get("id"),
            })
        else:
            normalized.append({
                "name": getattr(call, "name", "unknown"),
                "arguments": _parse_tool_arguments(
                    getattr(call, "args", getattr(call, "arguments", {}))
                ),
                "id": _json_safe(getattr(call, "id", None)),
            })
    return normalized


def _tool_call_key(call: dict[str, Any]) -> tuple[str, str]:
    return call["name"], _safe_json(call["arguments"])


def _extract_message(message: Any) -> dict[str, Any]:
    message_type = _message_field(message, "type", "")
    role_map = {"human": "User", "ai": "AI Assistant", "tool": "Tool Result", "system": "System"}
    role = role_map.get(str(message_type), str(message_type).title() or "Message")

    content = _message_field(message, "content", "")
    blocks = _json_safe(_content_blocks(content))

    tool_calls = _normalize_tool_calls(_message_field(message, "tool_calls", []))
    invalid_tool_calls = _normalize_tool_calls(
        _message_field(message, "invalid_tool_calls", [])
    )
    display_blocks: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in {"tool_call", "server_tool_call", "function_call"}:
            call = {
                "name": (
                    block.get("name")
                    or (block.get("function") or {}).get("name")
                    or "unknown"
                ),
                "arguments": _parse_tool_arguments(
                    block.get(
                        "args",
                        block.get(
                            "arguments",
                            (block.get("function") or {}).get("arguments", {}),
                        ),
                    )
                ),
                "id": _json_safe(block.get("id")),
            }
            if not any(
                _tool_call_key(existing) == _tool_call_key(call)
                for existing in tool_calls
            ):
                tool_calls.append(call)
        elif block_type == "invalid_tool_call":
            invalid_tool_calls.append({
                "name": block.get("name") or "unknown",
                "arguments": _json_safe(
                    block.get("args", block.get("arguments", {}))
                ),
                "id": _json_safe(block.get("id")),
            })
        else:
            display_blocks.append(block)
    blocks = display_blocks

    additional_kwargs = _message_field(message, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict) and additional_kwargs.get("function_call"):
        function_call = additional_kwargs["function_call"]
        call = {
            "name": function_call.get("name") or "unknown",
            "arguments": _parse_tool_arguments(function_call.get("arguments", {})),
            "id": _json_safe(additional_kwargs.get("tool_call_id")),
        }
        if not any(
            _tool_call_key(existing) == _tool_call_key(call)
            for existing in tool_calls
        ):
            tool_calls.append(call)

    usage = _json_safe(_message_field(message, "usage_metadata", {}) or {})
    if not isinstance(usage, dict):
        usage = {}

    response_metadata = _json_safe(
        _message_field(message, "response_metadata", {}) or {}
    )
    if not isinstance(response_metadata, dict):
        response_metadata = {}

    return {
        "role": role,
        "message_id": _json_safe(_message_field(message, "id")),
        "name": _json_safe(_message_field(message, "name")),
        "tool_call_id": _json_safe(_message_field(message, "tool_call_id")),
        "status": _json_safe(_message_field(message, "status")),
        "blocks": blocks,
        "tool_calls": tool_calls,
        "invalid_tool_calls": invalid_tool_calls,
        "usage": usage,
        "response_metadata": response_metadata,
    }


def _message_identity(message: dict[str, Any]) -> str:
    return _safe_json(message)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "dict"):
        return _json_safe(value.dict())
    if hasattr(value, "content"):
        return {
            "type": _message_field(value, "type", value.__class__.__name__),
            "content": _json_safe(_message_field(value, "content", "")),
            "name": _json_safe(_message_field(value, "name")),
            "id": _json_safe(_message_field(value, "id")),
            "tool_call_id": _json_safe(_message_field(value, "tool_call_id")),
            "status": _json_safe(_message_field(value, "status")),
        }
    return str(value)


class AnalysisError(Exception):
    """Base exception for analysis management errors."""


class AnalysisPermissionDeniedError(AnalysisError):
    """User does not have permission to view or run analyses."""


class AnalysisNotFoundError(AnalysisError):
    """Analysis or PR not found."""


class ModelNotConfiguredError(AnalysisError):
    """Credentials not configured for the chosen AI model."""


class AnalysisManagementService:
    def __init__(
        self,
        analysis_repo: AIAnalysisRepository,
        pr_repo: PullRequestRepository,
        finding_repo: AIFindingRepository,
        project_repo: ProjectRepository,
        ai_config_repo: AIConfigurationRepository,
    ) -> None:
        self.analysis_repo = analysis_repo
        self.pr_repo = pr_repo
        self.finding_repo = finding_repo
        self.project_repo = project_repo
        self.ai_config_repo = ai_config_repo

    async def _verify_project_member(self, project_id: int, user_id: int) -> None:
        project = await self.project_repo.get_project_by_id(project_id)
        if not project:
            raise AnalysisNotFoundError(f"Project #{project_id} not found.")
        is_member = await self.project_repo.is_user_project_member(project_id, user_id)
        if not is_member:
            raise AnalysisPermissionDeniedError("User is not a member of this project.")

    async def _verify_quality_engineer(self, project_id: int, user_id: int) -> None:
        project = await self.project_repo.get_project_by_id(project_id)
        if not project:
            raise AnalysisNotFoundError(f"Project #{project_id} not found.")
        if project.created_by_user_id != user_id:
            raise AnalysisPermissionDeniedError(
                "Only the Quality/Security Engineer can access token usage reports."
            )

    async def compute_config_hashes(self, project_id: int) -> tuple[bytes, bytes]:
        all_mcps = await self.ai_config_repo.get_mcp_servers(project_id)
        active_mcps = [s for s in all_mcps if s.enabled]
        all_skills = await self.ai_config_repo.get_agent_skills(project_id)
        active_skills = [s for s in all_skills if s.enabled]

        mcp_data = sorted(
            [
                {
                    "name": s.name,
                    "url": s.url,
                    "transport": s.transport.value,
                    "connection_config": s.connection_config_encrypted.hex(),
                }
                for s in active_mcps
            ],
            key=lambda x: x["name"],
        )
        skills_data = sorted(
            [{"name": s.name, "content": s.content} for s in active_skills],
            key=lambda x: x["name"],
        )

        mcp_hash = hashlib.sha256(json.dumps(mcp_data, sort_keys=True).encode()).digest()
        skills_hash = hashlib.sha256(json.dumps(skills_data, sort_keys=True).encode()).digest()
        return mcp_hash, skills_hash

    async def get_available_models(self, project_id: int) -> list[dict[str, Any]]:
        """Return AI models for which the project has valid provider credentials."""
        creds = await self.ai_config_repo.get_project_credentials(project_id)
        models_out: list[dict[str, Any]] = []
        for c in creds:
            provider_models = await self.ai_config_repo.get_models_for_provider(c.provider_id)
            for m in provider_models:
                models_out.append({
                    "id": m.id,
                    "name": m.model_identifier,
                    "provider": c.provider.name,
                    "provider_id": c.provider_id,
                })
        return models_out

    async def list_project_analyses(
        self,
        project_id: int,
        user_id: int,
        offset: int = 0,
        limit: int = 10,
    ) -> Sequence[AIAnalysis]:
        await self._verify_project_member(project_id, user_id)
        return await self.analysis_repo.list_by_project(
            project_id=project_id,
            offset=offset,
            limit=limit,
        )

    async def count_project_analyses(
        self,
        project_id: int,
        user_id: int,
    ) -> int:
        await self._verify_project_member(project_id, user_id)
        return await self.analysis_repo.count_by_project(project_id)

    async def get_analysis_config_snapshot(
        self,
        project_id: int,
    ) -> tuple[list[str], list[str]]:
        mcps = await self.ai_config_repo.get_mcp_servers(project_id)
        skills = await self.ai_config_repo.get_agent_skills(project_id)
        return (
            [server.name for server in mcps if server.enabled],
            [skill.name for skill in skills if skill.enabled],
        )

    async def get_checkpoint_timeline(
        self,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        checkpoints: list[dict[str, Any]] = []
        async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn) as saver:
            await saver.setup()
            config = {"configurable": {"thread_id": thread_id}}
            async for checkpoint_tuple in saver.alist(config, limit=100):
                checkpoint = checkpoint_tuple.checkpoint
                metadata = checkpoint_tuple.metadata or {}
                channel_values = checkpoint.get("channel_values", {}) or {}
                messages = channel_values.get("messages", [])
                snapshot_messages = (
                    [_extract_message(message) for message in messages]
                    if isinstance(messages, list)
                    else []
                )
                snapshot_ids = [
                    _message_identity(message) for message in snapshot_messages
                ]

                pending_writes: list[dict[str, Any]] = []
                for write_index, pending_write in enumerate(
                    checkpoint_tuple.pending_writes or [], start=1
                ):
                    if isinstance(pending_write, (tuple, list)) and len(pending_write) >= 3:
                        task_id, channel, value = pending_write[:3]
                    else:
                        task_id, channel, value = None, "unknown", pending_write
                    value = _json_safe(value)
                    pending_writes.append({
                        "index": write_index,
                        "task_id": str(task_id) if task_id is not None else None,
                        "channel": str(channel),
                        "value": value,
                    })

                checkpoints.append({
                    "checkpoint_id": checkpoint_tuple.config["configurable"]["checkpoint_id"],
                    "timestamp": checkpoint.get("ts", ""),
                    "step": metadata.get("step"),
                    "source": metadata.get("source", ""),
                    "run_id": metadata.get("run_id"),
                    "parents": metadata.get("parents", {}) or {},
                    "snapshot_messages": snapshot_messages,
                    "snapshot_ids": snapshot_ids,
                    "pending_writes": pending_writes,
                    "updated_channels": sorted(checkpoint.get("updated_channels", []) or []),
                    "channel_count": len(checkpoint.get("channel_versions", {}) or {}),
                })

        checkpoints.reverse()
        previous_message_ids: list[str] = []
        formatted_checkpoints: list[dict[str, Any]] = []
        for item in checkpoints:
            snapshot_ids = item["snapshot_ids"]
            common_prefix = 0
            for old_id, new_id in zip(previous_message_ids, snapshot_ids, strict=False):
                if old_id != new_id:
                    break
                common_prefix += 1

            new_messages = item["snapshot_messages"][common_prefix:]
            previous_message_ids = snapshot_ids
            formatted_checkpoints.append({
                "id": len(formatted_checkpoints) + 1,
                "checkpoint_id": item["checkpoint_id"],
                "title": f"Checkpoint {len(formatted_checkpoints) + 1}",
                "description": (
                    f"{item['source']} step"
                    if item["source"]
                    else "LangGraph checkpoint"
                ),
                "data": "\n".join(
                    [
                        f"Checkpoint ID: {item['checkpoint_id']}",
                        f"Timestamp: {item['timestamp'] or '—'}",
                        f"Step: {item['step'] if item['step'] is not None else '—'}",
                        f"Run ID: {item['run_id'] or '—'}",
                        f"Updated channels: {', '.join(item['updated_channels']) or '—'}",
                        f"Channel count: {item['channel_count']}",
                        f"Pending writes: {len(item['pending_writes'])}",
                        f"Parents: {_safe_json(item['parents'])}",
                    ]
                ),
                "messages": new_messages,
                "pending_writes": item["pending_writes"],
                "branches": [],
            })

        return formatted_checkpoints

    async def request_pr_analysis(
        self,
        project_id: int,
        user_id: int,
        pr_number: int,
        model_id: int,
        additional_instruction: str = "",
    ) -> AIAnalysis:
        """US-16: Request an AI Pull Request analysis."""
        await self._verify_project_member(project_id, user_id)

        # Verify model has credentials
        creds = await self.ai_config_repo.get_project_credentials(project_id)
        configured_provider_ids = {c.provider_id for c in creds}

        # Check model exists
        available = await self.get_available_models(project_id)
        chosen = next((m for m in available if m["id"] == model_id), None)
        if not chosen:
            raise ModelNotConfiguredError(
                f"Provider credentials for model ID #{model_id} are not configured in this project."
            )

        # Get or create PullRequest record
        pr = await self.pr_repo.get_or_create(
            project_id=project_id,
            github_pr_number=pr_number,
            title=f"Pull Request #{pr_number}",
            state=PullRequestState.OPEN,
        )

        project = await self.project_repo.get_project_by_id(project_id)
        base_prompt = "Review Python code quality, security vulnerabilities, and adherence to clean architecture."
        system_prompt = (
            f"{base_prompt}\n\nProject Additional Instructions:\n{project.additional_system_prompt or ''}\n\nUser Instruction:\n{additional_instruction}".strip()
        )

        mcp_hash, skills_hash = await self.compute_config_hashes(project_id)
        thread_id = f"analysis-{uuid.uuid4().hex}"

        analysis = await self.analysis_repo.create(
            pull_request_id=pr.id,
            started_by_user_id=user_id,
            model_id=model_id,
            base_commit_hash="",  # Populated by worker on fetch
            head_commit_hash="",  # Populated by worker on fetch
            system_prompt=system_prompt,
            langgraph_thread_id=thread_id,
            mcp_config_hash=mcp_hash,
            skills_config_hash=skills_hash,
            status=RunStatus.PENDING,
            continuation_instruction=additional_instruction or None,
        )
        await self.analysis_repo.commit()
        return analysis

    async def create_fork(
        self,
        project_id: int,
        user_id: int,
        source_analysis_id: int,
        checkpoint_id: str,
        checkpoint_ns: str = "",
        instruction: str = "",
    ) -> tuple[AIAnalysis, bool]:
        """US-24: Fork an analysis from a checkpoint. Returns (new_analysis, config_has_drifted)."""
        await self._verify_project_member(project_id, user_id)
        source = await self.analysis_repo.get_by_id(source_analysis_id)
        if not source:
            raise AnalysisNotFoundError(f"Source analysis #{source_analysis_id} not found.")

        current_mcp_hash, current_skills_hash = await self.compute_config_hashes(project_id)
        config_has_drifted = (
            source.mcp_config_hash != current_mcp_hash
            or source.skills_config_hash != current_skills_hash
        )

        # Reuse same thread for checkpoint lineage or dedicated branch thread
        new_thread_id = source.langgraph_thread_id

        fork_analysis = await self.analysis_repo.create(
            pull_request_id=source.pull_request_id,
            started_by_user_id=user_id,
            model_id=source.model_id,
            base_commit_hash=source.base_commit_hash,
            head_commit_hash=source.head_commit_hash,
            system_prompt=source.system_prompt,
            langgraph_thread_id=new_thread_id,
            mcp_config_hash=current_mcp_hash,
            skills_config_hash=current_skills_hash,
            status=RunStatus.PENDING,
            source_analysis_id=source.id,
            source_checkpoint_ns=checkpoint_ns,
            source_checkpoint_id=checkpoint_id,
            continuation_instruction=instruction,
            diff=source.diff,
        )
        await self.analysis_repo.commit()
        return fork_analysis, config_has_drifted

    async def get_analysis_result(
        self, project_id: int, user_id: int, analysis_id: int
    ) -> tuple[AIAnalysis, Sequence[AIFinding]]:
        """US-17: View code analysis result and findings."""
        await self._verify_project_member(project_id, user_id)
        analysis = await self.analysis_repo.get_with_findings(analysis_id)
        if not analysis:
            raise AnalysisNotFoundError(f"Analysis #{analysis_id} not found.")
        return analysis, analysis.findings

    async def get_token_usage_report(
        self,
        project_id: int,
        user_id: int,
        model_name: str,
        user_email: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        group_by: str | None = None,
    ) -> dict[str, Any]:
        """US-25: Token usage monitoring for Quality/Security Engineer."""
        await self._verify_quality_engineer(project_id, user_id)

        first = date.fromisoformat(start_date) if start_date else None
        last = date.fromisoformat(end_date) if end_date else None

        records = await self.analysis_repo.get_token_usage_records(
            project_id=project_id,
            model_name=model_name,
            user_email=user_email if user_email else None,
            start_date=first,
            end_date=last,
        )

        period = bool(first and last and first <= last)
        valid_group = group_by if period and group_by in ("day", "month") else ""

        grouped: dict[str, list[int]] = {}
        for record in records:
            r_date: date = record["date"]
            if valid_group == "month":
                key = r_date.isoformat()[:7]
            elif valid_group == "day":
                key = r_date.isoformat()
            else:
                key = "summary"

            grouped.setdefault(key, [0] * 5)
            grouped[key] = [
                a + b for a, b in zip(grouped[key], record["metrics"], strict=True)
            ]

        return {
            "model": model_name,
            "user": user_email or "",
            "start": start_date or "",
            "end": end_date or "",
            "group": valid_group,
            "metrics": [
                "Total input",
                "Total input cache read",
                "Total input short-term cache write",
                "Total input longer-term cache write",
                "Total output",
            ],
            "grouped": grouped,
        }
