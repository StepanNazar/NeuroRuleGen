.PHONY: frontend backend prod
frontend:
	npm run dev
backend:
	UI_DEV=1 uv run uvicorn neurorulegen.web_controllers.app:app --reload --host "$${APP_HOST:-127.0.0.1}" --port "$${APP_PORT:-8000}"
prod:
	npm run build
	UI_DEV=0 uv run uvicorn neurorulegen.web_controllers.app:app --host "$${APP_HOST:-127.0.0.1}" --port "$${APP_PORT:-8000}"
