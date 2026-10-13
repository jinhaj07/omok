Omok++ GameAgent JangJinha v10 — 시간 재배분과 포획 연쇄 확인

팀명: JangJinha
팀원: 장진하 (개인 참가)

실제 에이전트는 omok-agent/playerJangJinha.py와 smartplayerJangJinha.py입니다.
두 파일을 함께 사용합니다. v6·최종 v9 원본은 verification/reference_v6/,
reference_v9/에 변경 없이 보존했습니다.

이번 변경
1. 중요한 국면의 평가가 깊이에 따라 크게 달라지면 추가 시간을 배정합니다.
   완료한 두 단계 또는 다음 단계에서 전체 점수 범위로 다시 계산한 이전 최선
   수의 점수를 비교합니다. 첫 저비용 단계의 점수는 기준으로 사용하지 않습니다.
   추가 배정은 한 차례이며, 총 예산은 기본 예산의 2.5배·3.6초·남은 경기
   시간에서 20ms를 뺀 값 중 가장 작게 제한합니다. 준비 시간도 포함합니다.
   더 깊은 비교가 중단되면 마지막 완료 단계의 착수를 유지합니다.
2. 기본 전술 탐색의 끝에서 포획 관련 강제 방어와 포획 뒤 재진입을 더 확인합니다.
   추가 가상 착수는 최대 2수, 호출당 노드는 최대 8개입니다. 강제 방어가 최대
   4개인 국면을 검사하며, 선택한 공격에 대한 안전한 방어는 전부 확인합니다.
   공격 후보는 선택적입니다. 한도·반복·시간 중단은 승리나 안전 판정이 아닙니다.
   완료한 연쇄 증명만 재사용하며, 시간 중단 시 가상 착수와 포획을 복구합니다.

기본 평가·후보 폭·PVS·바뀐 줄만 계산하는 구조는 v9와 같습니다.
일반 깊이 6, 기본 전술 깊이 6, 루트 후보 26, 첫 상대 응수 16, 내부 후보 12,
중요 후보 최대 4개 추가, 즉승·유일 안전 응수의 빠른 반환을 유지합니다.
평소 기본 예산 최대 1초, 중요 국면 기본 최대 2.8초도 유지합니다.
정확히 5목, 쌍 포획, 동시 5목·전체 보드 무승부 규칙은 그대로입니다.

현재 확인 범위
7종 규칙·방어·시간·평가·탐색·연쇄 검증을 통과했습니다.
실제 저장한 4개 국면에서 v9·시간만 변경·연쇄만 변경·전체 v10을 두 번씩
비교한 32회, 지정 깊이와 동일 2.8초 예산 비교 4회를 저장했습니다.
핵심 32수째에서는 v10이 두 번 모두 깊이 4를 완료해 (14,10)을 선택했습니다.
추가 검사는 비용이 있습니다. 같은 2.8초 예산의 단일 비교에서는 v9가 깊이 4,
v10이 깊이 3이었습니다. 모든 국면에서 더 깊게 보거나 더 잘 둔다고 판단하지
않습니다. 이번 버전의 새 전체 대전은 진행하지 않았습니다.

반드시 유지할 판단 기준
위험 판단의 약점은 찾았지만, 이 국면을 이기는 수나 승률을 높이는 수정은
아직 입증하지 못했습니다. 프로젝트 기록 PROJECT_STATUS.md에도 명시했습니다.
앞선 첫 수 변경 5판은 모두 건우2에게 졌습니다. 깊이 4의 선택도 승리 수로
입증된 것은 아닙니다. 평가·검출 개선과 실제 승률 향상을 구분해야 합니다.

실행
Python 3.9 이상, 표준 라이브러리만 필요합니다.
압축 해제한 agent_JangJinha_v10 폴더에서 기존 오목 프로젝트 폴더를 지정합니다.
JangJinha(흑) vs SimplePlayer(백), 각자 경기 전체 누적 1분:
python3 run_agent.py "/기존/오목/폴더" 3 2 1
사람(흑) vs JangJinha(백), 외부 경기 시간 무제한:
python3 run_agent.py "/기존/오목/폴더" 0 3 -1

직접 연결
omok-agent를 모듈 경로에 넣습니다.
from smartplayerJangJinha import SmartPlayerJangJinha
agent = SmartPlayerJangJinha(0)
row, col = agent.take_turn(board, remaining_ms)
흑=0, 백=1, 빈칸=-1. 좌표는 0부터 시작하는 (행, 열)입니다.
remaining_ms는 경기 전체 남은 시간(ms), -1은 외부 경기 시간 무제한입니다.

재검증
python3 validate_v10.py
python3 compare_v10.py timed
python3 compare_v10.py fixed
python3 compare_v10.py equal_budget
비교는 새 프로세스·빈 탐색 캐시에서 순차 실행합니다. timed는 실제 남은 경기
시계와 차례 수를 사용합니다. fixed는 깊이 4와 진단용 20초 상한을 사용하며,
equal_budget은 두 코드에 동일한 2.8초 예산을 부여합니다. 고정 시간·깊이
조정은 검사 프로세스 안에만 적용하며 원본 파일은 바꾸지 않습니다.

파일
omok-agent/: 실제 v10 두 파일.
PROJECT_STATUS.md: 목표·미입증 사항·이후 판단 기준.
변경설명.md: 변경 이유, 수치, 계산 비용과 해석 범위.
verification/validation.json, test_logs/: 최종 7종 검증 결과.
verification/v10_*_comparison.json: 최종 에이전트 해시가 연결된 36회 비교.
verification/v10_fixtures.json: 실제 국면과 기존 연쇄 증명 자료.
verification/reference_v6/, reference_v9/: 원본 비교 기준.
verification/history_v9/: 이전 v9 설명과 검사 결과.
verification/prototype_*/: 채택하지 않은 시제품·비교 제어 오류의 개발 기록.
llm-usage/: 기존 AI 사용 기록과 이번 요청·변경 요약.

AI 사용
ChatGPT(Codex)의 도움으로 코드·검증·설명을 작성했습니다.
건우2·기준 버전의 원본은 수정하지 않았습니다.
