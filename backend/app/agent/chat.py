"""Chat agent: the LLM picks which field tools to call, then answers from their results.

Usage:
    python -m app.agent.chat elmore_corn_1
"""
import json
import sys
import re
from datetime import date
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app.agent.context import field_context, live_forecast
from app.agent.report import build_facts, get_llm, unsupported_numbers
from app.agent.report import UNICODE_DASHES, build_facts, get_llm, unsupported_numbers
from app.agent.report import (STE_RULES, UNICODE_DASHES, build_facts, get_llm,
                              style_issues, unsupported_numbers)

MAX_TOOL_ROUNDS = 4   # tool calling rounds per question before the agent must answer
MAX_FIXES = 2         # rewrites allowed when the answer has unsupported numbers

SYSTEM_TEMPLATE = """You are FieldPilot, an agronomy assistant for one field: the {crop} field in {county}
({season} season, {status}). Today is {today}.

Rules:
1. Use your tools to get facts before answering. Call only the tools the question needs.
2. Every number in your answer must come from a tool result. Never estimate or calculate new numbers.
3. If the tools do not have the answer, say so plainly.
4. Yield is a county-level estimate based on weather. Give its 80% range when you mention it.
   Yield drivers compare this season with a typical Alabama season.
5. Answer questions about this field and farming it: its crop, other crops it could grow, soil,
   weather, yield, and management decisions. For general agronomy questions the tools do not cover
   (for example, whether another crop suits this area), answer from general knowledge, say that it
   is general guidance rather than field data, and do not use specific numbers unless they come
   from tool results. If the question needs data FieldPilot does not have (such as ownership or
   seed records), say that data is not available. Politely decline questions unrelated to farming.
6. Answer in plain language a farmer would use, in under 150 words, with no tables.
7. Soil facts come from USDA soil survey maps, not a soil test taken in this field.
8. To explain a low zone, use low_zone_findings from get_problem_zones. Describe soils with
   percent_of_low_zone compared with percent_of_field, never with the whole-field share alone.
   If the findings are unavailable, say the location of soils is unknown.
9. Agronomy reference (always applies): {reference}
10. When the user asks what to do, answer with a short list of actions. Write each action as a
    command in its own sentence, for example "Test the soil." Give the reason in a second short
    sentence. Mention numbers only when they support an action.
11. Never mention internal data names or fields, such as "low_zone_findings" or "unavailable".
    If the field is uniform, say so plainly, for example: "The crop grew evenly. No part of the
    field stands out as weaker."""

SYSTEM_TEMPLATE = SYSTEM_TEMPLATE + "\n\n" + STE_RULES

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_rounds: int
    fixes: int
    turn_start: int
    unsupported: list
    issues: list


def make_tools(field_name):
    """Tools locked to one field. Everything except the forecast comes from the cache."""
    ctx = field_context(field_name)
    facts = build_facts(ctx)

    def section(key):
        return json.dumps(facts.get(key) or {"unavailable": True})

    monthly = {}
    for r in (ctx.get("ndvi") or {}).get("series", []):
        m = r["date"][:7]
        monthly[m] = max(monthly.get(m, 0), r["ndvi"])

    @tool
    def get_field_overview() -> str:
        """Crop, county, season and its status, field size in acres, and agronomy reference values
        (optimal soil pH, heat stress threshold, critical growth period)."""
        return json.dumps({
            "field": facts["field"],
            "field_acres": (facts.get("zones") or {}).get("field_acres"),
            "reference": facts["reference"],
            "missing_data": facts["missing_data"],
        })

    @tool
    def get_crop_health() -> str:
        """Satellite crop health for the season: peak NDVI and NDRE, the peak date,
        and the highest NDVI in each month (the season's greenness trend)."""
        return json.dumps({
            "peak": facts.get("crop_health"),
            "monthly_max_ndvi": [{"month": m, "max_ndvi": round(v, 2)} for m, v in sorted(monthly.items())],
        })

    def low_zone_findings():
        """Soils that stand out in the low zone, computed in code so the agent can't misread them."""
        zone_soils = {z["zone"]: z["soils"] for z in facts.get("zone_soils") or []}
        low, high = zone_soils.get("low", []), zone_soils.get("high", [])
        if not low:
            return None
        in_high = {s["soil"] for s in high}
        info = {u["name"]: u for u in (facts.get("soil") or {}).get("units", [])}
        stand_out = []
        for s in low:
            if s["pattern"] == "concentrated in this zone" or s["soil"] not in in_high:
                stand_out.append({
                    "soil": s["soil"],
                    "percent_of_low_zone": s["percent_of_zone"],
                    "percent_of_field": s["percent_of_field"],
                    "pattern": s["pattern"],
                    "present_in_high_zone": s["soil"] in in_high,
                    "drainage": info.get(s["soil"], {}).get("drainage"),
                    "ph": info.get(s["soil"], {}).get("ph"),
                })
        return {
            "soils_that_stand_out_in_low_zone": stand_out,
            "soils_less_common_in_low_zone": [s["soil"] for s in low if s["pattern"] == "less common in this zone"],
        }

    @tool
    def get_problem_zones() -> str:
        """Low, medium, and high productivity zones from satellite data: share of the field, acres,
        mean NDVI, whether the field is uniform, the location of the low zone, which soils lie under
        each zone, and which soils stand out in the low zone."""
        return json.dumps({
            **(facts.get("zones") or {"unavailable": True}),
            "soils_under_each_zone": facts.get("zone_soils") or "unavailable",
            "low_zone_findings": low_zone_findings() or "unavailable",
        })
    @tool
    def get_season_weather() -> str:
        """Growing season weather: total rain, water balance and its severity, heat stress days,
        longest dry spell, and monthly rain, water balance, and average high temperature."""
        return section("weather")

    @tool
    def get_weather_forecast() -> str:
        """Live 7 day forecast for the field: daily high and low temperature, rain amount, and rain chance."""
        try:
            return json.dumps(live_forecast(field_name))
        except Exception as e:
            return json.dumps({"unavailable": True, "error": str(e)})

    @tool
    def get_soil() -> str:
        """Soil types in the field from USDA SSURGO: share of field, available water, drainage,
        pH, and land capability class."""
        return section("soil")

    @tool
    def get_zone_soils() -> str:
        """Which soil types lie under each productivity zone (low, medium, high), as a share of
        that zone's area. Compare with each soil's share of the whole field to see whether a
        soil is concentrated in the low zone."""
        return section("zone_soils")
    
    @tool
    def get_yield_estimate() -> str:
        """County-level yield estimate for the season with its 80% range, county typical yield,
        weather drivers versus a typical season, and USDA's reported county yield."""
        return section("yield")

    tools = [get_field_overview, get_crop_health, get_problem_zones, get_season_weather,
             get_weather_forecast, get_soil, get_yield_estimate]
    return tools, facts


def build_chat_graph(field_name):
    tools, facts = make_tools(field_name)
    by_name = {t.name: t for t in tools}
    llm_with_tools = get_llm().bind_tools(tools)
    llm_answer_only = get_llm().bind_tools(tools, tool_choice="none")

    def agent(state):
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    def run_tools(state):
        results = []
        for call in state["messages"][-1].tool_calls:
            t = by_name.get(call["name"])
            try:
                content = t.invoke(call["args"] or {}) if t else f"Unknown tool: {call['name']}"
            except Exception as e:
                content = json.dumps({"error": str(e)})
            results.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        return {"messages": results, "tool_rounds": state["tool_rounds"] + 1}

    def final(state):
        """Tool limit reached: answer with what we have."""
        return {"messages": [llm_answer_only.invoke(state["messages"])]}
    
    def verify(state):
        answer = state["messages"][-1].content
        sources = [facts["field"], facts["reference"]]
        for m in state["messages"]:
            if isinstance(m, ToolMessage):
                try:
                    sources.append(json.loads(m.content))
                except (json.JSONDecodeError, TypeError):
                    sources.append(m.content)
        bad = unsupported_numbers(answer, sources)

        issues = []
        y = facts.get("yield")
        clean = UNICODE_DASHES.sub("-", answer.lower())
        if y and str(y["estimate"]) in answer.replace(",", "") and not re.search(r"county[- ]level", clean):
            issues.append("Say the yield is a county-level estimate based on weather, not a prediction "
                          "for this specific field.")

        style = style_issues(answer)
        if (bad or issues or style) and state["fixes"] < MAX_FIXES:
            feedback = list(issues) + list(style)
            if bad:
                feedback.append("These numbers are not in any tool result: " + ", ".join(bad) + ".")
            question = state["messages"][state["turn_start"]].content
            fix = HumanMessage(
                f'Answer the user\'s question again: "{question}"\n'
                "Keep everything the question needs, and fix these problems:\n- " + "\n- ".join(feedback)
            )
            return {"messages": [fix], "fixes": state["fixes"] + 1, "unsupported": bad, "issues": issues}
        return {"unsupported": bad, "issues": issues}

    
    def after_agent(state):
        return "tools" if state["messages"][-1].tool_calls else "verify"

    def after_tools(state):
        return "final" if state["tool_rounds"] >= MAX_TOOL_ROUNDS else "agent"

    def after_verify(state):
        return "agent" if isinstance(state["messages"][-1], HumanMessage) else END

    g = StateGraph(ChatState)
    g.add_node("agent", agent)
    g.add_node("tools", run_tools)
    g.add_node("final", final)
    g.add_node("verify", verify)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", after_agent, {"tools": "tools", "verify": "verify"})
    g.add_conditional_edges("tools", after_tools, {"agent": "agent", "final": "final"})
    g.add_edge("final", "verify")
    g.add_conditional_edges("verify", after_verify, {"agent": "agent", END: END})
    return g.compile(), facts


class ChatSession:
    """One conversation about one field. Keeps history for follow-up questions."""

    def __init__(self, field_name):
        self.graph, self.facts = build_chat_graph(field_name)
        f = self.facts["field"]
        self.messages = [SystemMessage(SYSTEM_TEMPLATE.format(
            field_name=field_name, crop=f["crop"], county=f["county"], season=f["season"],
            status=f["season_status"], today=date.today().isoformat(),
            reference=json.dumps(self.facts["reference"]),
        ))]

    def ask(self, question, config=None):
        start = len(self.messages)
        state = self.graph.invoke({
            "messages": self.messages + [HumanMessage(question)],
            "tool_rounds": 0, "fixes": 0, "turn_start": start, "unsupported": [],
        }, config=config)
        self.messages = state["messages"]
        new = state["messages"][start:]
        return {
            "answer": state["messages"][-1].content,
            "tools_used": [m.name for m in new if isinstance(m, ToolMessage)],
            "verified": not state["unsupported"],
            "unsupported": state["unsupported"],
            "issues": state["issues"],
        }


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "colbert_corn_1"
    session = ChatSession(name)
    print(f"Chatting about {name}. Press Enter on an empty line to quit.")
    while True:
        q = input("\nyou> ").strip()
        if not q:
            break
        r = session.ask(q)
        print(f"\nfieldpilot> {r['answer']}")
        check = "verified" if r["verified"] else f"UNVERIFIED: {r['unsupported']}"
        print(f"   [tools: {', '.join(r['tools_used']) or 'none'} | {check}]")