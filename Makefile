.PHONY: gpu gpu-down gpu-logs up down

# Docker stacks read ONLY .env.docker (never the local dev .env), so developer
# secrets/paths can't leak into the containers. Created from the example on first run.
ENV_FILE := .env.docker

$(ENV_FILE):
	cp .env.docker.example $(ENV_FILE)

# Full GPU stack: Postgres + Redis + Wan2.2 download + migrate + API + worker + UI.
# Requires an NVIDIA GPU + nvidia-container-toolkit. See docs/DOCKER.md.
gpu: $(ENV_FILE)
	docker compose --env-file $(ENV_FILE) -f docker-compose.gpu.yml up --build

gpu-down:
	docker compose --env-file $(ENV_FILE) -f docker-compose.gpu.yml down

gpu-logs:
	docker compose --env-file $(ENV_FILE) -f docker-compose.gpu.yml logs -f backend worker

# CPU/stub stack (no GPU, no model download) — quick demo of the UI + API.
up: $(ENV_FILE)
	docker compose --env-file $(ENV_FILE) up --build

down:
	docker compose --env-file $(ENV_FILE) down
