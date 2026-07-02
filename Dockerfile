# AgentCore Runtime container.
# ARM64 is required by Bedrock AgentCore Runtime.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

# Install the app + its dependencies from pyproject.toml (hatchling build backend).
COPY pyproject.toml ./
COPY apps ./apps
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir aws-opentelemetry-distro==0.10.1

# AgentCore requires a non-root runtime user.
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

# AgentCore serves POST /invocations and GET /ping on port 8080.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping')" || exit 1

CMD ["opentelemetry-instrument", "python", "-m", "apps.agent"]
