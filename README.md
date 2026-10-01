# agent-fabric

Núcleo **genérico** para pipelines definidos por spec e **árvores de agentes com sub-agentes**, sobre LLMs
locais (Ollama via **LiteLLM proxy**), integrando **Pydantic/PydanticAI**, **DSPy**, **CrewAI** e **LangChain**.
A estatística virou um _domain pack_ (`stat_fabric`); `examples/domains/text_pack` prova que o núcleo
serve para qualquer domínio.

> LLM planeja, delega, repara e interpreta; **quem calcula é sempre código determinístico**.

## Specs em Markdown: contrato + orientação

Tudo é um arquivo Markdown com _frontmatter_ YAML:

- **frontmatter = contrato**, validado pelo Pydantic;
- **corpo = orientação em linguagem natural**, carregada nos prompts só quando necessária.

| Arquivo                         | O que declara                                                                                                                                           | Validado quando                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `skills/<nome>/SKILL.md`        | **componente** (portas tipadas, params) ou **pipeline** (`kind: pipeline`, DAG com `$params`) + seções _When to use_, _Interpreting_, _Common mistakes_ | no registro (contrato spec ↔ código, referências, tipos)           |
| `config/agents/<nome>/AGENT.md` | **agente** (tipo, sub-agentes, modelo…); o corpo é o _system prompt_                                                                                    | antes de rodar (árvore inteira: referências, ciclos, profundidade) |
| `config/fabric.md`              | `root`, `budget`, `llm`                                                                                                                                 | ao carregar                                                        |

Onde a orientação entra nos prompts:

- **catálogo do planner:** `description` + 1º parágrafo de _When to use_;
- **intérprete:** a seção _Interpreting_;
- **reparo de parâmetros e feedback de planos rejeitados:** a seção _Common mistakes_;
- **pasta `references/`:** só é lida sob demanda;
- **`runtime: prompt`:** a seção _Instructions_ é o template do prompt — o SKILL.md sozinho vira um
  componente, sem classe Python (veja abaixo).

## Domínios sem código (`runtime: prompt`)

Um SKILL.md com `runtime: prompt` é um componente completo — sem pacote Python, sem `register()`:

```markdown
---
name: summarize_notes
version: 1.0.0
domain: notes
description: Condense um transcript em um resumo breve.
runtime: prompt
params:
  { tone: { description: Tom do resumo, required: false, default: neutral } }
inputs: { transcript: { type: text, constraints: { min_chars: 20 } } }
outputs: { summary: { type: text } }
---

# Summarize notes

## Instructions

Escreva um resumo {params.tone} deste transcript.

{inputs.transcript}
```

- O template aceita `{params.<nome>}`, `{inputs.<porta>}` e `{objective}` — validados contra o contrato
  no registro; chaves literais escapam como `{{ }}`.
- Com `outputs` declarados o modelo responde um objeto JSON validado e auto-corrigido; sem `outputs`, o
  texto livre é a saída. Portas de saída são só `text`/`json`/`number`/`any` — um passo prompt nunca
  alimenta uma porta `dataframe`, então a fronteira de cálculo determinístico continua valendo.
- `prompt: {model, temperature, grounding}` no frontmatter sobrepõe os defaults do agente; `grounding`
  (ligado por padrão) rejeita números inventados na saída.
- `config/fabric.md` aceita `skill_dirs: [./skills]` para carregar specs relativos ao diretório do config —
  é assim que `config/notes/` roda 100% em Markdown.
- Scaffold: `python -m agent_fabric.scaffold prompt <nome> --dir <pack>/skills --domain <domínio>`.

## Agentes com sub-agentes

```
research_lead (supervisor, router)           fallback: rules
├── stats_team (supervisor, sequential)
│   ├── statistician (planner, domínio statistics)   fallback: stats_rules
│   └── methods_reviewer (llm, saída estruturada Review, grounding)
├── profile_runner (pipeline: exploratory_analysis)
└── notes_digest (pipeline: document_digest)          ← domínio texto
```

- **router**: o LLM gera um plano de delegação validado (agentes existentes, chaves do blackboard, `@d1`
  para passar saídas, dependências acíclicas) com auto-correção; dependentes de falhas são pulados.
- **sequential**: repassa a saída de cada filho ao próximo; **pydantic_ai**: delega via _tool calls_.
- **Orçamento** por execução (profundidade, execuções, delegações, chamadas LLM), **trace** com caminhos
  (`research_lead/stats_team/statistician`), **memória por agente**, **fallbacks** em build e runtime.
- **CrewAI**: `build_crew()` mapeia a árvore para um crew hierárquico cujas ferramentas executam os agentes da fábrica.

## Outros domínios

| Domínio     | Pacote               | Agentes                                                                                  | O que faz                                                                                                                           |
| ----------- | -------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `lakehouse` | `packages/lakehouse` | `config/lakehouse` (`lakehouse_team`, `dag_engineer`, `dag_reviewer`, `schema_designer`) | Gera DAGs do Airflow que carregam CSV, JSON, XLSX, API ou ferramenta MCP em tabelas Trino/Iceberg nas camadas bronze, silver e gold |
| `coworker`  | `packages/coworker`  | `config/coworker` (`pair_programmer`, `context_scout`, `code_critic`, `patch_author`)    | Programação em par: escolhe o contexto dentro de um orçamento de tokens, revisa o código e valida propostas de patch                |
| `notes`     | — _(só Markdown)_    | `config/notes` (`note_taker`)                                                            | Demo code-free: resumo, extração de ações e digest de reunião via `runtime: prompt`                                                 |

**Lakehouse.** Pipeline `ingest_to_lakehouse`: `source_inspect` → `medallion_plan` → `airflow_dag_render` → `dag_check`.
O código do DAG vem de um modelo estático e nenhum valor é interpolado em código ou SQL; credenciais ficam em
conexões do Airflow. O `batch_id` deriva do `run_id`, então um retry da mesma execução recarrega o próprio lote
sem duplicar linhas. APIs podem ser paginadas (`next_link`, `cursor` ou `page`; exceder `max_pages` falha a execução
em vez de carregar dados parciais) e a carga pode ser incremental (`watermark_column`, com `merge`). Sem LLM, direto de um JSON de parâmetros:

```bash
python -m lake_fabric.generate params.json --sample records.json --out dags
# params.json: {"source": {"type": "csv", "path": "/data/orders.csv"}, "dag_id": "ingest_orders",
#               "catalog": "lake", "table": "orders", "business_keys": ["order_id"]}
```

**Coworker.** Pipelines `improve_code` (índice, contexto, pacote e revisão estática) e `propose_patch` (edições
aplicadas só em memória, restritas ao contexto escolhido, com diff unificado). Nada é gravado em disco.
A escolha de contexto é medida: `python -m coworker_fabric.evals --root .` roda casos rotulados (sem LLM) e mostra
recall, precisão e tokens; arquivos grandes entram só com os símbolos relevantes.

```bash
python -m agent_fabric.lint --domains lake_fabric.domain:register --agents config/lakehouse \
       --schemas lake_fabric.schemas:SCHEMAS --strict
python -m agent_fabric.lint --domains coworker_fabric.domain:register --agents config/coworker \
       --schemas coworker_fabric.schemas:SCHEMAS --strict
python examples/run_evals.py --domain lakehouse --mode live     # regressão dos planners (proxy no ar)
python examples/run_evals.py --domain coworker --mode live
```

## Manutenção

- `python -m agent_fabric.lint … --strict`: detecta divergência entre texto e contrato (identificadores
  inexistentes, seções faltando, links quebrados, textos longos demais para modelos pequenos, sub-agentes
  não mencionados) e valida a árvore de agentes.
- `python examples/run_evals.py --mode live`: regressão do planner. Rode ao mudar o texto de uma skill
  ou trocar modelos, porque texto muda comportamento sem mudar código.
- `python -m agent_fabric.scaffold skill|pipeline|agent <nome> --dir …`: cria arquivos com as seções canônicas.

## CLI `agent-fabric`

Interface unificada (rich: cores, tabelas, view ao vivo com spinner; `--plain` ou não-TTY → saída em texto):

```bash
agent-fabric catalog --skills config/notes/skills            # tabela: nome, kind, domínio, params, portas
agent-fabric agents config/notes                             # árvore de agentes + validação
agent-fabric lint --agents config --domains stat_fabric.domain:register --strict   # tabela colorida de issues
agent-fabric run config/notes "Resuma a reunião" --input transcript=reuniao.txt    # visão ao vivo no TTY
```

`--input` aceita `nome=caminho` (`.txt`/`.md` → texto, `.json` → objeto, `.jsonl` → linhas,
`.csv`/`.parquet`/`.xlsx` → dataframe).
`run` mostra cada agente com status e conta de chamadas LLM em tempo real e, com `--plain`, imprime o
mesmo relatório Markdown de `render_markdown`.

## Uso

```bash
uv sync --all-packages --group dev                 # workspace uv (packages/*); versionar o uv.lock
pytest -q                                          # suíte offline
python examples/run_demo.py --mode scripted        # erros simulados de modelo pequeno + auto-correção
python examples/run_demo.py --mode offline         # proxy fora do ar: degradação controlada
litellm --config config/litellm_config.yaml --port 4000 && python examples/run_demo.py --mode live
```

```python
from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.report import render_markdown
from stat_fabric.domain import register as stats
from stat_fabric.schemas import Review

fabric = AgentFabric(build_registry([stats, my_pack.register]), AgentsConfig.load("config"))
fabric.register_schema("Review", Review)
report = fabric.run("Como os tratamentos afetam o rendimento?", {"data": df, "notes": texto}, session_id="ensaio-2026")
print(render_markdown(report))
```

Governança para assistentes de código: **[CLAUDE.md](CLAUDE.md)**.
