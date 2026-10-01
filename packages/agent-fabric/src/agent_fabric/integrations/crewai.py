"""CrewAI integration: map an agent tree onto a hierarchical Crew.

* the root supervisor becomes CrewAI's ``manager_agent`` (Process.hierarchical);
* each direct sub-agent becomes a CrewAI agent whose only tool runs the *fabric* agent
  (so nested supervisors, pipelines, budgets, validation and tracing still apply at any depth);
* statistics/pipelines are never computed by CrewAI itself.

    crew, ctx = build_crew(fabric, "How do treatments affect yield?", inputs={"data": df})
    crew.kickoff();  ctx.blackboard / ctx.trace hold the fabric side of the run
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..errors import AgentConfigError, ErrorDetail, MissingOptionalDependency
from ..llm.prompts import compact


def _crewai() -> Any:
    try:
        import crewai
    except ImportError as exc:  # pragma: no cover
        raise MissingOptionalDependency("crewai", "crewai") from exc
    return crewai


def build_crew(
    fabric: Any, instruction: str, inputs: dict[str, Any] | None = None, root: str | None = None
) -> tuple[Any, Any]:
    crewai = _crewai()
    from crewai.tools import BaseTool

    from ..agents.runtime import AgentTask, Budget, RunContext

    roots = [root] if root else fabric.config.roots()
    root_agent = fabric.build(roots[0])
    if not root_agent.children:
        raise AgentConfigError(
            "CrewAI mapping needs a supervisor root",
            [ErrorDetail(loc=("root",), type="not_a_supervisor", msg=f"'{root_agent.name}' has no sub-agents")],
        )
    ctx = RunContext(
        session_id="crewai",
        budget=Budget(fabric.config.budget),
        memory=fabric.memory,
        blackboard=dict(inputs or {}),
        input_keys=list(inputs or {}),
    )
    s = fabric.config.llm

    def llm(spec: Any) -> Any:
        return crewai.LLM(
            model=f"openai/{fabric.model_for(spec)}",
            base_url=s.base_url,
            api_key=s.api_key,
            temperature=spec.temperature if spec.temperature is not None else s.temperature,
        )

    class RunInput(BaseModel):
        instruction: str = Field(description="what this agent should do")

    def make_tool(child: Any) -> Any:
        class FabricAgentTool(BaseTool):
            name: str = f"run_{child.name}"
            description: str = f"Run the '{child.name}' agent ({child.spec.card}). Returns status, summary and output."
            args_schema: type[BaseModel] = RunInput

            def _run(self, instruction: str) -> str:
                res = child.run(
                    AgentTask(instruction=instruction, inputs=list(ctx.input_keys)), ctx, root_agent.name, 1
                )
                return f"[{res.status}] {res.summary}\n{compact(res.output, max_chars=4000)}"

        return FabricAgentTool()

    workers = [
        crewai.Agent(
            role=c.spec.role,
            goal=c.spec.goal,
            backstory=c.spec.backstory or c.spec.card,
            llm=llm(c.spec),
            tools=[make_tool(c)],
            allow_delegation=False,
            verbose=False,
        )
        for c in root_agent.children.values()
    ]
    rs = root_agent.spec
    manager = crewai.Agent(
        role=rs.role, goal=rs.goal, backstory=rs.backstory or rs.card, llm=llm(rs), allow_delegation=True, verbose=False
    )
    task = crewai.Task(
        description=f"{instruction}\n\nAvailable inputs: {sorted(ctx.blackboard)}",
        expected_output="A concise, well-grounded answer that cites the sub-agents' results",
    )
    crew = crewai.Crew(
        agents=workers, tasks=[task], manager_agent=manager, process=crewai.Process.hierarchical, verbose=False
    )
    return crew, ctx


__all__ = [
    "build_crew",
]
