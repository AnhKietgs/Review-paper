"""Factory for lazy, one-role LangGraph subgraphs."""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import evidence_verifier, related_work, scientific_review
from app.agents.ports import LLMPort
from app.agents.schemas import (
    AgentAction, SelectedComparisonOutput, SelectedScientificOutput,
)


class GraphState(TypedDict):
    """Explicit graph inputs and structured outputs."""

    context: dict
    output: dict


class AgentFactory:
    """Build a role graph without tools or filesystem access in its nodes."""

    @staticmethod
    def request(role: str, llm: LLMPort, context: dict):
        """Share the exact prompt, context and schema with budget planning."""
        contracts = {
            "supervisor": (AgentAction, "supervisor.md"),
            "scientific_review": (
                scientific_review.OUTPUT_SCHEMA,
                scientific_review.PROMPT_FILE,
            ),
            "related_work": (related_work.OUTPUT_SCHEMA, related_work.PROMPT_FILE),
            "evidence_verifier": (
                evidence_verifier.OUTPUT_SCHEMA,
                evidence_verifier.PROMPT_FILE,
            ),
        }
        schema, prompt_file = contracts[role]
        if getattr(llm, "evidence_selection_mode", False):
            schema = {
                "scientific_review": SelectedScientificOutput,
                "related_work": SelectedComparisonOutput,
            }.get(role, schema)
        prompt = (Path(__file__).parent / "prompts" / prompt_file).read_text(
            encoding="utf-8"
        )

        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ], schema

    @staticmethod
    def build(role: str, llm: LLMPort):
        """Compile a LangGraph that invokes one structured model operation."""
        def generate(state: GraphState) -> dict:
            messages, schema = AgentFactory.request(role, llm, state["context"])
            result = llm.generate_json(messages, schema)
            return {"output": result.model_dump(mode="json")}

        graph = StateGraph(GraphState)
        graph.add_node(role, generate)
        graph.add_edge(START, role)
        graph.add_edge(role, END)
        return graph.compile()
