# Agency Agents 도입 후보 검토

검토일: 2026-09-16. 결론: 역할 지침과 UI 정보 구조를 선별적으로 활용한다.
플랫폼 실행·권한·상태 관리 계층은 기존 구조를 유지한다.
이 문서는 조사와 후속 제안이며 Phase 2/3 구현 승인이나 설치 기록이 아니다.

## 1. 검토 범위와 근거

- [agency-agents](https://github.com/msitarzewski/agency-agents): 역할 Markdown,
  divisions, 변환 스크립트, coordination, playbooks, runbooks 구조와 주요 문서.
- [agency-agents-app](https://github.com/msitarzewski/agency-agents-app): 별도 UI 저장소.
  README, 파일 목록, AgentsWorkspace 및 AgencyDashboard 소스를 확인했다.
- API 파일 목록 조회 시 main 커밋:
  - agency-agents: `ad9264e309bd5e5422c04784372d7841b1e5d604`
  - agency-agents-app: `d84defbbf27702e204a4899339edcff4a90ef9af`
- 본문 열람은 main 및 웹 캐시 기준이다. 위 커밋 전체를 체크아웃해 감사한 결과는
  아니다. 실제 복사 시 해당 파일을 선택한 커밋에서 다시 확인하고 해시를 기록한다.
- 전체 파일을 개별 평가하지는 않았다. 구조 전반과 관련성이 높은 대표 파일을
  검토했다. 외부 앱 설치·실행, UI 시각/접근성 테스트, 성능 비교는 수행하지 않았다.

## 2. 도입 후보 목록

| 대상 | 판단 | 우리 쪽 활용 | 조정 및 도입 시점 |
|---|---|---|---|
| 역할 이름·설명·직능 분류 | 채택 후보 | 에이전트 카탈로그 및 역할 설명 | 직능 분류와 소속 팀을 분리. Phase 2 |
| 전문 분야·책임·산출물 | 우선 채택 후보 | Developer/Reviewer/QA 업무 계약 | 실제 스택과 작업 범위로 축소. Phase 2 |
| 행동 규칙·보고 형식 | 선별 채택 | 범위 준수, 근거 제시, 검증 결과 보고 | 기존 정책과 충돌하는 문장 제거. 현재는 검토 문서만 |
| persona의 Memory/Experience | 그대로 도입 제외 | 필요한 경우 검증 가능한 역할 설명으로 대체 | 지침 문장이 실제 기억·경력·학습 기능을 만들지는 않음 |
| 인계·QA 피드백·에스컬레이션 양식 | 우선 채택 후보 | 구조화된 산출물과 재작업 요청 | Task/Run/Event ID, 파일 근거를 연결. Phase 2 |
| NEXUS 전체 워크플로 | 참고 | 작업별 최소 협업 흐름 선택 | 모든 작업에 전체 조직을 동원하지 않음. Phase 2 |
| 시나리오 runbook | 선별 참고 | 장애 대응·제품 작업 운영 절차 | 단일 Mac와 인간 승인 정책에 맞게 축소 |
| divisions 메타데이터 | 선별 채택 후보 | 직능 필터, 표시명, 색상·아이콘 | 새 스키마 설계 후 반영. 권한 근거로 사용 금지 |
| 역할 검색·상세 패널 UI | 우선 UI 후보 | 역할/권한/소속/지침 버전을 한 화면에서 조회 | 읽기 전용 화면으로 재구현. Phase 3 |
| Teams/Projects UI | UI 참고 | 팀 책임과 프로젝트 연결 관계 조회 | preset 역할 묶음과 실제 소유 팀은 별개. Phase 3 |
| 설치 상태 Dashboard | 정보 구조 참고 | 주의가 필요한 항목에서 상세로 이동 | 설치 상태를 실행 상태로 취급하지 않음. Phase 3 |
| source/rendered hash·변경 감지 | 설계 후보 | 지침 버전 고정과 변경 검토 | 자동 갱신 대신 검토된 버전 선택. Phase 2 이후 |
| convert/install 스크립트 | 참고만 | 명시적 지침 전달 설계에 참고 | 전역 설치를 플랫폼 설정으로 간주하지 않음 |
| 외부 앱의 설치·Deploy·업데이트 버튼 | 초기 도입 제외 | 없음 | Pixel UI의 읽기 전용 원칙과 분리 |
| 전체 Tauri/Rust/Svelte 앱 | 통째 도입 보류 | 구성 요소별 참고 | 기존 Python 및 향후 Phaser/TypeScript와 연결 비용 큼 |
| 픽셀 오피스·실시간 작업 타임라인 | 직접 재사용 근거 없음 | 우리 Event projection으로 별도 개발 | 검토한 앱은 역할 설치 관리자. Phase 3 |

## 3. 역할별 우선순위

### 먼저 검토할 역할

1. [Minimal Change Engineer](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-minimal-change-engineer.md)
   — 변경 범위 관리에 유용하다. 파일 열람을 과도하게 제한하는 규칙, 임의의 코드 줄 수
   목표는 제외한다. 근본 원인 조사와 필수 검증을 방해해서는 안 된다.
2. [Code Reviewer](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-code-reviewer.md)
   — 정확성·보안·유지보수·테스트 기준과 심각도별 피드백을 참고한다.
   리뷰 결과는 근거와 권고이며 최종 상태 변경은 플랫폼 정책이 수행한다.
3. [Reality Checker](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-reality-checker.md)
   — 완료 주장과 실증 자료를 대조하는 원칙을 참고한다. 첫 시도 자동 불합격이나
   모든 시스템에 스크린샷을 요구하는 규칙은 제외한다. 인프라는 DB·잠금·복구 증거가 필요하다.
4. [Multi-Agent Systems Architect](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-multi-agent-systems-architect.md)
   — 계약·실패 경로·컨텍스트·권한·관측성 설계 체크리스트로 활용한다.
   문서의 체인 길이·평가 개수 등의 수치를 검증된 보편 법칙으로 채택하지 않는다.
5. [UI Designer](https://github.com/msitarzewski/agency-agents/blob/main/design/design-ui-designer.md)
   — 일관된 디자인과 접근성, 화면 인계 기준을 후속 UI 설계에 활용한다.
   이 역할 문서는 UI 코드나 픽셀 그래픽 자산 자체가 아니다.

### 작업 필요성이 생기면 추가 검토

Technical Writer, SRE, Software Architect, API Tester, Test Results Analyzer,
Accessibility Auditor, UX Researcher가 후보다. 파일 목록 또는 역할 설명 수준의 후보이며
이번에 모두 상세 평가한 것은 아니다. 제품의 실제 스택을 확인한 뒤 Frontend/Backend
역할을 고른다. 마케팅·영업·게임·공간 컴퓨팅 등은 담당 제품의 요구가 생길 때 검토한다.
역할 수 자체를 플랫폼 성숙도나 품질 지표로 삼지 않는다.

## 4. UI에서 가져올 것과 데이터 연결

상세 근거:
[앱 README](https://github.com/msitarzewski/agency-agents-app/blob/main/README.md),
[AgentsWorkspace](https://github.com/msitarzewski/agency-agents-app/blob/main/src/lib/components/AgentsWorkspace.svelte),
[AgencyDashboard](https://github.com/msitarzewski/agency-agents-app/blob/main/src/lib/components/AgencyDashboard.svelte).

검색·목록·상세를 함께 보여주는 구성을 우선 참고한다. 원본 컴포넌트는 Svelte store,
설치 데이터, Tauri 경계와 연결되어 있어 복사만으로 우리 시스템에 작동하지 않는다.

| 화면 | 가져올 표현 방식 | 우리 데이터와 표시 기준 |
|---|---|---|
| Agents | 직능 필터, 검색, 상세 패널 | 역할/팀/프로젝트/권한 프로필/승인된 지침 버전 |
| Teams | 역할 구성과 상세 보기 | 공용 플랫폼 팀과 제품 팀 구분, 실제 registry 관계 |
| Projects | 목록과 연결된 구성 보기 | 등록 저장소, 담당 팀, 실제 작업 상태 |
| Overview | 주의 항목에서 필터된 상세로 이동 | blocked/failed 작업과 관측 시각; 설치 개수와 분리 |
| Instruction changes | 원본과 로컬 차이 확인 | 출처 커밋, 파일 해시, 검토한 변경 내역 |
| Task detail | 별도 설계 필요 | 상태 전이, run, 검증 결과, 산출물과 event ID |
| Pixel Office | 별도 설계 필요 | 실제 이벤트만 표현; 정지·실패·연결 끊김을 정직하게 표시 |

이름·색상·아이콘은 표시용이다. 전문성이나 실행 권한의 증거가 아니다.
원본의 current/outdated/modified는 지침 파일 상태이며 running/completed로 대응시키지 않는다.
최종 UI 스택 변경은 별도 결정과 ADR이 필요하다. 이번 검토는 기존 결정을 바꾸지 않는다.

## 5. 전문성을 적용하는 방식 — 후속 설계 제안

역할 텍스트만으로 전문성을 입증할 수 없다. 역할별 입력, 허용 범위, 산출물, 검증 기준을
먼저 정하고 동일한 과제로 기본 Developer와 비교해야 한다.

- 공통 안전 정책과 프로젝트 범위를 플랫폼이 결정한다.
- 역할 지침은 승인된 작업을 수행하는 방법에 집중한다.
- 역할 지침에 추가 권한, 임의의 도구 설치, 자동 push/merge/deploy 권한을 부여하지 않는다.
- 필요한 역할 내용만 전달한다. 전체 카탈로그를 매 실행 프롬프트에 넣지 않는다.
- 입력은 요구사항·프로젝트 참조·허용 파일 범위·완료 기준으로 제한한다.
- 결과는 변경 파일·수행한 검증·미검증 항목·산출물 참조·차단 사유로 받는다.
- Phase 2에서는 정상 작업, 권한 밖 요청, 시간 초과, 잘못된 인계, 근거 없는 완료 주장으로
  평가한다. 성공률, 재작업, 비용·시간, 권한 위반을 기록한다.
- 역할의 자기평가나 점수만으로 completed로 바꾸지 않는다. 숨겨진 사고 과정은 수집하지 않는다.

현재 registry의 skills/tools 필드에 이름을 넣는 것만으로 외부 역할이 로드된다고 볼 수 없다.
현재 Codex 어댑터는 사용자 설정을 무시하므로 전역 설치 대신 명시적인 지침 전달 계약을
설계해야 한다. 이것은 후속 단계의 작업이며 이번에 구현하지 않았다.

## 6. 협업 자료의 수정 지점

[Handoff Templates](https://github.com/msitarzewski/agency-agents/blob/main/strategy/coordination/handoff-templates.md)의
입력·완료 조건·실패 근거 구성을 참고한다. 우리 쪽에서는 task/run/correlation 참조와
검증된 산출물 경로를 사용하고, 전송되는 텍스트를 권한이나 실행 명령으로 해석하지 않는다.

[Agents Orchestrator](https://github.com/msitarzewski/agency-agents/blob/main/specialized/agents-orchestrator.md)의
모든 작업 통과 요구와 실패 작업을 두고 진행하는 절차는 적용 전 조정해야 한다.
의존성이 있는 후속 작업은 선행 실패를 무시해서는 안 된다. 재시도 횟수와 종료 상태는
기존 상태 모델에 맞게 코드로 강제해야 한다.

[NEXUS](https://github.com/msitarzewski/agency-agents/blob/main/strategy/nexus-strategy.md)의 단계 번호는
제품 개발 절차이며 우리 저장소의 Phase 승인 번호와 관계없다.
[Incident runbook](https://github.com/msitarzewski/agency-agents/blob/main/strategy/runbooks/scenario-incident-response.md)은
운영 문서 참고 후보이며 자동 복구/배포 실행 권한으로 취급하지 않는다.

## 7. 출처와 업데이트 정책

두 저장소의 LICENSE는 MIT다. 원문·코드의 실질적 부분을 가져올 때 각 저장소의
저작권 고지와 라이선스 본문을 함께 보존한다. 의존성·아이콘·이미지는 별도 출처도 확인한다.

- [원본 지침 LICENSE](https://github.com/msitarzewski/agency-agents/blob/main/LICENSE)
  — Copyright (c) 2025 AgentLand Contributors.
- [앱 LICENSE](https://github.com/msitarzewski/agency-agents-app/blob/main/LICENSE)
  — Copyright (c) 2026 Michael Sitarzewski.

실제 도입 기록에는 저장소, 고정 커밋, 파일 경로, 원본 해시, 로컬 수정 사항, 승인 상태,
평가 결과를 남기는 방식을 제안한다. main을 자동 추적해 실행 지침을 바꾸지 않는다.
이번에는 원본 코드·역할 파일·이미지를 복사하거나 설치하지 않았다.

## 8. 실행 순서

1. 현재 Phase 1: 비밀값 없는 로컬 설정 준비, 오프라인 검증, Mac 인수 체크리스트 정리.
2. `[MAC-VERIFY]`: 실제 Mac에서 인증·격리·Slack·launchd·재부팅·복구 확인.
3. Phase 2 승인 후: 최소 역할 지침, 평가 과제, 구조화된 인계, 버전 기록을 도입.
4. Phase 3 승인 후: 카탈로그/팀/프로젝트 조회 UI와 실제 이벤트 기반 작업·Pixel 화면 개발.

Mac이 없어도 문서와 도입 후보 정리는 가능하다. 하지만 Mac 없이 개발할 수 있다는 사실이
잠긴 단계의 구현 권한을 뜻하지는 않는다. 현재 Phase 상태는 그대로 유지한다.
