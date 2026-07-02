from __future__ import annotations

import json
import os
import uuid
from typing import Any

import boto3


def _extract_response_text(response: Any) -> str:
    content_type = response.get("contentType", "")
    payload = response.get("response")

    if "text/event-stream" in content_type and payload is not None:
        text_parts: list[str] = []
        for line in payload.iter_lines(chunk_size=10):
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                decoded = decoded[6:]
            text_parts.append(decoded)
        return "".join(text_parts)

    if content_type == "application/json" and payload is not None:
        content: list[str] = []
        for chunk in payload:
            if isinstance(chunk, (bytes, bytearray)):
                content.append(chunk.decode("utf-8"))
            else:
                content.append(str(chunk))
        return "".join(content)

    if payload is not None:
        return payload.read().decode("utf-8")

    return str(response)


def invoke_agent_runtime_text(agent_runtime_arn: str, prompt: str) -> str:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        raise EnvironmentError("AWS_REGION environment variable is required")

    client = boto3.client("bedrock-agentcore", region_name=region)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_runtime_arn,
        qualifier="DEFAULT",
        runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )
    return _extract_response_text(response)
