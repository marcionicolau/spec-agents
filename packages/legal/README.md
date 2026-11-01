# spec-agents-legal

Legal domain pack for [agent-fabric](https://github.com/marcionicolau/spec-agents): pairs with a lawyer on a
**criminal case** downloaded from eproc and finds the best-sustained arguments for a petition.

> LLMs extract facts and write; **rules decide** what is contradictory, what is weak and what may be argued.

## Two invariants, enforced by code

1. **Every claim cites the record** as `ev12/DEPOIM1 p.3 l.10-14`. `claim_verify` re-reads those lines and drops
   claims whose quote is not there; `rebuttal_check` drops rebuttal points whose locators do not exist.
2. **Every result explains itself**: charges, anomalies, points, authorities and rebuttal points carry a
   `rationale` paragraph saying why that path was chosen.

## Pipeline `analyse_case`

| Step | Component | Kind | What it does |
|---|---|---|---|
| 1 | `process_ingest` | code | eproc files → `case` (doc ids, phase, pages of numbered lines) |
| 2 | `crime_classify` | code | articles in the denúncia → charges with elements to prove (ontology) |
| 3 | `evidence_segment` | code | line-numbered bundle for the extractor |
| 4 | `claim_extract` | **prompt** | LLM: claims with speaker, role, party, fact slots, elements, locator |
| 5 | `claim_verify` | code | quality control: quote must be at the cited lines |
| 6 | `consistency_check` | code | NeSy rules: `slot_conflict`, `retraction`, `missing_element`, `inquiry_only`, `single_source`, outlier speakers |
| 7 | `argument_map` | code | strong/weak points per side, refutation targets |
| 8 | `authority_select` | code | BM25 over a **curated** JSONL corpus; no authority → `needs_research` |
| 9 | `dossier_build` | code | everything the writer and checker need, without document text |

Then `rebuttal_writer` (LLM, `Rebuttal` schema) drafts, and `check_rebuttal` gates the draft.

## Agents

```
case_counsel (supervisor, router)
├── case_analyst (planner, legal)       analyse_case
├── rebuttal_writer (llm, Rebuttal)     argues only from the dossier
└── quality_controller (pipeline)       check_rebuttal
```

## Use

```bash
pip install spec-agents-core "spec-agents-legal[pdf]"
export LEGAL_ALLOWED_ROOTS=/cases
agent-fabric run packages/legal/config \
  "Defesa: encontre os pontos fracos da acusação. Caso em /cases/5001234, corpus /cases/authorities.jsonl"
python -m agent_fabric.lint --domains legal_fabric.domain:register --agents packages/legal/config \
       --schemas legal_fabric.schemas:SCHEMAS --strict
```

## Caveats

- `data/authorities.sample.jsonl` holds **summaries** for tests; replace it with authorities your team has checked
  against the official text. The confidence gate is only as good as that corpus.
- Case records hold personal and sometimes sealed data (LGPD, segredo de justiça): keep the LLM local.
- Output is a draft for the lawyer's review. Nothing is filed.
