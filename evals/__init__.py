"""Strands Evals experiments for the sandbox agent hierarchy.

Two experiments live here:

- ``routing_eval`` — a deterministic (no judge model) CI gate that asserts each prompt reaches the
  correct write/read tool by checking the normalised HITL outcome label. It catches the class of
  regression where an intermediate tier answers in plain text instead of calling the tool (so no
  interrupt is raised and no Slack UI renders).
- ``quality_eval`` — an LLM-as-judge helpfulness check for read responses, using the sandbox's own
  Haiku model as the judge (informational, not a hard gate).

Running either needs AWS Bedrock credentials (the agents call Bedrock), so evals are an online,
opt-in step (``make eval`` / ``make eval-quality``) and are intentionally excluded from the
offline ``make check``.
"""
