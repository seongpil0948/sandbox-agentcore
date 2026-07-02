---
description: "Use when implementing or modifying Slack app code in sandbox-agentcore. Enforces official Slack Python SDK Socket Mode patterns, project env var conventions from .envrc, event/scopes setup, and secret-handling rules."
applyTo: "apps/**/*.py,tests/**/*.py,pyproject.toml,README.md,.envrc"
---
# Slack Python SDK Rules

Use these rules whenever code touches Slack integration in this repo. These rules are based on
`doc/slack-llms-full-python.txt` and the current project bridge in `apps/slack/socket_mode.py`.

## Project stance

- refer doc/slack-llms-full-python.txt
- Use the official `slack_sdk` package, not legacy `slackclient`/`slack` imports.
- Prefer the raw Python Slack SDK `SocketModeClient` for this sandbox.
- Keep Slack as a thin bridge to `apps.agent.run_prompt`; do not fork agent routing logic into Slack code.
- Keep the implementation synchronous unless the task explicitly asks for asyncio.
- For user-facing messages, prefer Block Kit `blocks` with a plain `text` fallback. Avoid sending
  long plain Markdown strings as the only message body.
- Normalize model Markdown before sending to Slack. Convert headings, bold markers, and bullets
  into Slack-compatible Block Kit/mrkdwn instead of wrapping raw model output in code blocks.

## Slack app setup checklist

For the current Socket Mode bridge, the Slack app should be configured with:

- App-level token with `connections:write` scope (`xapp-...`).
- Socket Mode enabled.
- Bot token installed to the workspace (`xoxb-...`).
- Event Subscriptions enabled.
- Interactivity enabled for Block Kit `block_actions`.
- Bot events:
  - `app_mention` for channel mentions.
  - `message.im` for direct messages.
- Bot scopes normally required by this repo:
  - `chat:write` to call `chat_postMessage`.
  - `app_mentions:read` for `app_mention`.
  - `im:history` for `message.im`.
- App Home messages tab enabled if DM/message-tab testing is expected.

Do not request broad scopes for examples. Add only the scope needed by the SDK method or event.

## Environment variable contract

Read Slack credentials only from environment variables. Never hardcode values.

Primary names in this repo:

- `SLACK_APP_SOCKET_TOKEN` for app-level token (`xapp-...`).
- `SLACK_BOT_USER_OAUTH_TOKEN` for bot token (`xoxb-...`).
- `SLACK_NOTIFICATION_CHANNEL_ID` for direct runtime-triggered notifications.
- `SLACK_SIGNING_SECRET` only when HTTP Request URL endpoints are added.

Compatibility aliases are allowed for sample interoperability:

- `SLACK_APP_TOKEN` as alias for `SLACK_APP_SOCKET_TOKEN`.
- `SLACK_BOT_TOKEN` as alias for `SLACK_BOT_USER_OAUTH_TOKEN`.
- `SLACK_ALERT_CHANNEL_ID` or `SLACK_CHANNEL_ID` as aliases for `SLACK_NOTIFICATION_CHANNEL_ID`.

When reading tokens in code, support the primary name first, then aliases.

## Socket Mode implementation requirements

- Use the built-in import unless a different transport is explicitly requested:
  - `from slack_sdk.socket_mode import SocketModeClient`
  - `from slack_sdk.web import WebClient`
- Initialize `SocketModeClient(app_token=..., web_client=WebClient(token=...))`.
- Use the app-level `xapp-...` token only for the Socket Mode connection.
- Use the bot `xoxb-...` token only for Web API calls.
- Register listeners with `client.socket_mode_request_listeners.append(handler)`.
- Acknowledge every envelope quickly with `SocketModeResponse(envelope_id=req.envelope_id)`.
- Ack before slow work. For heavier work, ack first, then dispatch or process.
- Keep the process alive intentionally after `client.connect()`; the current bridge uses `Event().wait()`.

## Event handling rules

- Handle only `events_api` envelopes unless the task explicitly adds interactivity or shortcuts.
- For this bridge, accept:
  - `app_mention`
  - `message` events with no `subtype`
- For interactive buttons, handle `interactive` envelopes with payload type `block_actions`.
- Ignore bot/subtype messages to avoid reply loops.
- Strip Slack mention tokens like `<@U123>` before forwarding text to `run_prompt`.
- Require `channel`, normalized text, and `ts` before replying.
- Reply in the same thread with `chat_postMessage(channel=..., thread_ts=event["ts"], text=..., blocks=...)`.
- When Slack events call `run_prompt`, pass `notify_slack=False` to avoid duplicate direct-runtime
  notifications.

## Block Kit and action workflow rules

- Build notification and action blocks in `apps/slack/workflows.py`, not inline inside handlers.
- Always include a plain `text` fallback for accessibility, mobile clients, and notifications.
- Use `section` with `mrkdwn` for formatted text; avoid Markdown tables because Slack does not
  render GitHub-style tables.
- Do not pass raw model output directly as `text` when it contains Markdown. Use a Slack-specific
  fallback string and Slack-specific `blocks`.
- Do not wrap whole model answers in triple-backtick code blocks unless the user explicitly asked
  for raw output.
- Use `actions` blocks for buttons, with stable `action_id` constants.
- Encode compact JSON in button `value`; include only non-secret workflow context.
- For certificate notices, use:
  - `갱신 실행`
  - `무시`
  - `상세 보기`
- For account create/update/delete notices, use operation-specific execute buttons plus:
  - `무시`
  - `상세 보기`
- Button handlers must:
  - ack the envelope first,
  - fetch or build detail information,
  - update the original message with HITL/interrupt state,
  - offer `승인 후 재개` and `취소`,
  - never perform real mutations without the explicit resume/approval button.
- Direct runtime invocations may post Slack notifications only when `SLACK_NOTIFICATION_CHANNEL_ID`
  and bot token env vars are configured.

## Web API usage conventions

- Prefer typed SDK methods such as `chat_postMessage`, `reactions_add`, `views_open`,
  `chat_update`, `conversations_list`, and `auth_test` over raw `api_call`.
- Use channel IDs, user IDs, and timestamps from Slack payloads; avoid hidden globals.
- Include `text` fallback whenever using blocks.
- Use `thread_ts` for conversational responses so channel mentions and DMs stay grouped.
- Verify bot identity with `auth_test()` during startup when useful for troubleshooting.

## Sync vs async

- Sync path: `SocketModeClient` + `WebClient` + normal functions.
- Async path: async Socket Mode client + `AsyncWebClient` + `async def` listeners.
- Do not mix sync clients with async listeners or async clients with sync SDK calls.
- Add async transport dependencies (`aiohttp`, `websockets`, or `websocket-client`) only when the chosen client requires them.

## Error handling and rate limits

- Catch `SlackApiError` around Web API calls.
- Log `exc.response.get("error", "unknown")`; do not log tokens or full auth headers.
- Treat `invalid_auth`, `not_in_channel`, `channel_not_found`, and missing scopes as setup issues.
- Do not add custom retry loops casually. Prefer SDK retry behavior unless the code has a clear need.
- If adding rate-limit handling, honor Slack's retry guidance and keep tests deterministic.

## HTTP endpoint rules

Socket Mode does not require a public HTTP Request URL. If HTTP endpoints are added later:

- Validate requests with `SignatureVerifier` and `SLACK_SIGNING_SECRET`.
- Do not use legacy verification-token flows for new code.
- Keep endpoint handlers thin and covered by tests.

## Security and secret handling

- Never commit real Slack credentials in `.envrc`, tests, docs, screenshots, logs, or comments.
- Use placeholders such as `xapp-***`, `xoxb-***`, and `***`.
- Redact token-like strings from errors and fixtures.
- Do not print full Slack payloads if they may contain user data or secrets.

## Testing guidance

- Do not make live Slack API calls in default tests.
- Mock/fake Slack SDK clients and requests.
- Assert:
  - envelope ack is sent,
  - unsupported events are ignored,
  - bot/subtype messages are filtered,
  - mention tokens are stripped,
  - `chat_postMessage` is called with `thread_ts`,
  - Block Kit messages include fallback `text`,
  - button actions call `chat_update`,
  - HITL resume/cancel action ids are present,
  - `SlackApiError` paths log a safe error.
- Keep tests smoke-level and deterministic.

## Project hygiene

- Keep dependencies minimal: `slack-sdk` only for the current sync Socket Mode bridge.
- Keep `README.md`, `.envrc`, and tests aligned with the environment variable contract.
- If app event subscriptions or scopes change, update README setup steps in the same change.

## References

- `doc/slack-llms-full-python.txt`
- `apps/slack/socket_mode.py`
- `/home/sp/code/ai/sandbox-agentcore/.envrc`
- https://docs.slack.dev/tools/python-slack-sdk/socket-mode
- https://docs.slack.dev/tools/python-slack-sdk/reference/index.html
