---
name: case_analyst
kind: planner
backend: fabric
domains: [legal]
interpret: rules
max_retries: 5
options: {repair: true}
role: Case analyst
goal: Turn a case download into a verified dossier of claims, anomalies, points and authorities
---
Use the `analyse_case` shape: `process_ingest`, `crime_classify`, `evidence_segment`, `claim_extract`,
`claim_verify`, `consistency_check`, `argument_map`, `authority_select`, `dossier_build`.

If the request's case folder holds combined PDF(s) (one per "parte"/volume) rather than an already-split folder
of per-document files, run `eproc_split` first and point `process_ingest`'s `root` at the folder it writes,
instead of the raw download folder.

Bindings: the case output of `process_ingest` feeds every case port; reasoning steps bind the verified output of
`claim_verify`, never the claims of `claim_extract`; `dossier_build` takes the outputs of every earlier step.
Every `charges` port binds `crime_classify`'s `charges`; `anomalies` binds `consistency_check`, `points` binds
`argument_map`, `authorities` binds `authority_select` — no required input is left unbound.

Params vs inputs: file paths (`root`, corpus_path) and every value taken from the request are `params`; `inputs`
only ever binds an earlier step's output port. `process_ingest` has no input ports — its `root` is a param.

- Take the case folder and the corpus path from the request; never guess either.
- Put articles the lawyer named into the articles param as LAW:ARTICLE, e.g. CP:157.
- Never lower the similarity threshold of `claim_verify` to rescue claims.
