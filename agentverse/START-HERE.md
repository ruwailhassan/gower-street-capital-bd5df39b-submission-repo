# AgentVerse: drop this folder into your project

## For participants

1. Extract the download. You get one folder named **agentverse**. If your computer calls it `agentverse 2` or similar, that is fine.
2. Drag that whole folder into your project folder using Finder or File Explorer.
3. Open the project in Antigravity and choose a prompt.

**Test your own finance project:**

> Read agentverse/START-HERE.md and use finance-test to test my finance project. Work out what it does, connect its actual code, practise on 25 cases, then run a hidden challenge. Show me what passed, what failed and what wasn't tested. Handle the setup for me.

Practice runs are for fixing bugs: their answer files sit on disk, so their scores prove nothing. **Challenge** runs build hidden cases in memory after your code is fixed. Quote those. Trading ideas can also run on **real Binance price history** (`real-markets`) or a **live forward test**, both needing internet. You can request **250 standard** or **2,500 stress** practice cases instead, or another number up to 10,000. Each case contains several payments, transactions or prices. Antigravity chooses suitable data for your idea and prepares project-specific cases when needed. Testing a kit example does not count as testing your submission.

**Explore examples before choosing an idea:**

> Read agentverse/START-HERE.md and start the finance playground. Show me the results first, explain them simply, then help me choose something to build. Handle the setup for me.

You can also open `agentverse/finance/example-results/DEMO-RESULTS.md` immediately to see the generated sample results before setup.

**Review and push team changes:**

> Read agentverse/START-HERE.md and use review-and-push to check my changes and push them to my team's GitHub repository. Ask for the team repository link if needed and a one-sentence explanation for the commit message. Handle setup and sign-in, then give me the exact next step for a teammate to review the changes.

You do not need to run an installer, create hidden folders or enter terminal commands. Keep the whole `agentverse` folder together. Finance skills share the bundled `finance` data and tools.

```text
your-project/
├── agentverse/
│   ├── START-HERE.md
│   ├── finance/             # demo, data, tests, optional local MCP
│   └── skills/
│       ├── finance-data/
│       ├── finance-build/
│       ├── finance-test/
│       └── review-and-push/
└── your project files
```

For a review without uploading, send: **Read agentverse/START-HERE.md and use review-and-push to review this project without publishing.**

The finance generator, project test runner, demo and calculation tests use Python 3.9+ with no extra packages, account or API key. The optional MCP connector uses a free SDK and a newer runtime. Antigravity handles permitted setup. Data and tools have no paid feed or hosting dependency (the optional real-market and live modes download free Binance Vision public data); use the event-provided Argon access for the agent. If model quota runs out, local examples and tests still work. The code never buys credits or enables billing.

Review-and-push may also need Git, Gitleaks and GitHub CLI. Antigravity checks existing tools and handles permitted official setup; it may need your approval for software installation. It must never skip secret scanning because a tool is missing.

Complete account sign-in yourself in the browser. Never paste API keys, passwords or GitHub tokens into chat. Use your team's shared repository. A successful publishing run ends with the uploaded branch/commit, the commit message and a clear next step for teammate review, normally through a pull request.

## Instructions for Antigravity

The user's message determines whether publication is authorised. This guide alone does not authorise a push.

1. Locate this kit directory (the folder holding this file and `finance/bench.py`; its name may be `agentverse 2` or similar, so always quote paths) and the participant's actual project root. Review the project containing the kit, not just the kit's files. Preserve unrelated work.
2. Route by the user's intent: finance demo/data starts with `skills/finance-data/SKILL.md`; building uses `finance-build`; testing uses `finance-test`; GitHub review/publishing uses `review-and-push`. Read only the relevant entry point and its needed resources. Explicit reading works before automatic discovery; do not require an installer or restart first. A finance request does not imply permission to publish.
3. For future discovery, copy the selected complete skill directories into `<project-root>/.agents/skills/<skill-name>/` where permitted, using native file tools. When starting finance, copy all three finance skill folders so the next steps can be discovered too. Preserve different existing versions and ask before replacing them; reuse identical copies. Keep shared `finance` resources in the original `agentverse` folder. If discovery setup fails, explain and continue by explicitly reading the bundled skill where allowed. Never modify a global installation without the user's instruction.
4. Use existing tools first and perform permitted official setup yourself. Skill-folder copying needs no runtime. Finance's initial demo and offline tests require only Python 3.9+; do not make first results wait for MCP setup. Review preflight additionally needs Git and Gitleaks v8.30.1+ in the v8 series; publishing needs GitHub CLI. Respect host approvals/network restrictions. If a step genuinely requires the participant, give one small next action.
5. Follow the selected skill to a visible verified result. For finance testing, inspect and connect the actual submission through the adapter in `finance/TESTING.md`, practise with generated cases, then run `bench.py challenge` and open its report. Only challenge (or live) results may be presented as results. Baseline/demo runs must be labelled as kit checks. Show failures and untested requirements plainly and help the beginner take one next step. Keep data/tools free and use their supplied Argon access without enabling billing or paid fallbacks. For review-and-push, establish the team repository, get a brief change explanation for the commit, run checks, complete the requested push when safe and provide the exact teammate review action. Stop publication on unresolved credentials or incomplete essential scanning.

Antigravity automatically discovers project skills at `.agents/skills/<skill-name>/SKILL.md`. It also supports `~/.gemini/config/skills/` for global skills. The copy in step 3 provides project discovery for later conversations; the user can start a fresh conversation if the skill list is stale.

## For organisers (judging the finance track)

Run `finance/bench.py seal` before judging and post the commitment. Then run each team with `challenge --seed-prompt --team "<name>"`, so every team gets different hidden cases from one sealed seed, and publish the seed after awards. Full procedure and its limits: `finance/TESTING.md`, "Organiser procedure".

Source: [Antigravity skill discovery](https://antigravity.google/docs/skills).
