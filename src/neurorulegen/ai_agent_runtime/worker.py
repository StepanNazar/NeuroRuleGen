"""Background Analysis Worker process: polls pending analyses, fetches PR from GitHub, runs agent, and tracks tokens."""

import asyncio
import logging
import multiprocessing
import traceback
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from neurorulegen.ai_agent_runtime.agent import build_pr_analysis_agent
from neurorulegen.ai_configuration.repository import (
    SQLAlchemyAIConfigurationRepository,
)
from neurorulegen.analysis_management.models import AIAnalysis, RunStatus
from neurorulegen.analysis_management.repository import (
    SQLAlchemyAIAnalysisRepository,
    SQLAlchemyAIFindingRepository,
)
from neurorulegen.common.config import get_settings
from neurorulegen.common.db import create_database
from neurorulegen.github_integration.services import GitHubClient

logger = logging.getLogger("ai_analysis_worker")


class AnalysisWorker:
    def __init__(self, stop_event) -> None:
        self.stop_event = stop_event
        self.settings = get_settings()

    async def run(self) -> None:
        engine, sessionmaker = create_database()
        logger.info("Background Analysis Worker starting...")

        try:
            # Recover any tasks left RUNNING from a prior crash/restart
            try:
                async with sessionmaker() as session:
                    repo = SQLAlchemyAIAnalysisRepository(session)
                    recovered = await repo.recover_stale_running()
                    if recovered > 0:
                        logger.info(f"Recovered {recovered} stale RUNNING tasks.")
            except Exception as e:
                logger.error(f"Error recovering stale tasks: {e}")

            # AsyncPostgresSaver.from_conn_string is an async context manager
            async with AsyncPostgresSaver.from_conn_string(self.settings.postgres_dsn) as checkpointer:
                await checkpointer.setup()
                github_client = GitHubClient()

                while not self.stop_event.is_set():
                    try:
                        task: AIAnalysis | None = None
                        # Short session 1: Claim next pending task
                        async with sessionmaker() as session:
                            analysis_repo = SQLAlchemyAIAnalysisRepository(session)
                            task = await analysis_repo.claim_next_pending()

                        if task is not None:
                            await self.process_analysis(
                                task=task,
                                sessionmaker=sessionmaker,
                                checkpointer=checkpointer,
                                github_client=github_client,
                            )
                    except Exception as e:
                        logger.error(f"Error in analysis worker poll loop: {e}\n{traceback.format_exc()}")

                    # Sleep 1 second checking stop_event
                    for _ in range(10):
                        if self.stop_event.is_set():
                            break
                        await asyncio.sleep(0.1)

        finally:
            await engine.dispose()
            logger.info("Background Analysis Worker gracefully stopped.")

    async def process_analysis(
        self,
        task: AIAnalysis,
        sessionmaker: Any,
        checkpointer: AsyncPostgresSaver,
        github_client: GitHubClient,
    ) -> None:
        project_id = task.pull_request.project_id
        pr_number = task.pull_request.github_pr_number
        repo_url = task.pull_request.project.github_repo_url

        mcp_client = None
        try:
            # 1. Fetch PR details and diff
            pr_data = await github_client.get_pull_request(repo_url, pr_number)
            base_sha = pr_data.get("base", {}).get("sha", "")
            head_sha = pr_data.get("head", {}).get("sha", "")

            diff_text = task.diff
            if not diff_text:
                diff_text = await github_client.get_pull_request_diff(repo_url, pr_number)

            # 2. Fetch changed files content (skipping deleted files)
            pr_files = await github_client.get_pull_request_files(repo_url, pr_number)
            project_files: dict[str, str] = {}
            for f in pr_files:
                filename = f.get("filename")
                status = f.get("status", "")
                if not filename or status == "removed":
                    continue
                try:
                    ref = base_sha if status == "deleted" else head_sha
                    content = await github_client.get_file_content(repo_url, filename, ref=ref)
                    project_files[filename] = content
                except Exception as ex:
                    logger.warning(f"Could not fetch file {filename} at ref: {ex}")

            # 3. Short session 2: Load credentials, MCP, and Skills
            async with sessionmaker() as session:
                ai_config_repo = SQLAlchemyAIConfigurationRepository(session)
                cred = await ai_config_repo.get_credential(project_id, task.model.provider_id)
                if not cred:
                    raise ValueError(f"Provider credentials missing for provider #{task.model.provider_id}.")

                all_mcps = await ai_config_repo.get_mcp_servers(project_id)
                mcp_config = {
                    s.name: {
                        "transport": s.transport.value,
                        "url": s.url,
                        "headers": s.connection_config_decrypted.get("headers", {}),
                    }
                    for s in all_mcps
                    if s.enabled
                }
                all_skills = await ai_config_repo.get_agent_skills(project_id)
                skills_files = {s.name: s.content for s in all_skills if s.enabled}

                api_key = cred.api_key_decrypted
                prov_config = cred.config_decrypted or {}

            # Callback for saving findings immediately to database in isolated sessions
            async def on_finding(finding_dict: dict[str, Any]) -> None:
                try:
                    async with sessionmaker() as f_session:
                        f_repo = SQLAlchemyAIFindingRepository(f_session)
                        await f_repo.create(
                            ai_analysis_id=task.id,
                            description=finding_dict["description"],
                            file_path=finding_dict["file_path"],
                            diff_side=finding_dict["diff_side"],
                            start_line=finding_dict["start_line"],
                            end_line=finding_dict["end_line"],
                        )
                        await f_session.commit()
                except Exception as f_err:
                    logger.error(f"Failed to persist finding in DB: {f_err}")

            agent, token_handler, mcp_client = await build_pr_analysis_agent(
                model_name=task.model.model_identifier,
                provider_name=task.model.provider.name,
                api_key=api_key,
                provider_config=prov_config,
                system_prompt=task.system_prompt,
                mcp_servers_config=mcp_config,
                skills_files=skills_files,
                project_files=project_files,
                checkpointer=checkpointer,
                on_finding=on_finding,
            )

            # 4. Invoke agent (handling US-24 forking if source checkpoint is provided)
            input_message = (
                f"Analyze the following Pull Request code diff for Python quality issues and security:\n\n{diff_text}"
            )
            if task.continuation_instruction:
                input_message += f"\n\nAdditional instruction: {task.continuation_instruction}"

            if task.source_checkpoint_id:
                source_config = {
                    "configurable": {
                        "thread_id": task.langgraph_thread_id,
                        "checkpoint_id": task.source_checkpoint_id,
                    },
                    "callbacks": [token_handler],
                }
                if task.source_checkpoint_ns is not None:
                    source_config["configurable"]["checkpoint_ns"] = task.source_checkpoint_ns

                fork_config = await agent.aupdate_state(
                    source_config,
                    {"messages": [HumanMessage(content=input_message)]},
                )
                await agent.ainvoke(None, fork_config)
            else:
                config = {
                    "configurable": {
                        "thread_id": task.langgraph_thread_id,
                    },
                    "callbacks": [token_handler],
                }
                await agent.ainvoke({"messages": [HumanMessage(content=input_message)]}, config=config)

            run_status = RunStatus.COMPLETED
            error_msg = None

        except Exception as ex:
            logger.error(f"Analysis task #{task.id} execution failed: {ex}\n{traceback.format_exc()}")
            run_status = RunStatus.FAILED
            error_msg = str(ex)

        finally:
            if mcp_client and hasattr(mcp_client, "close"):
                try:
                    await mcp_client.close()
                except Exception:
                    pass

        # 5. Short session 3: Safely persist token metrics, metadata, and status
        try:
            usage_by_model = token_handler.usage_metadata or {}
            input_tokens = sum(u.get("input_tokens", 0) for u in usage_by_model.values())
            output_tokens = sum(u.get("output_tokens", 0) for u in usage_by_model.values())
            cached_tokens = sum(
                u.get("input_token_details", {}).get("cache_read", 0) or u.get("cached_input_tokens", 0)
                for u in usage_by_model.values()
            )

            async with sessionmaker() as session:
                analysis_repo = SQLAlchemyAIAnalysisRepository(session)
                await analysis_repo.update_token_usage(
                    analysis_id=task.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_tokens,
                )
                await analysis_repo.update_status_and_metadata(
                    analysis_id=task.id,
                    status=run_status,
                    error_message=error_msg,
                    diff=diff_text if "diff_text" in locals() else None,
                    base_commit_hash=base_sha if "base_sha" in locals() else None,
                    head_commit_hash=head_sha if "head_sha" in locals() else None,
                )
        except Exception as fin_err:
            logger.error(f"Failed to record final status for task #{task.id}: {fin_err}")


def worker_process_main(stop_event) -> None:
    """Entry point for the separate OS worker process."""
    worker = AnalysisWorker(stop_event=stop_event)
    asyncio.run(worker.run())
