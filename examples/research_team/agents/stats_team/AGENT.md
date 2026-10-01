---
name: stats_team
kind: supervisor
strategy: sequential
synthesize: false
sub_agents: [statistician, methods_reviewer]
role: Statistics team
description: Statistical analysis of tabular trial data (regression, ANOVA, time series, PCA, clustering) with a methods review.
---
Run the analysis first (`statistician`), then have it reviewed (`methods_reviewer`).
The review sees the statistician's full output. Its verdict decides how strongly the lead may state conclusions.
