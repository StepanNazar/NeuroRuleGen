"""Repository layer for AI configuration."""

from abc import ABC, abstractmethod

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from neurorulegen.ai_configuration.models import (
    AgentSkill,
    AIModel,
    AIProvider,
    MCPServer,
    ProjectProviderCredential,
)
from neurorulegen.project_management.models import Project


class AIConfigurationRepository(ABC):
    @abstractmethod
    async def get_provider_by_name(self, name: str) -> AIProvider | None:
        pass

    @abstractmethod
    async def get_or_create_provider(self, name: str) -> AIProvider:
        pass

    @abstractmethod
    async def get_models_for_provider(self, provider_id: int) -> list[AIModel]:
        pass

    @abstractmethod
    async def get_or_create_model(
        self, provider_id: int, model_identifier: str
    ) -> AIModel:
        pass

    @abstractmethod
    async def get_project_credentials(
        self, project_id: int
    ) -> list[ProjectProviderCredential]:
        pass

    @abstractmethod
    async def get_credential(
        self, project_id: int, provider_id: int
    ) -> ProjectProviderCredential | None:
        pass

    @abstractmethod
    async def upsert_credential(
        self,
        project_id: int,
        provider_id: int,
        api_key_encrypted: bytes,
        config_encrypted: bytes | None = None,
    ) -> ProjectProviderCredential:
        pass

    @abstractmethod
    async def get_mcp_servers(self, project_id: int) -> list[MCPServer]:
        pass

    @abstractmethod
    async def sync_mcp_servers(
        self, project_id: int, servers: list[MCPServer]
    ) -> list[MCPServer]:
        pass

    @abstractmethod
    async def get_agent_skills(self, project_id: int) -> list[AgentSkill]:
        pass

    @abstractmethod
    async def get_agent_skill(
        self, project_id: int, skill_id: int
    ) -> AgentSkill | None:
        pass

    @abstractmethod
    async def create_agent_skill(
        self, project_id: int, name: str, description: str, content: str
    ) -> AgentSkill:
        pass

    @abstractmethod
    def update_agent_skill(
        self,
        skill: AgentSkill,
        name: str,
        description: str,
        content: str,
    ) -> None:
        pass

    @abstractmethod
    def toggle_agent_skill(self, skill: AgentSkill) -> bool:
        pass

    @abstractmethod
    async def get_project(self, project_id: int) -> Project | None:
        pass

    @abstractmethod
    def update_project_additional_system_prompt(
        self, project: Project, prompt: str | None
    ) -> None:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass


class SQLAlchemyAIConfigurationRepository(AIConfigurationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_provider_by_name(self, name: str) -> AIProvider | None:
        stmt = (
            select(AIProvider)
            .options(selectinload(AIProvider.models))
            .where(AIProvider.name == name)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_provider(self, name: str) -> AIProvider:
        provider = await self.get_provider_by_name(name)
        if provider:
            return provider
        provider = AIProvider(name=name)
        self._session.add(provider)
        await self._session.flush()
        return provider

    async def get_models_for_provider(self, provider_id: int) -> list[AIModel]:
        stmt = select(AIModel).where(AIModel.provider_id == provider_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create_model(
        self, provider_id: int, model_identifier: str
    ) -> AIModel:
        stmt = select(AIModel).where(
            AIModel.provider_id == provider_id,
            AIModel.model_identifier == model_identifier,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            return model
        model = AIModel(provider_id=provider_id, model_identifier=model_identifier)
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_project_credentials(
        self, project_id: int
    ) -> list[ProjectProviderCredential]:
        stmt = (
            select(ProjectProviderCredential)
            .options(selectinload(ProjectProviderCredential.provider))
            .where(ProjectProviderCredential.project_id == project_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_credential(
        self, project_id: int, provider_id: int
    ) -> ProjectProviderCredential | None:
        stmt = select(ProjectProviderCredential).where(
            ProjectProviderCredential.project_id == project_id,
            ProjectProviderCredential.provider_id == provider_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_credential(
        self,
        project_id: int,
        provider_id: int,
        api_key_encrypted: bytes,
        config_encrypted: bytes | None = None,
    ) -> ProjectProviderCredential:
        cred = await self.get_credential(project_id, provider_id)
        if cred:
            cred.api_key_encrypted = api_key_encrypted
            if config_encrypted is not None:
                cred.config_encrypted = config_encrypted
        else:
            cred = ProjectProviderCredential(
                project_id=project_id,
                provider_id=provider_id,
                api_key_encrypted=api_key_encrypted,
                config_encrypted=config_encrypted,
            )
            self._session.add(cred)
            await self._session.flush()
        return cred

    async def get_mcp_servers(self, project_id: int) -> list[MCPServer]:
        stmt = select(MCPServer).where(MCPServer.project_id == project_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def sync_mcp_servers(
        self, project_id: int, servers: list[MCPServer]
    ) -> list[MCPServer]:
        existing_servers = await self.get_mcp_servers(project_id)
        existing_by_name = {s.name: s for s in existing_servers}
        new_names = {s.name for s in servers}

        # Remove servers not in incoming payload
        to_delete = [
            name for name in existing_by_name if name not in new_names
        ]
        if to_delete:
            stmt = delete(MCPServer).where(
                MCPServer.project_id == project_id, MCPServer.name.in_(to_delete)
            )
            await self._session.execute(stmt)

        # Update or insert
        for server in servers:
            if server.name in existing_by_name:
                curr = existing_by_name[server.name]
                curr.transport = server.transport
                curr.url = server.url
                curr.connection_config_encrypted = server.connection_config_encrypted
                curr.enabled = server.enabled
            else:
                self._session.add(server)

        await self._session.flush()
        return await self.get_mcp_servers(project_id)

    async def get_agent_skills(self, project_id: int) -> list[AgentSkill]:
        stmt = (
            select(AgentSkill)
            .where(AgentSkill.project_id == project_id)
            .order_by(AgentSkill.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_agent_skill(
        self, project_id: int, skill_id: int
    ) -> AgentSkill | None:
        stmt = select(AgentSkill).where(
            AgentSkill.project_id == project_id, AgentSkill.id == skill_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_agent_skill(
        self, project_id: int, name: str, description: str, content: str
    ) -> AgentSkill:
        skill = AgentSkill(
            project_id=project_id,
            name=name,
            description=description,
            content=content,
            enabled=True,
        )
        self._session.add(skill)
        await self._session.flush()
        return skill

    def update_agent_skill(
        self,
        skill: AgentSkill,
        name: str,
        description: str,
        content: str,
    ) -> None:
        skill.name = name
        skill.description = description
        skill.content = content

    def toggle_agent_skill(self, skill: AgentSkill) -> bool:
        skill.enabled = not skill.enabled
        return skill.enabled

    async def get_project(self, project_id: int) -> Project | None:
        stmt = select(Project).where(Project.id == project_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def update_project_additional_system_prompt(
        self, project: Project, prompt: str | None
    ) -> None:
        project.additional_system_prompt = prompt

    async def commit(self) -> None:
        await self._session.commit()
