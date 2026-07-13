# COWORK_SETUP_GUIDE — Eureka Internship Addendum

This is a **second** Cowork project, separate from your `isom4030_startup/` coursework folder. Keep them separate — startup work and deep learning lectures shouldn't share a master context.

## Folder structure
```
eureka_internship/
├── EUREKA_MASTER_CONTEXT.md          ← always loaded first
├── COWORK_SETUP_GUIDE.md             ← this file
├── project_7_doc_understanding/
│   └── INSTRUCTIONS.md
├── project_8_chart_generation/
│   └── INSTRUCTIONS.md
└── project_9_text_to_cypher/
    └── INSTRUCTIONS.md
```

## Setup steps
1. On your computer, create a folder called `eureka_internship/` (anywhere — Desktop, Documents, doesn't matter).
2. Copy all 5 files into the structure shown above.
3. In Claude desktop, switch to Cowork. Create a **new** project called `Eureka Internship` — do not reuse your ISOM4030 project.
4. Link it to the `eureka_internship/` folder.
5. For each of the three projects, open its `INSTRUCTIONS.md` and paste the full content into Cowork's "Project instructions" field. Always keep `[Load EUREKA_MASTER_CONTEXT.md before starting]` at the top.
6. Start with Project 7, Task 1. Say: **"Run Task 1"** and wait. Review the plan Cowork shows before approving. Do not ask Cowork to "do the whole project."

## Execution order (matters)
- **Week 1–2:** Project 7 (Document Understanding Router). Tasks 1–4 are enough to demo.
- **Week 2–3:** Project 8 (Chart Generation Router). Tasks 1–4 are enough to demo; Task 5 if time allows.
- **Week 3–5:** Project 9 (Text-to-Cypher Agent). This is the flagship — finish *all* tasks. Task 7 is the demo you show the CEO.

If your internship is short (4 weeks), cut Task 5 and Task 6 from Project 7, and cut Task 5 from Project 8. Do not cut anything from Project 9.

## Pre-work before you start Task 1 of anything (do this the weekend before)
1. Neo4j GraphAcademy → "Cypher Fundamentals" (free, ~4 hours). Non-negotiable for Project 9.
2. Read the Anthropic docs page on **tool use** and the OpenAI docs page on **structured outputs** — for the *concepts* only (tool schemas, retries, structured JSON). The code you ship calls a self-hosted Llama model, not these APIs — see EUREKA_MASTER_CONTEXT.md §4 for why (short version: real KYC data can't leave Eureka's infrastructure).
3. Skim FATF's "40 Recommendations" executive summary and one Wolfsberg Group FAQ on beneficial ownership. 90 minutes. Domain vocabulary is the cheapest credibility you can buy with this founder.
4. Install: Docker (for Neo4j), Python 3.11+, Node 20+ (for the Project 8 demo UI), AWS CLI configured with a personal sandbox account, **Ollama** (or vLLM) with `llama3.1` and `llama3.2-vision` pulled locally for the self-hosted model lane. No Anthropic/OpenAI API keys are needed for the shipped pipeline.

## Relationship-building rules (this is half the value)
These are not code instructions — they are behavioral rules. Re-read before each week.

1. **Ship one small working thing in the first 2 weeks.** Even if ugly. Credibility compounds from a first artifact, not from a plan.
2. **Write a one-page memo before starting each project**, not just at the end. The CEO is a banker — he will read a pre-memo that asks "here is what I'm going to try and why, do you agree with the framing?" and respond. That response is a relationship-building exchange.
3. **Use domain vocabulary correctly from day 1.** UBO, PEP, EDD, STR, FATF, sanctions screening, adverse media. If you don't know a term, ask. Do not fake it.
4. **Do not ask about equity in week 1.** Do not ask about equity before Project 9 works end-to-end. Earn the conversation first; it is much shorter when you've earned it.
5. **After Project 9 works**, request a 20-minute meeting with the CEO specifically, phrased as: *"I've prototyped something that maps to the AI-G Data roadmap slide. Can I show it to you for 20 minutes and get your reaction to what v2 should do?"* Bring the memo. Bring the screen-share. End by asking what v2 would need to do for him to put it in front of a client. That is the meeting where the relationship inflects.
6. **Only after that meeting, and only if he's engaged**, ask whether there is a path to staying involved beyond the internship — and let him define the shape. Do not show up with a number.

## Why three projects, not one
Project 7 demonstrates you can handle messy real inputs. Project 8 demonstrates you understand the LLM-as-DSL-generator pattern properly (not just Mermaid). Project 9 demonstrates you understand *their product's future* and can build toward it. Together, they are a narrative: ingestion → reasoning → visualization. Each is independently demoable, so if you run out of time on #9 you still have #7 and #8 to show.
