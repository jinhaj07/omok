CAS 1102 Project 1: Omok++ — Game Agent

1. Team members
Team name: JRM
Number of members: 3
- Member name: Minjun Ryu, Geonwoo Min, Jinha Jang
(TODO: describe each member's role)

2. Running instructions
Python version used: Python 3.13 (standard library only; works on Python 3.8+)
No additional packages are required.

The agent lives in omok-agent/:
  smartplayerjinhajang.py   SmartPlayerJinhaJang (the game agent)
  playerjinhajang.py        PlayerJinhaJang (copy of the Player base class)

To use it in a game infrastructure, put both files next to omok.py and map
player code 3 to the agent, e.g. in GameManager:
    from smartplayerjinhajang import SmartPlayerJinhaJang
    ...
    elif player == 3:
        return SmartPlayerJinhaJang(color)
Then run, e.g.:
    python3 omok.py 3 1 1      (agent as black vs RandomPlayer, 1 minute each)

take_turn(board, time) follows the course interface: board is a 19x19 list
(-1 empty, 0 black, 1 white) and is never modified; time is the remaining
time in milliseconds (-1 = no limit); it returns (row, col).

3. LLM / AI usage declaration
AI tool: Claude Code (Anthropic), Claude Pro plan   (TODO: add other members' AI tools)
How it was used:
- Designing the agent architecture together (search algorithm, evaluation,
  time management, test and tuning workflow).
- Writing the agent code (omok-agent/), the development tools (headless match
  runner, regression gate, self-play tuning script) and the tests. Code
  written by the LLM is marked with comments at the top of each file.
- The evaluation weights were tuned by our self-play tuning script.
All prompts and responses are included in llm-usage/.

4. Acknowledgments
- RandomPlayer and SimplePlayer (course-provided) were used as test opponents.
- Our Project 1 game infrastructure (team JRM) was used for local testing.
(TODO: add anything else used)

5. Other notes
Algorithm summary: alpha-beta (negamax) search with iterative deepening, a
transposition table, threat-based forced-move pruning (block a five or
capture to break it), a continuous-four (VCF) win search, and an incremental
line-pattern evaluation that follows the exact-five and capture rules of
Omok++. Time per move is a share of the remaining clock with a fixed reserve.
