# Mac 검증 전 준비

2026-09-16 개발 호스트에서 수행한 준비 기록이다. 운영 Mac 인수 결과는 아니다.
현재 상태는 Phase 1 `awaiting_mac_verify`다.

## 완료한 준비

- 기존 파일이 없는 경우에만 다섯 example registry를 `config/<name>.yaml`로 복사했다.
  대상은 settings, agents, teams, projects, permissions다. 로컬 파일은 Git에서 제외된다.
- 샘플 프로젝트 저장소 주소는 placeholder로 유지했다. 실제 제품 저장소를 추정하지 않았다.
- 샘플 Developer는 disabled, 기본 runtime은 disabled, Git 자동 commit/push/merge는 false다.
  예제의 shared 역할 선언은 활성 협업 흐름을 의미하지 않는다.
- `ai-hub check-config`로 다섯 registry와 workspace 경로의 정합성을 확인했다.
  이 검사는 원격 저장소의 존재·접근 권한이나 런타임 실행 가능성을 보증하지 않는다.
- pytest 277개, Ruff, mypy(67개 소스 파일)를 통과했다.
- 외부 자료의 도입 후보와 수정 조건은 [Agency Agents 검토](AGENCY_AGENTS_REUSE_REVIEW.md)에 기록했다.

`.env` 또는 인증 정보를 생성·수정하지 않았고, 서비스·외부 에이전트·UI를 설치하거나 시작하지
않았다. 테스트는 일시적인 fixture를 사용한다. 운영 DB 초기화나 제품 저장소 clone은 하지 않았다.
로컬 설정 파일은 이 PC에만 존재하므로 다른 PC/Mac에서는 아래 준비를 반복해야 한다.

## 재현 명령

저장소 루트에서 PowerShell로 실행한다. 기존 로컬 설정은 덮어쓰지 않는다.

```powershell
foreach ($registryName in @('settings', 'agents', 'teams', 'projects', 'permissions')) {
    $registryTarget = Join-Path 'config' ($registryName + '.yaml')
    if (-not (Test-Path -LiteralPath $registryTarget)) {
        Copy-Item -LiteralPath (Join-Path 'config' ($registryName + '.example.yaml')) -Destination $registryTarget
    }
}
```

표준 검사:

```text
uv run --locked ai-hub check-config
uv run --locked pytest
uv run --locked ruff check .
uv run --locked mypy
```

이번 Windows 환경은 `.python-version`이 지정하는 3.12 설치 링크가 깨져 있었고,
사용 가능한 기존 venv는 Python 3.14.3이었다. 검사는 다음 접두어로 실행했다.
기본 Python 버전 파일이나 의존성 lock은 변경하지 않았다.

```powershell
python -m uv run --offline --cache-dir .uv-cache --python C:\Python314\python.exe --locked ai-hub check-config
python -m uv run --offline --cache-dir .uv-cache --python C:\Python314\python.exe --locked pytest
python -m uv run --offline --cache-dir .uv-cache --python C:\Python314\python.exe --locked ruff check .
python -m uv run --offline --cache-dir .uv-cache --python C:\Python314\python.exe --locked mypy
```

이 경로는 이번 개발 PC 전용이다. 다른 환경에서는 유효한 인터프리터를 선택하고
표준 명령을 사용한다. 이번 결과를 Python 3.12 또는 macOS 테스트 결과로 보고하지 않는다.

## 추가로 정할 비밀값 없는 정보

| 항목 | 필요한 결정 | 현재 처리 |
|---|---|---|
| 테스트 프로젝트 | 실제 저장소 URL, base branch, 프로젝트/팀 ID | placeholder 유지 |
| 운영 계정 | Mac 전용 계정과 저장소 경로 | Mac에서 확정 |
| 작업 정책 | 자동 commit 여부, 동시 작업 수 | 보수적인 example 기본값 유지 |
| Slack 접근 | 허용 사용자·채널 운영 범위 | 실제 연결 전 확정 |
| 백업 | 목적지·주기·보존 기간·복원 담당 | 첫 부팅 문서에 따라 인수 시 확정 |

실제 프로젝트가 결정되면 agent/team/project의 상호 참조를 함께 바꾸고, 테스트 팀에
Developer 한 명만 활성화한 뒤 check-config를 다시 실행한다. 임의의 예제 저장소를
실제 업무 대상으로 활성화하지 않는다. 비밀값은 이 문서에 기록하지 않는다.

## 남은 실기기 인수

- `[MAC-VERIFY]` Apple Silicon/macOS/CLT/Homebrew 및 bootstrap 재실행.
- `[MAC-VERIFY]` 전용 계정, workspace 소유권·권한, 전원·절전·FileVault 정책.
- `[MAC-VERIFY]` GitHub/Codex 인증과 실제 sandbox·승인 불가 시 실패 동작.
- `[MAC-VERIFY]` Slack Socket Mode 연결, 허용 사용자와 결과 전달.
- `[MAC-VERIFY]` 승인된 fixture에서만 README_TEST.md 생성, 잠금 해제와 이력 확인.
- `[MAC-VERIFY]` launchd 설치/시작/중단/실패 복구 및 재부팅 후 복구.
- `[MAC-VERIFY]` 백업 복원 drill과 localhost readiness 확인.

실행 순서는 [Mac 첫 부팅 체크리스트](MAC_MINI_FIRST_BOOT.md)를 따른다.
멀티에이전트 실행은 Phase 2, 조회 UI/Pixel Office는 Phase 3 승인 후 구현한다.
