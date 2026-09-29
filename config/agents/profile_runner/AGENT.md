---
name: profile_runner
kind: pipeline
pipeline: exploratory_analysis
inputs: [data]
options:
  params: {features: [nitrogen, phosphorus, potassium, ph, rainfall]}
role: Multivariate profiler
description: Deterministic PCA + k-means profile of the plots on soil and weather variables.
---
Runs the `exploratory_analysis` pipeline with a fixed feature set. No LLM is involved.
Change the features in the frontmatter, not here.
