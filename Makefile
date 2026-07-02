.PHONY: help sync lint fmt fmt-check typecheck test check run invoke eval eval-quality docker-build tf-validate

help:
	@echo "Targets:"
	@echo "  sync          uv sync"
	@echo "  lint          ruff check (autofix-safe)"
	@echo "  fmt           ruff format (write)"
	@echo "  fmt-check     ruff format --check"
	@echo "  typecheck     pyright apps tests evals"
	@echo "  test          pytest smoke tests"
	@echo "  check         lint + fmt-check + typecheck + test (offline, no Bedrock)"
	@echo "  run           run local AgentCore app (apps/agent.py); starts the in-process Slack thread"
	@echo "  invoke        invoke deployed AgentCore runtime via boto3 client"
	@echo "  eval          deterministic routing/behaviour CI gate (needs AWS Bedrock)"
	@echo "  eval-quality  LLM-as-judge helpfulness eval on read responses (needs AWS Bedrock)"
	@echo "  docker-build  build the ARM64 runtime image (override IMAGE=...)"
	@echo "  tf-validate   terraform validate in terraform/"

sync:
	uv sync

lint:
	uv run ruff check .

fmt:
	uv run ruff format .
	uv run ruff check . --fix

fmt-check:
	uv run ruff format --check .

typecheck:
	uv run pyright apps tests evals

test:
	uv run pytest -q

check: lint fmt-check typecheck test

run:
	uv run python apps/agent.py

eval:
	SLACK_SOCKET_MODE_INPROCESS=0 uv run python -m evals.routing_eval

eval-quality:
	SLACK_SOCKET_MODE_INPROCESS=0 uv run python -m evals.quality_eval

invoke:
	uv run python apps/client.py --help

IMAGE ?= sandbox-agentcore:latest

docker-build:
	docker build --platform linux/arm64 -t $(IMAGE) .

tf-validate:
	terraform -chdir=terraform init -backend=false
	terraform -chdir=terraform validate
