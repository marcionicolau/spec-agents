# Error model

| Category          | Class                                           | Recoverable    | Typical fix path                    |
| ----------------- | ----------------------------------------------- | -------------- | ----------------------------------- |
| `spec`            | `SpecError`                                     | no             | developer fixes spec/code           |
| `plan`            | `PlanValidationError`                           | yes            | planner self-correction             |
| `params` / `data` | `ParamsValidationError` / `DataValidationError` | yes            | planner, `LLMParamRepairer`         |
| `execution`       | `ComponentExecutionError`                       | per hint table | report                              |
| `llm_output`      | `LLMOutputError`, `CorrectionExhausted`         | yes / no       | retry loop                          |
| `dependency`      | `DependencyError`                               | no             | skip dependents, fallback backend   |
| `agent`           | `AgentConfigError` / `DelegationError`          | no / yes       | fix config / router self-correction |
| `budget`          | `BudgetExceeded`                                | no             | stop delegating; synthesis skipped  |

Rules: set `loc` (path into plan/params/config), stable snake_case `type`, factual `msg`, actionable `hint`
(`suggest()` for names). Don't create cascades: a port with a bad reference counts as bound.
Nested pipeline errors are re-located as `pipeline.<inner_step>.…`.

---
