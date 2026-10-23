"""Multi-agent field assistant.

A planner routes each question to specialist agents (crop health, weather, soil, yield),
which run in parallel with their own tools. A synthesizer combines their findings,
and a deterministic verifier checks every number before the answer is returned.

Usage:
    python -m app.agent.multi elmore_corn_1
"""
import json
import operator
import re
import sys
from typing import Annotated, TypedDict
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.agent.chat import make_tools
from app.agent.report import STE_RULES, UNICODE_DASHES, get_llm, unsupported_numbers

SPECIALISTS = {
    "crop_health": {
        "title": "Crop health agent",
        "tools": ["get_crop_health", "get_problem_zones"],
        "focus": "satellite crop health (NDVI and NDRE), the season greenness trend, and productivity zones",
    },
    "weather": {
        "title": "Weather agent",
        "tools": ["get_season_weather", "get_weather_forecast"],
        "focus": "season weather, water balance, heat stress, dry spells, and the 7 day forecast",
    },
    "soil": {
        "title": "Soil agent",
        "tools": ["get_soil", "get_problem_zones"],
        "focus": "soil types, drainage, pH, available water, and which soils lie under each zone",
    },
    "yield": {
        "title": "Yield agent",
        "tools": ["get_yield_estimate"],
        "focus": "the county-level yield estimate, its 80% range, and the weather drivers behind it",
    },
}
MAX_SPECIALIST_ROUNDS = 2
MAX_FIXES = 1

PLANNER_PROMPT = """You route questions about one farm field to specialist agents.

Specialists:
{catalog}

Reply with only JSON: {{"specialists": ["name", ...], "reason": "one short sentence"}}
Choose only the specialists the question needs. Choose none for greetings or questions
unrelated to farming. For broad questions, such as why part of the field is weak or what
to do next season, choose every specialist that can contribute."""

SPECIALIST_PROMPT = """You are the {title} for one field: the {crop} field in {county}
({season} season, {status}). Today is {today}. Your focus: {focus}.
Analyze the data below for the farmer's question, and report your findings in 3 to 6 short bullet points.
Use only numbers from your data. Say plainly when your data does not answer part of the question.
Do not give advice outside your focus. Never mention internal data names."""

SYNTH_PROMPT = """You are Field Pilot, an agronomy assistant. Write the final answer to the farmer's
question from the specialist findings below.

Rules:
1. Use only facts and numbers from the findings. Never calculate new numbers.
2. Combine the findings into one clear answer. Connect them only where the findings support it.
   Weather that affected the whole field cannot explain why one zone is weaker than the rest.
3. If there are no findings and the question is unrelated to farming, politely decline.
4. Yield is a county-level estimate based on weather. Say "county-level" and give its 80% range.
5. Never mention agents, tools, or internal data names.
6. Answer in plain language, in under 150 words, with no tables.
Agronomy reference: {reference}
7. Today is {today}. For timing questions, such as whether to plant now, compare today's date
   with the planting window in the agronomy reference before anything else.
"""


class State(TypedDict, total=False):
    question: str
    history: str
    plan: list
    findings: Annotated[list, operator.add]   # specialists append in parallel
    answer: str
    unsupported: list
    issues: list
    fixes: int
    retry: bool


class SpecialistInput(TypedDict):
    name: str
    question: str
    history: str

def run_specialist(name, question, history, all_tools, field_info):
    """One specialist: code gathers its data, then its own LLM analyzes it."""
    spec = SPECIALISTS[name]
    outputs, used, sections = [], [], []
    for tool_name in spec["tools"]:
        try:
            content = all_tools[tool_name].invoke({})
        except Exception as e:
            content = json.dumps({"unavailable": True, "error": str(e)})
        outputs.append(content)
        used.append(tool_name)
        sections.append(f"{tool_name}:\n{content}")

    system = SPECIALIST_PROMPT.format(title=spec["title"], focus=spec["focus"],
                                      today=date.today().isoformat(), **field_info)
    prompt = f"{history}Question: {question}\n\nYour data:\n\n" + "\n\n".join(sections)
    try:
        findings = get_llm().invoke([SystemMessage(system), HumanMessage(prompt)]).content
    except Exception as e:
        findings = f"The {spec['title'].lower()} could not complete its analysis ({type(e).__name__})."
    return {"agent": name, "title": spec["title"], "findings": findings,
            "tool_outputs": outputs, "tools_used": used}
def build_graph(field_name):
    tools, facts = make_tools(field_name)
    all_tools = {t.name: t for t in tools}
    f = facts["field"]
    field_info = {"crop": f["crop"], "county": f["county"], "season": f["season"], "status": f["season_status"]}
    catalog = "\n".join(f"- {k}: {v['focus']}" for k, v in SPECIALISTS.items())
    synth_system = SYNTH_PROMPT.format(reference=json.dumps(facts["reference"]),
                                       today=date.today().isoformat()) + STE_RULES

    def planner(state):
        reply = get_llm().invoke([
            SystemMessage(PLANNER_PROMPT.format(catalog=catalog)),
            HumanMessage(f"{state['history']}Question: {state['question']}"),
        ]).content
        try:
            raw = json.loads(re.search(r"\{.*\}", reply, re.S).group(0)).get("specialists", [])
            plan = [s for s in raw if s in SPECIALISTS]
        except (AttributeError, json.JSONDecodeError):
            plan = list(SPECIALISTS)   # if the plan cannot be read, ask everyone
        return {"plan": plan, "fixes": 0, "retry": False}

    def fan_out(state):
        if not state["plan"]:
            return "synthesizer"
        return [Send("specialist", {"name": n, "question": state["question"], "history": state["history"]})
                for n in state["plan"]]

    def specialist(inp: SpecialistInput):
        return {"findings": [run_specialist(inp["name"], inp["question"], inp["history"], all_tools, field_info)]}

    def synthesizer(state):
        parts = [f"{x['title']} findings:\n{x['findings']}" for x in state.get("findings", [])]
        prompt = f"{state['history']}Question: {state['question']}\n\n"
        prompt += "\n\n".join(parts) if parts else "No specialist findings."
        if state.get("retry"):
            feedback = list(state.get("issues", []))
            if state.get("unsupported"):
                feedback.append("These numbers are not in the findings: " + ", ".join(state["unsupported"]) + ".")
            prompt += "\n\nRewrite the answer and fix these problems:\n- " + "\n- ".join(feedback)
        return {"answer": get_llm().invoke([SystemMessage(synth_system), HumanMessage(prompt)]).content}

    def verify(state):
        answer = state["answer"]
        sources = [facts["field"], facts["reference"]]
        for x in state.get("findings", []):
            for out in x["tool_outputs"]:
                try:
                    sources.append(json.loads(out))
                except (json.JSONDecodeError, TypeError):
                    sources.append(out)
        bad = unsupported_numbers(answer, sources)
        issues = []
        y = facts.get("yield")
        clean = UNICODE_DASHES.sub("-", answer.lower())
        if y and str(y["estimate"]) in answer.replace(",", "") and not re.search(r"county[- ]level", clean):
            issues.append("Call the yield a county-level estimate based on weather.")
        retry = bool(bad or issues) and state.get("fixes", 0) < MAX_FIXES
        return {"unsupported": bad, "issues": issues, "retry": retry,
                "fixes": state.get("fixes", 0) + (1 if retry else 0)}

    g = StateGraph(State)
    g.add_node("planner", planner)
    g.add_node("specialist", specialist)
    g.add_node("synthesizer", synthesizer)
    g.add_node("verify", verify)
    g.set_entry_point("planner")
    g.add_conditional_edges("planner", fan_out, ["specialist", "synthesizer"])
    g.add_edge("specialist", "synthesizer")
    g.add_edge("synthesizer", "verify")
    g.add_conditional_edges("verify", lambda s: "synthesizer" if s["retry"] else END,
                            {"synthesizer": "synthesizer", END: END})
    return g.compile(), facts


class MultiAgentSession:
    """Same interface as ChatSession, so the API and evals can use either."""

    def __init__(self, field_name):
        self.graph, self.facts = build_graph(field_name)
        self.turns = []

    def ask(self, question, config=None):
        history = "".join(f"Earlier question: {q}\nEarlier answer: {a}\n\n" for q, a in self.turns[-3:])
        state = self.graph.invoke({"question": question, "history": history, "findings": []}, config=config)
        self.turns.append((question, state["answer"]))
        return {
            "answer": state["answer"],
            "agents_used": state.get("plan", []),
            "tools_used": [t for x in state.get("findings", []) for t in x["tools_used"]],
            "verified": not state.get("unsupported") and not state.get("issues"),
            "unsupported": state.get("unsupported", []),
            "issues": state.get("issues", []),
        }


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "elmore_corn_1"
    session = MultiAgentSession(name)
    print(f"Multi-agent chat about {name}. Press Enter on an empty line to quit.")
    while True:
        q = input("\nyou> ").strip()
        if not q:
            break
        r = session.ask(q)
        print(f"\nfieldpilot> {r['answer']}")
        check = "verified" if r["verified"] else f"UNVERIFIED: {r['unsupported'] + r['issues']}"
        print(f"   [agents: {', '.join(r['agents_used']) or 'none'} | tools: {', '.join(r['tools_used']) or 'none'} | {check}]")