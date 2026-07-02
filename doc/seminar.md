# Heuristic AI Brainstorming Session

<!--
발표 스크립트:
오늘 세션은 완성된 제품을 공유하는 자리가 아니라, 현재 만든 AgentCore 샌드박스를 기준으로 실제 업무에 맞는 방향을 함께 잡는 브레인스토밍입니다.
핵심 아이디어는 사람, 서비스 계정, 애플리케이션, 워크로드를 모두 principal 로 보고, 그 principal 의 계정과 credential lifecycle 을 agent hierarchy 로 관리할 수 있는지 검증하는 것입니다.
-->

## Why This Document  

<!--
발표 스크립트:
6월 29일에 AWS 개인 계정과 테스트 환경을 만들었고, 오늘까지는 기존 요구사항이었던 인증서 갱신, user onboarding, account sync 같은 내부 리소스 관리 관점으로 실험했습니다.
아직 도메인 정보가 충분하지 않기 때문에, 오늘은 실제 운영 지식이 있는 분들의 의견을 받아 agent 구조와 우선순위를 보정하려고 합니다.
-->

This seminar note summarizes the final state of the sandbox after the latest chat-driven
implementation cycle.

Primary outcome: the sandbox now demonstrates principal/account/certificate/secret lifecycle
handling with Slack-first HITL flows and centralized deterministic mock data.

## Scope and Architecture

<!--
발표 스크립트:
이 프로젝트에서 HR supervisor 아래에는 cert leaf 뿐 아니라 account-manager leaf 도 존재합니다.
cert 는 credential/certificate lifecycle 을 담당하고, account-manager 는 principal 과 account inventory, onboarding/offboarding 검증을 담당합니다.
지금은 세 tier 를 하나의 AgentCore 런타임 안에서 in-process agents-as-tools 패턴으로 동작시킵니다.
-->

The repository remains intentionally minimal:

- Strands agents
- Bedrock model invocation
- AgentCore Runtime entrypoint
- Slack Socket Mode bridge
- Terraform runtime scaffold

Hierarchy (single runtime, in-process agents-as-tools):

```text
orchestrator (root)
└── supervisor: human-resource
        ├── leaf: cert
        └── leaf: account-manager
```

## What Was Implemented in This Cycle

<!--
발표 스크립트:
이번 사이클에서 실제로 동작하는 범위를 먼저 정리하겠습니다.
Slack 슬래시 커맨드는 걷어내고, @mention/DM 으로 에이전트를 부르면 Strands interrupt 가 그대로 Slack Block Kit 으로 뜨는 agent-driven HITL 흐름으로 바꿨습니다.
principal 의 계정·credential·certificate·secret lifecycle 을 교차 검증하는 로직을 추가했고,
흩어져 있던 mock 데이터를 apps/mock_data.py 하나로 통합했습니다.
-->

### 1) Agent-driven HITL workflows

Slack 상호작용은 전적으로 에이전트가 주도합니다. 슬래시 커맨드는 없고, `@mention` 또는 DM 으로
요청하면 오케스트레이터가 처리하다가 write 작업에서 Strands interrupt 를 올리고, 그 interrupt 가
Slack Block Kit 으로 렌더링됩니다.

인증서 갱신 (cert leaf):

- `@sandbox-ai-app cert status <domain>` — 상태 조회 (읽기, interrupt 없음)
- `@sandbox-ai-app cert renew` — 도메인 없이 요청하면 `cert_selection` interrupt → `external_select`
  인증서 선택기 → 선택 후 `cert_renewal_approval` interrupt → managed_via 상세가 포함된 승인 카드
- `@sandbox-ai-app cert renew <domain>` — 도메인을 주면 선택 단계를 건너뛰고 바로 승인 카드

계정/principal (account leaf):

- `@sandbox-ai-app <principal> 조회` — lookup/list 계열 읽기 도구 (interrupt 없음)
- `@sandbox-ai-app <principal> 계정 생성|변경|삭제` — 각각 `account_create/update/delete` interrupt →
  승인 카드; 삭제는 연결된 인증서·시크릿 offboarding 체크리스트를 함께 표시

<!--
발표 스크립트:
핵심은 인자 없이 "cert renew" 만 멘션해도 에이전트가 도메인을 되묻지 않고 곧장 external_select 인증서 선택기를 띄운다는 점입니다.
선택하면 managed_via(SSH/ACM) 상세가 담긴 승인 카드가 뜨고, 승인/취소 버튼으로 마무리합니다.
계정 삭제는 대상에 연결된 인증서와 시크릿을 offboarding 체크리스트로 함께 보여줘서, 무엇을 회수해야 하는지 한눈에 보이게 했습니다.
-->

모든 대상 선택은 `external_select` 로 처리하며, 옵션은 Socket Mode 의 `block_suggestion` 리스너가
`build_hitl_options(...)` 로 제공합니다. 버튼/선택 payload 에는 secret 이 아닌 값(session,
interrupt_id, response)만 담기며, `cert_selection` 은 external_select 에 value 가 없어 resume
컨텍스트를 select 의 `block_id` 에 인코딩합니다.

### 2) HITL behavior

<!--
발표 스크립트:
모든 인터랙션은 ack-first 로 처리합니다. 3초 안에 먼저 응답하고, 상세 조회나 오케스트레이션은 그 다음에 수행합니다.
상세/조회 액션은 절대 변경을 일으키지 않고, 승인 제출 시에도 sandbox 에서는 실제 mutation 없이 승인 의도만 기록합니다.
-->

- Interactive actions follow ack-first handling (3초 내 `ack()` 먼저).
- Read/detail actions are non-mutating.
- Approval submissions record intent/outcome only in sandbox mode.
- Real infrastructure mutation is intentionally out of scope.

### 3) Principal lifecycle verification

<!--
발표 스크립트:
principal lifecycle 검증은 "이 hierarchy 가 각 principal 의 lifecycle 을 관리할 수 있는가"를 확인하는 것입니다.
여기서 manageable 은 리소스가 건강하다는 뜻이 아니라, hierarchy 가 탐지·열거하고 HITL 로 조치를 라우팅할 수 있다는 의미입니다.
예를 들어 만료된 인증서도 cert leaf 가 탐지할 수 있으므로 manageable 로 봅니다.
-->

Cross-leaf lifecycle checks verify whether each principal is manageable across:

- account lifecycle
- credential lifecycle
- certificate lifecycle
- secret lifecycle

Manageable means the hierarchy can discover and route lifecycle work, not that the current
resource health is perfect.

### 4) Centralized mock data and resource typing

<!--
발표 스크립트:
이전에는 Slack 쪽과 agent leaf 쪽이 각자 mock 데이터를 들고 있어서 값이 어긋날 위험이 있었습니다.
이번에 apps/mock_data.py 를 단일 소스로 만들어 cert leaf, account-manager leaf, lifecycle 검증, Slack 렌더링이 모두 같은 레코드를 공유하도록 했습니다.
인증서와 시크릿에는 managed_via/management_endpoint 를 추가해, 소유한 자원을 SSH·HTTP 등 여러 방법으로 관리·갱신한다는 요구를 모델링했습니다.
-->

All mock registries were consolidated into a single source of truth:

- `apps/mock_data.py`

Used by:

- `apps/agents/leaf_cert.py`
- `apps/agents/leaf_account_manager.py`
- `apps/agents/principal_lifecycle.py`
- `apps/slack/workflows.py` (Block Kit rendering of interrupt reasons)

Resource taxonomy now includes explicit types:

- principal types: `user`, `contractor`, `service_account`, `application`, `workload`, `agent_identity`
- resource types: `nginx_certificate`, `acm_certificate`, `aws_secret`, `aws_account`

`CertificateRecord` and `SecretRecord` also carry a management method, modeling that an owned
resource can be managed/renewed via multiple methods:

- `managed_via` — cert: `ssh` (certbot + `nginx -s reload`) or `acm_api` (HTTPS ACM API); secret: `api`
- `management_endpoint` — e.g. `ssh://deploy@nginx.internal`, `https://acm.us-east-1.amazonaws.com`,
  `https://secretsmanager.us-east-1.amazonaws.com`

Compatibility note: `apps/slack/mock_data.py` remains as a thin re-export shim so legacy imports
continue to work while the canonical data lives in `apps/mock_data.py`.

## Representative Lifecycle Examples

<!--
발표 스크립트:
샘플 principal 을 유형별로 하나씩 준비했습니다.
service_account 인 deploy-bot 은 nginx_certificate 와 aws_secret 이 연결되어 있고,
application 인 payments-api 는 인증서와 secret 을 함께 봅니다.
workload 인 batch-runner 는 만료된 인증서를 탐지하는 케이스를 보여줍니다.
-->

- `new.engineer` (`user`): onboarding lifecycle checks
- `deploy-bot` (`service_account`): linked `nginx_certificate` + `aws_secret`
- `payments-api` (`application`): linked `acm_certificate` + `aws_secret`
- `batch-runner` (`workload`): expired certificate detection remains manageable



## Demo Paths (copy-paste ready)

<!--
발표 스크립트:
데모는 세 가지입니다. 인증서 갱신, 계정 종료, 그리고 principal lifecycle 커버리지 검증입니다.
앞의 두 개는 Slack 멘션 → interrupt → 승인 흐름으로, 마지막은 복붙으로 바로 실행 가능한 명령으로 보여드립니다.
-->

### Demo 1 — Certificate renewal via mention (`@sandbox-ai-app cert renew`)

<!--
발표 스크립트:
도메인 없이 "cert renew" 만 멘션합니다. 에이전트가 도메인을 되묻지 않고 cert_selection interrupt 를 올려 external_select 인증서 선택기를 띄웁니다.
인증서를 하나 고르면 cert_renewal_approval interrupt 로 넘어가 managed_via(SSH 또는 ACM) 상세가 담긴 승인 카드가 뜹니다.
[승인] 을 누르면 nginx.internal 처럼 ssh 로 관리되는 인증서는 "certbot renew + nginx -s reload" 가 기록되고, acm_api 인증서는 ACM 갱신 요청이 기록됩니다. 실제 갱신은 없습니다.
-->

Slack (도메인 없이 멘션 → 선택 → 승인):

```text
@sandbox-ai-app cert renew
```

Flow:

1. `@sandbox-ai-app cert renew` → 에이전트가 `cert_selection` interrupt 를 올립니다 (아직 대상 없음).
2. Slack 이 `external_select` 인증서 선택기를 렌더링 (옵션은 `block_suggestion` 리스너가 제공) → 인증서 하나 선택.
3. 선택한 도메인이 tool 로 돌아가면 `cert_renewal_approval` interrupt 로 이어져 승인 카드가 표시됩니다:
   domain, ARN, account, region, status, expiration, renewal eligibility, renewal status, in-use,
   그리고 `관리 방식`(managed_via + management_endpoint) 라인.
4. `[승인]` → managed_via 경로가 기록됩니다: `ssh` → `certbot renew` + `nginx -s reload`,
   `acm_api` → ACM 갱신/재-import 요청 (sandbox: 실제 갱신 없음). `[취소]` → 변경 없음.

(선택) 도메인을 함께 주면 선택 단계를 건너뜁니다: `@sandbox-ai-app cert renew api.example.com`.

### Demo 2 — Account offboarding via mention (`@sandbox-ai-app offboard deploy-bot`)

<!--
발표 스크립트:
계정 종료도 멘션으로 진행합니다. "offboard deploy-bot" 또는 "deploy-bot 계정 삭제" 처럼 자연어로 요청하면 에이전트가 principal 이름을 파싱해 account_delete interrupt 를 올립니다.
승인 카드에는 대상에 연결된 인증서와 시크릿이 offboarding 체크리스트로 함께 표시되어, 회수해야 할 자원이 한눈에 보입니다.
[승인] 을 누르면 offboarding 이 기록됩니다. sandbox 라 실제 삭제는 없습니다.
-->

Slack (자연어 멘션 → 승인):

```text
@sandbox-ai-app offboard deploy-bot
```

Flow:

1. `@sandbox-ai-app offboard deploy-bot` (또는 `deploy-bot 계정 삭제`) → 에이전트가 principal 이름을
   파싱해 `account_delete` interrupt 를 올립니다.
2. Slack 이 승인 카드를 렌더링: principal, type, owner, status + 연결된 인증서·시크릿 offboarding
   체크리스트 (`linked_resources`).
3. `[승인]` → offboarding 이 기록되고 회수 대상 목록이 남습니다 (sandbox: 실제 삭제 없음).
   `[취소]` → 변경 없음.

생성/변경도 같은 패턴입니다: `@sandbox-ai-app create service account ci-bot`,
`@sandbox-ai-app update deploy-bot access`.

### Demo 3 — Principal lifecycle coverage (runnable)

<!--
발표 스크립트:
마지막 데모는 principal type 별 lifecycle 커버리지 검증입니다.
이건 Slack 없이도 복붙으로 바로 실행됩니다. AWS 자격증명이 없어도 offline 결정론적으로 동작합니다.
전체 타입 커버리지, 그리고 개별 principal 검증 두 가지를 보여드립니다.
-->

전체 타입 커버리지 (offline, 자격증명 불필요) — 복붙 후 바로 실행:

```sh
uv run python -c "from apps.agents.principal_lifecycle import verify_principal_types; print(verify_principal_types())"
```

개별 principal lifecycle 검증:

```sh
uv run python -c "from apps.agents.principal_lifecycle import verify_principal_lifecycle; print(verify_principal_lifecycle('payments-api'))"
```

런타임(`make run`)이 떠 있을 때 HTTP 로 동일 검증:

```sh
curl -s http://127.0.0.1:8080/invocations \
  -H 'content-type: application/json' \
  -d '{"prompt":"verify principal type lifecycle coverage"}'
```

Expected output includes type-level coverage for `user`, `service_account`, `application`, and
`workload`, plus a hierarchy-wide `hierarchy_can_manage_all_types=yes` summary line.

## Diagram

```mermaid
flowchart TD
    U[Slack User @mention] --> S[Socket Mode Bridge]
    S --> R[hitl.start at AgentCore Runtime]
    R --> O[Orchestrator]
    O -- as_tool --> H[HR Supervisor]
    H -- as_tool --> C[Cert Leaf]
    H -- as_tool --> A[Account-Manager Leaf]
    C --> C1[Certificate Lifecycle]
    A --> A1[Account and Access Lifecycle]
    A --> A2[Secret Lifecycle]
    C -. interrupt bubbles up .-> P[Slack Block Kit: 승인/취소 or external_select]
    A -. interrupt bubbles up .-> P
    P -. hitl.resume forwards response .-> C
    P -. hitl.resume forwards response .-> A
```

## Quality and Validation Status

<!--
발표 스크립트:
현재 ruff, ruff format 체크, pyright, pytest 가 모두 로컬에서 통과합니다.
pytest 출력에 뜨던 의존성 경고는 저장소 코드 범위 밖(.venv)이라 프로젝트 체크에서 필터링했습니다.
-->

Current checks pass locally:

- `ruff check`
- `ruff format --check`
- `pyright` (includes `apps/`, `tests/`, `evals/`)
- `pytest`

The dependency warning previously emitted from `.venv/lib/python3.14/site-packages` during
pytest output was filtered from project checks because it is outside repository code scope.

## AI 서비스 품질 보증 — Evaluator 도입 제안

<!--
발표 스크립트:
마지막으로 AI 담당자를 통해 aiops 구조를 살펴보니 evaluator 부분이 빠져 있다는 점을 발견했습니다.
저희 팀이 leaf agent 개발 외에, AI 서비스들에 대한 품질을 보증하는 CI 과정을 맡는 것이 팀에 도움이 되지 않을까 하는 아이디어를 공유드리려 합니다.
오늘 이 자리에서 다른 분들의 의견도 여쭤보고 싶습니다.
-->

이번 구현 사이클에서 실제로 경험한 **회귀 버그 두 가지**가 evaluator 도입의 동기입니다.

1. **Slack UI 미표시** — HR supervisor(Haiku)가 `cert_specialist` 툴을 호출하지 않고 평문으로
   인증서 상세를 되물어 interrupt 가 생성되지 않았습니다. `STATUS_FINAL` 텍스트가 반환되어
   Slack Block Kit 이 전혀 표시되지 않았습니다.
2. **중복 클릭 크래시** — `[승인]` 버튼을 빠르게 두 번 클릭하면 동일 세션의 캐시된 에이전트에
   동시 `resume` 이 들어가 `ConcurrencyException` 이 발생했습니다.

두 버그 모두 **수동 실행 전까지 발견되지 않았습니다.** Evaluator 는 이런 class 의 회귀를 CI 단계에서
잡는 안전망입니다.

### 설계 원칙

에이전트가 채널 비종속(`reason` = 구조화 dict) 이듯, evaluator 도 AI 서비스에 비종속이어야 합니다.

- **결정론적 게이트** (judge model 불필요) — 프롬프트 → 정규화된 outcome label 을 `Equals` 로 채점.
  `cert renew` 라는 입력이 `interrupt:cert_selection` 을 반환하는지 여부는 LLM 심판 없이 판단할 수 있습니다.
- **LLM-as-judge 품질 평가** — 읽기 응답의 helpfulness 는 subjective 하므로 동일 Haiku 모델을
  judge 로 사용하는 커스텀 평가자로 분리합니다 (hard gate 아닌 참고 지표).
- **오프라인 `make check` 와 분리** — 에이전트 호출에 Bedrock 이 필요하므로 eval 은 opt-in CI 스텝
  (`make eval`) 으로 별도 분리합니다.

### 구현체

```
evals/
├── __init__.py           # 패키지 설명
├── routing_eval.py       # 결정론적 라우팅 게이트 (CI hard gate)
└── quality_eval.py       # Haiku-judge helpfulness 평가 (참고 지표)
```

**`routing_eval.py`** — `Equals` 평가자(judge model 없음), 5 케이스:

| 케이스 | 입력 | 기대 outcome label |
|---|---|---|
| `cert-renew-no-domain` | `"cert renew"` | `interrupt:cert_selection` |
| `cert-renew-with-domain` | `"renew the certificate for api.example.com"` | `interrupt:cert_renewal_approval` |
| `cert-status-read` | `"what is the certificate status for api.example.com"` | `final` |
| `account-offboard` | `"offboard the deploy-bot service account"` | `interrupt:account_delete_approval` |
| `account-lookup-read` | `"which accounts does deploy-bot have"` | `final` |

각 케이스는 orchestrator → supervisor → leaf 를 거쳐 실제로 interrupt 가 발생하는지 (또는
발생하지 않는지) 를 검증합니다. **「Slack UI 미표시」 버그 클래스**를 자동으로 잡습니다.

**`quality_eval.py`** — `HaikuHelpfulnessJudge` 커스텀 평가자, 읽기 응답 4 케이스:

```python
class HaikuHelpfulnessJudge(Evaluator[str, str]):
    """동일 Haiku 모델로 응답 helpfulness 를 PASS/FAIL 로 채점하는 커스텀 평가자."""
    def evaluate(self, evaluation_case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        judge = Agent(model=self._model, system_prompt=_JUDGE_PROMPT)
        verdict = str(judge(f"USER: {evaluation_case.input}\nASSISTANT: ..."))
        passed = "PASS" in verdict.upper()
        return [EvaluationOutput(score=1.0 if passed else 0.0, test_pass=passed, reason=verdict)]
```

### 실행 방법

```sh
# CI 결정론적 라우팅 게이트 (exit 0 = 전체 통과, exit 1 = 1건 이상 실패)
make eval

# LLM-as-judge 품질 평가 (참고 지표 — 항상 exit 0)
make eval-quality
```

두 명령 모두 AWS Bedrock 자격증명이 필요합니다. 오프라인 `make check` 에는 포함되지 않습니다.

### Strands Evals SDK 선택 이유

이 프로젝트는 이미 `strands-agents-evals>=1.0.1` 를 의존성으로 포함하고 있으며,
[Strands Evals SDK](https://strandsagents.com/docs/user-guide/evals-sdk/quickstart/) 는
다음을 제공합니다:

- `Equals`/`Contains` 등 **결정론적 평가자** (judge model 없이 CI 게이트로 사용 가능)
- `Evaluator[I, O]` **커스텀 평가자 인터페이스** (도메인 특화 judge 작성 가능)
- `TrajectoryEvaluator` — 어떤 툴이 어떤 순서로 호출됐는지 평가 (future 확장)
- `ToolSelectionAccuracyEvaluator` — 올바른 툴을 선택했는지 정밀 평가 (future 확장)
- CLI `strands-evals run` — GitHub Actions 등 CI 파이프라인에서 no-code 실행

### 운영 팀에 대한 제안

<!--
발표 스크립트:
추후 시스템을 운영하는 role 로서 leaf agent 개발 외에, AI 서비스들에 대한 품질을 보증하는 CI 과정을 저희 팀이 맡는 것이 도움이 될 것 같다는 아이디어를 공유드렸습니다.
구체적으로는 두 가지 역할을 생각해 볼 수 있습니다.
첫째, 새 leaf agent 나 write tool 이 추가될 때 routing_eval 케이스를 함께 작성하는 기여입니다.
둘째, aiops 관점에서 전체 AI 서비스에 대한 품질 SLA 를 정의하고 evaluator 를 통해 측정하는 역할입니다.
-->

| 역할 | 내용 |
|---|---|
| **개발 기여** | 새 leaf agent / write tool 추가 시 `routing_eval.py` 케이스를 함께 작성 |
| **AI ops 품질 SLA** | 전체 AI 서비스에 대한 품질 지표 정의 + evaluator 로 측정 |
| **CI 게이트 유지** | `make eval` 이 PR merge 전 통과 필수인 파이프라인으로 발전 |

현재 구현 상태에서 곧바로 적용 가능한 하나의 패턴을 제안드립니다:

> **"새 write tool 을 추가하면 `routing_eval.py` 에 케이스를 동시에 추가한다."**

이 규칙 하나만 지켜도, 지금까지 경험한 「interrupt 미발생 → Slack UI 미표시」 클래스의 회귀를
자동으로 잡을 수 있습니다.

## Next Steps for Discussion

<!--
발표 스크립트:
마지막으로 논의하고 싶은 것은 어떤 실제 시스템부터 read-only 로 연결할지, 각 write 작업에 어떤 승인 근거가 필요한지,
그리고 어떤 저위험 작업은 Slack 승인만으로 충분한지입니다. single-runtime 구조는 명확한 요구가 있기 전까지 유지합니다.
-->

1. Prioritize first real read-only integrations (IAM Identity Center, Organizations, ACM, Secrets Manager).
2. Define approval evidence requirements for each write-class operation.
3. Decide whether Slack approval alone is sufficient for any low-risk operations.
4. Keep single-runtime hierarchy until a specific requirement justifies multi-runtime promotion.
5. **Evaluator CI 운영화** — `make eval` 을 GitHub Actions PR 게이트로 등록하고, 새 write tool 추가
   시 routing_eval 케이스 작성을 기여 규칙으로 지정.
   
