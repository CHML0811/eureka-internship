# Eureka Internship — AI-G Data Prototypes

Private-lane prototypes for document understanding, chart routing, and
text-to-Cypher KYC graph queries (Projects 7–9).

## Repository layout

| Path | Contents |
|------|----------|
| `eureka_internship/` | Runnable Python packages (`doc_router`, `chart_router`, `kyc_agent`) |
| `project_*_*/INSTRUCTIONS.md` | Original internship task briefs |
| `EUREKA_MASTER_CONTEXT.md` | Architecture and privacy constraints |
| `COWORK_SETUP_GUIDE.md` | Environment setup notes |

## Quick start

```bash
cd eureka_internship
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional: AuraDB credentials for live Neo4j
.venv/bin/python -m pytest -q
```

On Apple Silicon, if Terminal runs under Rosetta, prefix Python with `arch -arm64`.

See `eureka_internship/README.md` and `eureka_internship/kyc_agent/README.md`
for demos, AuraDB setup, and package-specific docs.

**Never commit `.env`.** Synthetic demo data only — no real KYC or PII in AuraDB Free.
