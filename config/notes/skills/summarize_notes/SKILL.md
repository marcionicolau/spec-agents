---
name: summarize_notes
version: 1.0.0
domain: notes
category: text
description: Condense a meeting transcript into a short faithful summary.
runtime: prompt
prompt: {grounding: true}
params:
  tone: {description: "writing tone for the summary", required: false, default: neutral, example: executive}
inputs:
  transcript: {type: text, description: the meeting transcript, constraints: {min_chars: 20}}
outputs:
  summary: {type: text}
---
# Summarize notes

## When to use
First step for any digest: produces a faithful, compact `summary` of the transcript before
anything is extracted from it.

## Instructions
Write a {params.tone} summary of the meeting below, at most 120 words. Cover what was
discussed and what was agreed; do not add anything that is not in the transcript.

Objective: {objective}

Transcript:
{inputs.transcript}

## Interpreting
`summary` is plain prose; treat it as a paraphrase, not a source of new facts.

## Common mistakes
- Inventing attendee names or dates that are not in the transcript.
- Restating the whole transcript instead of compressing it.
