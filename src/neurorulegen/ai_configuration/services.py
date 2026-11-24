"""Service layer for AI configuration, credentials, MCP servers and agent skills."""

import json
import re
from typing import Any

from neurorulegen.ai_configuration.models import (
    AgentSkill,
    MCPServer,
    MCPTransport,
    ProjectProviderCredential,
)
from neurorulegen.ai_configuration.repository import AIConfigurationRepository


class AIConfigurationError(Exception):
    """Base exception for AI configuration domain errors."""


class AIConfigurationPermissionError(AIConfigurationError):
    """Raised when a user lacks Quality/Security Engineer permissions."""


class AIConfigurationNotFoundError(AIConfigurationError):
    """Raised when an entity is not found."""


class AIConfigurationValidationError(AIConfigurationError):
    """Raised when validation fails."""


class AIConfigurationService:
    def __init__(
        self,
        repository: AIConfigurationRepository,
    ) -> None:
        self.repository = repository

    def _extract_skill_metadata(self, content: str) -> tuple[str, str]:
        """Extract name and description from YAML frontmatter if present."""
        match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            # Fallback: take first non-empty lines as description
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            desc = lines[0] if lines else "Agent skill"
            return "", desc[:255]

        frontmatter = match.group(1)
        name = ""
        description = ""
        for line in frontmatter.splitlines():
            line = line.strip()
            if line.startswith("name:"):
                name = line.split("name:", 1)[1].strip().strip("\"'")
            elif line.startswith("description:"):
                description = line.split("description:", 1)[1].strip().strip("\"'")

        return name, description or "Agent skill"

    async def _assert_project_engineer(self, project_id: int, user_id: int) -> None:
        project = await self.repository.get_project(project_id)
        if not project:
            raise AIConfigurationNotFoundError("Project not found.")
        if project.created_by_user_id != user_id:
            raise AIConfigurationPermissionError(
                "Only Quality/Security Engineer can manage AI configuration."
            )

    async def get_project_settings(
        self, project_id: int, user_id: int
    ) -> dict[str, Any]:
        """Fetch project AI configuration, MCP config, and provider status."""
        project = await self.repository.get_project(project_id)
        if not project:
            raise AIConfigurationNotFoundError("Project not found.")

        # Skills
        skills = await self.repository.get_agent_skills(project_id)

        # MCP servers to JSON
        mcp_servers = await self.repository.get_mcp_servers(project_id)
        mcp_dict: dict[str, Any] = {"mcpServers": {}}
        for server in mcp_servers:
            conn_cfg: dict[str, Any] = {}
            if server.connection_config_encrypted:
                try:
                    conn_cfg = json.loads(server.connection_config_encrypted.decode("utf-8"))
                except Exception:
                    conn_cfg = {}
            mcp_dict["mcpServers"][server.name] = {
                "transport": server.transport.value,
                "url": server.url,
                **conn_cfg,
            }

        # Azure AI Foundry credential status
        provider = await self.repository.get_provider_by_name("azure_ai_foundry")
        endpoint_val = ""
        has_api_key = False
        if provider:
            cred = await self.repository.get_credential(project_id, provider.id)
            if cred:
                has_api_key = bool(cred.api_key_encrypted)
                if cred.config_encrypted:
                    try:
                        cfg = json.loads(cred.config_encrypted.decode("utf-8"))
                        endpoint_val = cfg.get("endpoint", "")
                    except Exception:
                        endpoint_val = ""

        return {
            "additional_system_prompt": project.additional_system_prompt or "",
            "mcp_json": json.dumps(mcp_dict, indent=2),
            "azure_endpoint": endpoint_val,
            "has_azure_api_key": has_api_key,
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "content": s.content,
                    "enabled": s.enabled,
                }
                for s in skills
            ],
        }

    async def save_prompt_and_mcp(
        self,
        project_id: int,
        user_id: int,
        prompt: str,
        mcp_json_str: str,
    ) -> None:
        await self._assert_project_engineer(project_id, user_id)
        project = await self.repository.get_project(project_id)
        if not project:
            raise AIConfigurationNotFoundError("Project not found.")

        # Update additional system prompt
        self.repository.update_project_additional_system_prompt(
            project, prompt.strip() if prompt else None
        )

        # Parse and sync MCP servers
        clean_mcp = mcp_json_str.strip() or '{"mcpServers": {}}'
        try:
            parsed = json.loads(clean_mcp)
        except json.JSONDecodeError as e:
            raise AIConfigurationValidationError(
                f"Invalid JSON for MCP configuration: {e}"
            ) from e

        servers_dict = parsed.get("mcpServers", {})
        if not isinstance(servers_dict, dict):
            raise AIConfigurationValidationError(
                "MCP configuration must contain an 'mcpServers' object."
            )

        servers_to_sync: list[MCPServer] = []
        for name, cfg in servers_dict.items():
            clean_name = str(name).strip()
            if not clean_name:
                continue
            if not isinstance(cfg, dict):
                raise AIConfigurationValidationError(
                    f"Configuration for MCP server '{name}' must be an object."
                )

            transport_str = cfg.get("transport", "http").lower()
            if transport_str in ("http", "streamable_http", "streamable-http"):
                transport = MCPTransport.HTTP
            elif transport_str == "sse":
                transport = MCPTransport.SSE
            else:
                raise AIConfigurationValidationError(
                    f"Unsupported MCP transport '{transport_str}' for server '{name}'."
                )

            url = cfg.get("url", "").strip()
            if not url:
                raise AIConfigurationValidationError(
                    f"MCP server '{name}' is missing a 'url'."
                )

            # Store any extra configuration (headers, secrets) in connection_config_encrypted
            extra_cfg = {
                k: v for k, v in cfg.items() if k not in ("transport", "url")
            }
            conn_bytes = json.dumps(extra_cfg).encode("utf-8")

            servers_to_sync.append(
                MCPServer(
                    project_id=project_id,
                    name=clean_name,
                    transport=transport,
                    url=url,
                    connection_config_encrypted=conn_bytes,
                    enabled=True,
                )
            )

        await self.repository.sync_mcp_servers(project_id, servers_to_sync)
        await self.repository.commit()

    async def save_azure_foundry_credentials(
        self,
        project_id: int,
        user_id: int,
        endpoint: str,
        api_key: str | None = None,
    ) -> ProjectProviderCredential:
        await self._assert_project_engineer(project_id, user_id)

        clean_endpoint = endpoint.strip()
        if not clean_endpoint:
            raise AIConfigurationValidationError("Azure Endpoint URL cannot be empty.")

        provider = await self.repository.get_or_create_provider("azure_ai_foundry")
        existing_cred = await self.repository.get_credential(project_id, provider.id)

        if not api_key and not existing_cred:
            raise AIConfigurationValidationError(
                "API key is required for initial Azure AI Foundry configuration."
            )

        api_key_bytes = (
            api_key.strip().encode("utf-8")
            if api_key and api_key.strip()
            else (existing_cred.api_key_encrypted if existing_cred else b"")
        )

        config_data = {"endpoint": clean_endpoint}
        config_bytes = json.dumps(config_data).encode("utf-8")

        cred = await self.repository.upsert_credential(
            project_id=project_id,
            provider_id=provider.id,
            api_key_encrypted=api_key_bytes,
            config_encrypted=config_bytes,
        )
        await self.repository.commit()
        return cred

    async def get_skill(
        self, project_id: int, skill_id: int, user_id: int
    ) -> AgentSkill:
        project = await self.repository.get_project(project_id)
        if not project:
            raise AIConfigurationNotFoundError("Project not found.")
        skill = await self.repository.get_agent_skill(project_id, skill_id)
        if not skill:
            raise AIConfigurationNotFoundError("Skill not found.")
        return skill

    async def create_skill(
        self, project_id: int, user_id: int, name: str, content: str
    ) -> AgentSkill:
        await self._assert_project_engineer(project_id, user_id)
        clean_name = name.strip()
        if not clean_name:
            raise AIConfigurationValidationError("Skill name cannot be empty.")
        if not content.strip():
            raise AIConfigurationValidationError("Skill content cannot be empty.")

        _, desc = self._extract_skill_metadata(content)

        skill = await self.repository.create_agent_skill(
            project_id=project_id,
            name=clean_name,
            description=desc,
            content=content,
        )
        await self.repository.commit()
        return skill

    async def update_skill(
        self, project_id: int, skill_id: int, user_id: int, name: str, content: str
    ) -> AgentSkill:
        await self._assert_project_engineer(project_id, user_id)
        clean_name = name.strip()
        if not clean_name:
            raise AIConfigurationValidationError("Skill name cannot be empty.")
        if not content.strip():
            raise AIConfigurationValidationError("Skill content cannot be empty.")

        skill = await self.repository.get_agent_skill(project_id, skill_id)
        if not skill:
            raise AIConfigurationNotFoundError("Skill not found.")

        _, desc = self._extract_skill_metadata(content)
        self.repository.update_agent_skill(
            skill=skill,
            name=clean_name,
            description=desc,
            content=content,
        )
        await self.repository.commit()
        return skill

    async def toggle_skill(
        self, project_id: int, skill_id: int, user_id: int
    ) -> dict[str, Any]:
        await self._assert_project_engineer(project_id, user_id)
        skill = await self.repository.get_agent_skill(project_id, skill_id)
        if not skill:
            raise AIConfigurationNotFoundError("Skill not found.")

        new_status = self.repository.toggle_agent_skill(skill)
        await self.repository.commit()
        return {"id": skill.id, "enabled": new_status, "name": skill.name}
