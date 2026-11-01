---
name: eproc_split
version: 1.1.0
domain: legal
category: ingestion
description: Split one or more combined eproc download PDFs ("parte" volumes) into one file per event.
runtime: code
params:
  root:
    description: folder with the downloaded combined PDF(s), one per "parte"/volume
    example: /cases/5001234-56.2025.8.21.0021/download
  out_dir:
    description: folder to write one EVENTO<n>_<code>.txt file per event; point process_ingest's root here next
    example: /cases/5001234-56.2025.8.21.0021/split
  separator:
    description: marker text eproc prints on each generated separator page; override if a court phrases it differently
    example: "PÁGINA DE SEPARAÇÃO"
  pdf_codes:
    description: event codes also saved as real PDFs (default ["LAUDO"] - laudos carry signatures/stamps text loses)
    example: ["LAUDO"]
  pdf_out:
    description: folder for those PDFs; defaults to <root>/laudos, a folder inside the input directory
    example: /cases/5001234/download/laudos
  lang:
    description: language of warning text, "pt-BR" (default) or "en-US"
    example: pt-BR
inputs: {}
outputs:
  out_dir:
    type: text
    description: the folder written (same value as the out_dir param, for binding convenience)
---
# Eproc split

## When to use
First step when the download is one or more combined PDFs (one per "parte"), not an already-split folder of
per-document files. Run `process_ingest` on `out_dir` next, not on `root`.

## Interpreting
- A real eproc download is mostly docket movements with no attached document (status changes, system
  notifications): `n_no_document` counts them, it is not an error.
- `by_code` counts what was written per code; a large `OUTRO` count means `DOC_TYPE_PATTERNS` in `ontology.py`
  needs another pattern for this court's wording — extend it, the table is deliberately not exhaustive.
- `n_no_text` is a page with no extractable content (e.g. an unconverted audio/video attachment placeholder),
  skipped like a scanned PDF with no text layer.
- The separator-page format (`PÁGINA DE SEPARAÇÃO ... Evento N`) is confirmed from a real TJRS download; it is
  expected, not yet confirmed, to be common to eproc generally. Override `separator` if another court's instance
  phrases it differently rather than assuming it matches.

## Common mistakes
- Running `process_ingest` on `root` (the raw combined PDFs) instead of `out_dir`: it expects one file per
  document, which is exactly what this step produces.
- Treating a large `n_no_document` as a parsing failure: most real events are movements, not documents.
