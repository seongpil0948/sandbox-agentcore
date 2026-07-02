import boto3
import json
import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-runtime-arn", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--region", default="us-east-1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if len(args.session_id) < 33:
        raise ValueError("--session-id must be at least 33 characters")
    client = boto3.client("bedrock-agentcore", region_name=args.region)
    payload = json.dumps({"prompt": args.prompt}).encode("utf-8")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=args.agent_runtime_arn,
        runtimeSessionId=args.session_id,
        payload=payload,
    )
    output = response["response"].read().decode("utf-8")
    print(output)


if __name__ == "__main__":
    main()
