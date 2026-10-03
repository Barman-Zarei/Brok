[EN](../README.md) | [FA](README_FA.md) | [RU](README_RU.md) | [CN](README_CN.md) | [ID](README_ID.md) | [KO](README_KO.md)

## Brok 🤖 — 데스크톱 AI 동반자 & 코딩 에이전트 (페르시아어 우선)

<img src="brok.gif" width="140" alt="Brok"/>

Brok는 바탕화면에 사는 작은 로봇입니다(테두리 없음, 항상 위, 드래그 가능). **페르시아어**를 우선으로(다른 언어도 지원) 대화하며, 프로젝트에서 **권한이 통제되는 코딩 에이전트**로 일할 수 있습니다. [myCat](https://github.com/yumiaura/myCat)을 기반으로 하며 NOTICE와 LICENSE.txt를 참고하세요.

- 13가지 상태의 로봇 아바타(대기, 듣는 중, 생각 중, 입력, 코딩, 말하기, 기쁨, 혼란, 오류, 성공, 수면, 알림…)
- **Claude**, **Ollama(로컬)**, OpenAI 호환 API와 대화하며 LOCAL AI / CLOUD AI 표시가 항상 보입니다
- **코딩 작업공간**(우클릭 → Coding Workspace…): 파일, 편집기, 채팅, diff 보기, 터미널, 문제, git. 코드를 선택하고 설명 / 버그 찾기 / 최적화 / 테스트 작성 / Flutter로 변환을 실행
- **보안:** 모든 도구에 위험 수준이 있고, 파일 수정은 diff를 먼저 보여 주며, 삭제·commit·push·위험한 명령은 항상 확인을 요구하고, 위험한 명령은 차단됩니다. 단계·시간·토큰·도구 호출 횟수 제한이 있습니다
- 페르시아어 UI와 RTL, 학습 모드, AI 디버거, 프로젝트 상태 보고서, 직접 관리하는 메모리(`/remember`, `/memory`, `/forget`), 로컬 전용 모드, 전역 단축키(기본 Ctrl+Space), 이미지/스크린샷 첨부

### 설치 (Python ≥ 3.8)
```bash
pip install .
brok                              # desktop
export ANTHROPIC_API_KEY=...      # Claude (optional) / Ollama: ollama pull llama3.1
brok-agent doctor
brok-agent --project . ask "..."
```
자세한 내용: docs/configuration.md · docs/security.md · docs/coding-agent.md

> 현재 상태: 핵심 기능은 자동 테스트(Python 3.8, 3.12, Linux, 디스플레이 없음)로 검증되었습니다. 작성자가 아직 확인하지 못한 것: 실제 키로 Claude/OpenAI/GitHub 호출, Windows/macOS 빌드, 마이크 음성 인식.
