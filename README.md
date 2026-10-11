# NeuroRuleGen

NeuroRuleGen is a system for analyzing Python code quality. It uses AI to review
GitHub pull requests and generate deterministic Python rules that can find similar
problems across a repository without further AI calls.

Project owners manage developers, rules, model credentials, MCP servers and agent
skills. The system keeps analysis history and token usage.

## Local setup

Run commands from the repository root:

```bash
uv sync
cp .env.example .env
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run uvicorn neurorulegen.web_controllers.app:app --reload
```

The database settings in `.env` are shared by PostgreSQL configuration and the
Python application. `POSTGRES_HOST` is `localhost` when Python runs on the host.
Local example credentials are provided in `.env.example`.

## Database migrations

After modifying models:

```bash
uv run alembic revision --autogenerate -m "Describe the schema change"
uv run alembic upgrade head
```

Review each generated migration before applying it. Models are registered when
their modules are imported. Add an import to `common/models.py` when introducing
a new model module; new classes inside an existing module are picked up automatically.
The initial migration enables PostgreSQL `citext` for case-insensitive emails.

## Structure

Application packages live in `src/neurorulegen/` and group code by responsibility:
authentication and authorization, project management, analysis management, rule
management, AI configuration, GitHub integration,
web controllers and user interface. Shared database configuration is in `common`.
`ai_agent_runtime` contains `rule_analysis_engine` and is reserved for a separate
background process. Migration files live in `alembic/`; standalone scripts live
in the root `scripts/` directory.
