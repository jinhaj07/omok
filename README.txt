CAS 1102 Project 1: Omok++ — Game Agent

1. Team members
Team name: JRM
Number of members: 3
- Member name: Minjun Ryu, Geonwoo Min, Jinha Jang
(TODO: describe each member's role)

2. Running instructions
Python version used: Python 3.13 (standard library only; works on Python 3.8+)
No additional packages are required.

Submitted files:
  smartplayerJRM.py   SmartPlayerJRM (the game agent)
  playerJRM.py        PlayerJRM (copy of the Player base class)

To use it in a game infrastructure, put both files next to omok.py and map
a player code to the agent, e.g. in GameManager:
    from smartplayerJRM import SmartPlayerJRM
    ...
    elif player == 3:
        return SmartPlayerJRM(color)
Then run, e.g.:
    python3 omok.py 3 1 1      (agent as black vs RandomPlayer, 1 minute each)

take_turn(board, time) follows the course interface: board is a 19x19 list
(-1 empty, 0 black, 1 white) and is never modified; time is the remaining
game time in milliseconds (-1 = no limit); it returns (row, col).

3. LLM / AI usage declaration
AI tools: Claude Code (Anthropic), ChatGPT (OpenAI)
(TODO: confirm each member's AI tools)
How they were used:
- Designing the agent architecture together (search algorithm, evaluation,
  time management, test and tuning workflow).
- Writing the agent code, the development tools (headless match runner,
  league and A/B test runners, regression tests) and the tests. Each source
  file states at the top which AI tool wrote or adapted it.
- Analysing lost games and planning the A/B experiments that chose the
  final settings (over 35,000 test games against the team's agents).
All prompts and responses are included in llm-usage/.

4. Acknowledgments
- The final agent (v15) is built on Geonwoo Min's "Hybrid v2" agent, which
  combined ideas from Jinha Jang's v11 engine and from Geonwoo's and Minjun
  Ryu's earlier agents (safety checks, forced-win proofs).
- RandomPlayer and SimplePlayer (course-provided) were used as test opponents.
- Our Project 1 game infrastructure (team JRM) was used for local testing.

5. Other notes
Algorithm summary: principal-variation (negamax) alpha-beta search with
iterative deepening, aspiration windows and a transposition table; tactical
quiescence on fours and forced defences; a continuous-four (VCF) win search
checked by a forcing-move verifier; forced-move handling (block a five, or
capture a pair to break it); and an incremental line-pattern evaluation that
follows the exact-five, overline and pair-capture rules of Omok++, with
per-line caches for speed.
Time management: each move gets a share of the remaining clock (scaled so a
1-minute game uses most of its time), with short caps on the first moves and
a safety margin, so the agent never runs out of time. As white, the first
reply is a knight's move from black's first stone when the clock is short.
