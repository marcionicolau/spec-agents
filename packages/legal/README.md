# spec-agents-legal

Legal domain pack for [agent-fabric](https://github.com/marcionicolau/spec-agents): pairs with a lawyer on a
**criminal case** downloaded from eproc and finds the best-sustained arguments for a petition.

> LLMs extract facts and write; **rules decide** what is contradictory, what is weak and what may be argued.

## Two invariants, enforced by code

1. **Every claim cites the record** as `Evento 12, DEPOIM1 p.3 l.10-14`. `claim_verify` re-reads those lines and drops
   claims whose quote is not there; `rebuttal_check` drops rebuttal points whose locators do not exist.
2. **Every result explains itself**: charges, anomalies, points, authorities and rebuttal points carry a
   `rationale` paragraph saying why that path was chosen.

## Pipeline `analyse_case`

| Step | Component | Kind | What it does |
|---|---|---|---|
| 0 | `eproc_split` | code | *optional pre-step*: a combined download PDF (one per "parte"/volume) → one file per event |
| 1 | `process_ingest` | code | eproc files → `case` (doc ids, phase, pages of numbered lines) |
| 2 | `crime_classify` | code | articles in the denúncia → charges with elements to prove (ontology) |
| 3 | `evidence_segment` | code | line-numbered bundle for the extractor |
| 4 | `claim_extract` | **prompt** | LLM: claims with speaker, role, party, fact slots, elements, locator |
| 5 | `claim_verify` | code | quality control: quote must be at the cited lines |
| 6 | `consistency_check` | code | NeSy rules: `slot_conflict`, `retraction`, `missing_element`, `inquiry_only`, `single_source`, outlier speakers |
| 7 | `argument_map` | code | strong/weak points per side, refutation targets |
| 8 | `authority_select` | code | BM25 over a **curated** JSONL corpus; no authority → `needs_research` |
| 9 | `dossier_build` | code | everything the writer and checker need, without document text |

Then `rebuttal_writer` (LLM, `Rebuttal` schema) drafts, and `check_rebuttal` gates the draft. Every component takes
a `lang` param (`"pt-BR"` by default, or `"en-US"`) for its rationale and warning text; `analyse_case` and
`check_rebuttal` forward a single pipeline-level `lang` param to every step that needs it.

## Agents

```
case_counsel (supervisor, router)
├── case_analyst (planner, legal)       analyse_case
├── rebuttal_writer (llm, Rebuttal)     argues only from the dossier
└── quality_controller (pipeline)       check_rebuttal
```

## Use

`rebuttal_writer` declares `output_schema: Rebuttal`, so `--schemas legal_fabric.schemas:SCHEMAS` is required on
every `agent-fabric run`/`lint` call against this pack — without it the tree fails to load at all
(`unknown_schema ... 'Rebuttal' is not registered`), not just the step that needs it.

Already-split case folder (one PDF/TXT per document, named like `EVENTO12_DEPOIM1.pdf`):

```bash
pip install spec-agents-core spec-agents-legal
export LEGAL_ALLOWED_ROOTS=/cases
agent-fabric run packages/legal/config --schemas legal_fabric.schemas:SCHEMAS \
  "Defesa: encontre os pontos fracos da acusação. Caso em /cases/5001234, corpus /cases/authorities.jsonl"
```

A real eproc download instead arrives as one combined PDF per "parte" (volume), not pre-split - run `eproc_split`
first to get a folder `process_ingest` can read (needs the `pdf` extra: `pip install "spec-agents-legal[pdf]"`):

```bash
export LEGAL_ALLOWED_ROOTS=/cases
agent-fabric run packages/legal/config --schemas legal_fabric.schemas:SCHEMAS \
  "Defesa: analise o caso em /cases/5001234/download (download combinado; use eproc_split, saída em
   /cases/5001234/split), denúncia por roubo (CP:157). Corpus /cases/authorities.jsonl"
```

`case_analyst`'s planner decides on its own whether `eproc_split` is needed, from how the request describes the
case folder - see its AGENT.md. To split by hand instead of through the planner (useful to inspect
`by_code`/`n_no_document` before the rest of the analysis runs), call the pack's CLI - no LLM involved:

```bash
python -m legal_fabric.split /cases/5001234/download /cases/5001234/split
# {"n_volumes", "n_written", "n_no_document", "n_no_text", "by_code", "warnings"}
```

Worked example — a real download in `~/Downloads/eproc`, where eproc dropped the volume
`RS-50010072720268210112-2026-11-1-16-29-1250010072720268210112_PARTE_1.PDF` (one combined PDF per "parte"; the
`.PDF` suffix is matched case-insensitively, and further `PARTE_N` volumes in the same folder are picked up too),
split in place:

```bash
LEGAL_ALLOWED_ROOTS=$HOME/Downloads/eproc \
  python -m legal_fabric.split ~/Downloads/eproc ~/Downloads/eproc/split
# {"n_volumes": 1, "n_written": 110, "n_no_document": 146, "n_no_text": 0, "by_code": {...}}
```

On a ~260-event case that prints `n_volumes=1, n_written=110, n_no_document=146, n_no_text=0` plus a `by_code`
histogram: one `EVENTO<n>_<CODE>.txt` per event, while the no-document events are pure docket movements (deadline
and certificate entries) that carry no PDF and are counted, not errors. If the result also warns about `OUTRO`
documents, open a few `EVENTO*_OUTRO.txt` — they are types `DOC_TYPE_PATTERNS` in `ontology.py` does not
recognise yet (e.g. MP letterhead, eproc e-mail notices); the table is meant to grow, and `process_ingest` still
ingests them as kind `outro` meanwhile. Point `process_ingest`'s `root` — or the planner's case folder — at
`split/` next.

Full run on that split case (letter-suffixed articles are passed by hand in the request, as in the caveats below;
`--out`/`--trace-out` keep the report and the event trace):

```bash
LEGAL_ALLOWED_ROOTS=$HOME/Downloads/eproc uv run agent-fabric run packages/legal/config \
  "Defesa: analise o caso em $HOME/Downloads/eproc/split (download eproc já separado por evento via eproc_split). \
   Artigos imputados: CP:217-A c/c art. 226, II, na forma do art. 71 (duas vezes); CP:213 na forma do art. 71; \
   CP:147-A (três vezes); art. 24-A da Lei 11.340/2006. \
   Corpus de jurisprudência em packages/legal/data/authorities.sample.jsonl" \
  --schemas legal_fabric.schemas:SCHEMAS --out build/run/legal_case.md --trace-out build/run/legal_case.jsonl
```

```bash
python -m agent_fabric.lint --domains legal_fabric.domain:register --agents packages/legal/config \
       --schemas legal_fabric.schemas:SCHEMAS --strict
```

## Caveats

- `data/authorities.sample.jsonl` holds **summaries** for tests; replace it with authorities your team has checked
  against the official text. The confidence gate is only as good as that corpus.
- Crime types and their elements come from `src/legal_fabric/data/crimes.yaml`. Add a crime type, or point
  `crime_classify`'s `crimes_path` param at your own copy, without touching code — see the comments at the top of
  that file for the format.
- Automatic article detection (`ontology.ARTICLE_RE`) only captures digits, so a letter-suffixed article (e.g.
  `217-A`) is detected as the digits alone — a different, possibly unrelated article. Pass it by hand instead:
  `crime_classify`'s `articles` param, e.g. `["CP:217-A"]`.
- Case records hold personal and sometimes sealed data (LGPD, segredo de justiça): keep the LLM local.
- Output is a draft for the lawyer's review. Nothing is filed.
