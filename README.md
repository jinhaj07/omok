# 오목 AI 에이전트 개발 (CAS 1102 Project 1 — Omok++ Game Agent)

비공개 저장소. 과제 규정상 공개 업로드 금지.

## 구조
| 경로 | 내용 | 제출 여부 |
|---|---|---|
| `omok-agent/` | `SmartPlayerJinhaJang`, `PlayerJinhaJang` — 제출할 에이전트 | 제출 |
| `omok-game/` | Part 1 게임 인프라(JRM) 사본 + 플레이어 코드 `3` 연결 | 로컬 테스트용 |
| `tests/` | 규칙·엔진 단위 테스트 (인프라 `Board`와 랜덤 대국 교차검증 포함) | 개발용 |
| `tools/arena.py` | 헤드리스 대국기 (병렬, 시간·크래시·불법수 집계) | 개발용 |
| `tools/gate.py` | 회귀 게이트: 채점 조건 재현 + 느린 머신 + 프록시 상대 | 개발용 |
| `tools/tune.py` | 자기대국 기반 평가 가중치 자동 튜닝 (hill climbing) | 개발용 |
| `tuning/` | 튜닝 결과(`best.json`)와 기록(`log.jsonl`) | 개발용 |
| `llm-usage/` | LLM 사용 기록 | 제출 |

## 자주 쓰는 명령 (저장소 루트에서)
```bash
python3 -m unittest discover -s tests                 # 단위 테스트
python3 tools/gate.py                                  # 회귀 게이트 (채택 기준)
python3 tools/arena.py smart simple --games 8          # 1분 제한 8판
python3 tools/tune.py --iters 40 --games 32 --nodes 2000 --openings 6
cd omok-game && python3 omok.py 0 3 1                  # 사람(흑) vs 에이전트(백)
```

## 개발 루프
1. 엔진/평가 수정 또는 `tune.py`로 가중치 탐색
2. `tune.py` 결과를 `DEFAULT_PARAMS`에 반영
3. `gate.py` 통과 + 이전 버전 상대로 우세할 때만 채택 후 커밋
