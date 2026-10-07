---
name: summarize_text
version: 1.0.0
domain: text
category: generation
description: Faithful LLM-written summary of a document, steered by the run objective.
runtime: prompt
prompt: {grounding: true}
params:
  max_words: {description: "summary length cap", required: false, default: 150, example: 80}
inputs:
  text: {type: text, description: document to summarise, constraints: {min_chars: 20}}
outputs:
  summary: {type: text}
---
# Summarize text

## When to use
Last step of a digest: writes a short, faithful `summary` that answers the run
objective — e.g. what was decided and who owns what in a chat export.

## Instructions
Write a faithful summary of the document below, at most {params.max_words} words,
answering this objective: {objective}

Cover only what the document states. When the objective asks about decisions or
owners, name only people and facts that appear in the text; ignore timestamps,
media placeholders and other formatting noise. Do not add counts, dates, names or
facts that are not written in the document.

Document:
{inputs.text}

## Interpreting
`summary` is grounded prose; treat it as a paraphrase, not a source of new facts.

## Common mistakes
- Inventing names, decisions or dates absent from the document.
- Ignoring the objective and writing a generic abstract.
