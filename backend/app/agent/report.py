"""Field report graph: gather -> write -> verify, with rewrites when numbers are unsupported.

Usage:
    python -m app.agent.report colbert_corn_1
"""
import json
import os
import re
import sys
from datetime import date
from functools import lru_cache
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, StateGraph

from app.agent.context import field_context

MAX_ATTEMPTS = 2

SYSTEM_PROMPT =SYSTEM_PROMPT = """You are FieldPilot, an agronomy scouting assistant for Alabama corn and cotton.
Write a short field report for a farmer using ONLY the facts in the FACTS JSON.

Number rules:
1. Every number you write must appear in FACTS, exactly or rounded to fewer decimal places.
   Never calculate new numbers, differences, totals, or percentages.
2. Use only the numbers that matter for a decision. Do not list every fact.

Interpretation rules:
3. Each yield driver has this_season and typical_season values and an impact. Explain it like
   "summer highs averaged X F versus a typical Y F, which raised the estimate".
   Never call a factor a problem if it raised the estimate.
4. If zones.uniform is true, say the field is uniform with no problem zones.
   Only describe a location for zones.low_zone.
5. Problem areas are places or conditions in the field that need attention: a low zone,
   poorly drained soil, soil pH below the reference range, or a large water deficit. If none apply, say so.
6. If field.season_status is "completed", recommendations are for planning next season,
   not for scouting the current crop.
7. Yield is a county-level estimate based on weather. Always give its 80% range.
8. Base agronomic advice on the "reference" section and never contradict it.
9. If a topic is listed in missing_data, say the data was unavailable.
10. Yield drivers come from the yield model's own weather data, which can differ slightly from the
    weather section. Mention driver values only in the Yield outlook section.

Format: Markdown, under 300 words, short paragraphs, no tables, bold only for the yield estimate.
Use exactly these sections:
## Summary (2 or 3 sentences)
## Crop health
## Problem areas
## Weather
## Soil
## Yield outlook
## What to check next (2 to 4 bullet points)"""

GENERAL_REFERENCE = [
    "Lime, at a rate set by a soil test, raises low soil pH.",
    "Poorly drained soils cause wet stress early in the season and can limit rooting.",
    "In dry spells, sandy or well drained soils with low available water dry out first. "
    "Poorly drained soils mainly cause problems in wet periods.",
    "Yield driver effects compare this season with a typical Alabama season.",
]

REFERENCE = {
    "corn": {
        "optimal_soil_ph": "6.0 to 6.5",
        "heat_stress_threshold_f": 95,
        "critical_period": "pollination in late June and July",
    },
    "cotton": {
        "optimal_soil_ph": "6.0 to 6.5",
        "heat_stress_threshold_f": 95,
        "critical_period": "boll set and fill in July and August",
        "model_note": "For cotton, drier fall weather helps harvest and heavy midsummer rain can cause boll rot, so less rain and longer dry spells can raise the estimate.",        
    },
}
GENERAL_REFERENCE = [
    "Lime, at a rate set by a soil test, raises low soil pH.",
    "Poorly drained soils cause wet stress early in the season and can limit rooting.",
    "Yield driver effects compare this season with a typical Alabama season.",
]

NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
)
LIST_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")


class ReportState(TypedDict, total=False):
    field_name: str
    facts: dict
    report: str
    unsupported: list
    issues: list
    attempts: int


@lru_cache
def get_llm():
    return ChatGroq(model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), temperature=0.2)


def build_facts(ctx):
    """Compact, rounded facts for the LLM, with interpretation hints. No raw series or geometries."""
    field = ctx["field"]
    crop = field["crop"]
    year = ctx["season_year"]
    y = ctx.get("yield") or {}

    facts = {
        "field": {
            "name": field["name"],
            "crop": crop,
            "county": y.get("county") or field.get("county"),
            "season": year,
            "season_status": "completed" if date.today() > date(year, 11, 30) else "in progress",
        },
        "missing_data": sorted(ctx.get("errors", {}).keys()),
        "reference": {**REFERENCE[crop], "notes": GENERAL_REFERENCE},
    }

    if ctx.get("ndvi") and ctx["ndvi"]["peak"]:
        p = ctx["ndvi"]["peak"]
        facts["crop_health"] = {
            "peak_ndvi": round(p["ndvi"], 2),
            "peak_ndre": round(p["ndre"], 2),
            "peak_date": p["date"],
            "clear_satellite_dates": ctx["ndvi"]["clear_dates"],
        }

    if ctx.get("zones"):
        z = ctx["zones"]
        zones = [f["properties"] for f in z["features"]]
        low = next((p for p in zones if p["zone"] == "low"), None)
        facts["zones"] = {
            "index_used": z["index_used"].upper(),
            "field_acres": round(sum(p["acres"] for p in zones), 1),
            "uniform": max(p["percent"] for p in zones) >= 95,
            "breakdown": [{k: p[k] for k in ("zone", "percent", "mean_ndvi")} for p in zones],
            "low_zone": {k: low[k] for k in ("percent", "acres", "direction", "mean_ndvi")} if low else None,
        }

    if ctx.get("weather"):
        w = ctx["weather"]
        facts["weather"] = {
            k: w[k] for k in ("total_rain_in", "water_balance_in", "heat_stress_days",
                              "longest_dry_spell_days")
        }
        bal = w["water_balance_in"]
        facts["weather"]["deficit_severity"] = (
            "none" if bal >= 0 else "small" if bal > -2 else "moderate" if bal > -5 else "large"
        )        
        facts["weather"]["monthly"] = [
            {k: m[k] for k in ("month", "rain_in", "balance_in", "avg_tmax_f")} for m in w["monthly"]
        ]

    if ctx.get("soil"):
        s = ctx["soil"]
        facts["soil"] = {
            "field_available_water_in": s["field_available_water_in"],
            "units": [
                {k: u[k] for k in ("name", "percent", "available_water_in", "drainage",
                                   "ph", "capability_class")}
                for u in s["units"][:4]
            ],
        }

    if ctx.get("zone_soils"):
        facts["zone_soils"] = ctx["zone_soils"]

    if y:
        facts["yield"] = {
            "unit": y["unit"],
            "estimate": y["estimate"],
            "range_low": y["range"][0],
            "range_high": y["range"][1],
            "range_confidence_pct": 80,
            "county_typical": y["county_typical"],
            "weather_adjustment": y["weather_adjustment"],
            "drivers": [
                {
                    "factor": d["factor"],
                    "this_season": d["value"],
                    "typical_season": d["typical"],
                    "effect": d["effect"],
                    "impact": "raised the estimate" if d["effect"] > 0 else "lowered the estimate",
                }
                for d in y["drivers"]
            ],
            "usda_reported_county_yield": y["nass_reported_county_yield"],
            "model_average_error": f"{y['model']['cv_mae']} {y['unit']}",
        }
    return facts


def fact_numbers(obj):
    """Every number found anywhere in the facts, including inside strings."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from fact_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from fact_numbers(v)
    elif isinstance(obj, str):
        for m in NUM_RE.findall(obj):
            yield float(m.replace(",", ""))


def unsupported_numbers(text, facts):
    """Numbers in the report that can't be matched to a fact (rounding allowed)."""
    values = [abs(v) for v in fact_numbers(facts)]
    bad = []
    for raw in NUM_RE.findall(LIST_RE.sub(" ", DATE_RE.sub(" ", text))):
        s = raw.replace(",", "").lstrip("-")
        if not s:
            continue
        n = float(s)
        if n.is_integer() and 2000 <= n <= 2030:  # years
            continue
        decimals = len(s.split(".")[1]) if "." in s else 0
        if decimals == 0 and n < 10:
            ok = any(v == n for v in values)   # small whole numbers must match exactly
        else:
            ok = any(abs(round(v, decimals) - n) < 1e-9 for v in values)
        if not ok:
            bad.append(raw)
    return sorted(set(bad))

def rule_issues(report, facts):
    """Rules the LLM must follow, checked in code instead of trusted."""
    issues = []
    y = facts.get("yield")
    if y:
        m = re.search(r"## Summary(.*?)(?=\n## |\Z)", report, re.S)
        summary = (m.group(1) if m else "").replace(",", "")
        if str(y["estimate"]) not in summary:
            issues.append(
                f"The Summary must state the yield estimate of {y['estimate']} {y['unit']} "
                f"and its 80% range of {y['range_low']} to {y['range_high']}."
            )
    return issues

def gather(state):
    ctx = field_context(state["field_name"])
    return {"facts": build_facts(ctx), "attempts": 0, "unsupported": [], "issues": []}


def write(state):
    prompt = "FACTS:\n" + json.dumps(state["facts"], indent=1)
    feedback = []
    if state.get("unsupported"):
        feedback.append("These numbers are not in FACTS: " + ", ".join(state["unsupported"]) + ".")
    feedback.extend(state.get("issues", []))
    if feedback:
        prompt += "\n\nFix these problems in your previous draft and rewrite the full report:\n- "
        prompt += "\n- ".join(feedback)
    reply = get_llm().invoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(prompt)])
    return {"report": reply.content, "attempts": state["attempts"] + 1}


def verify(state):
    return {
        "unsupported": unsupported_numbers(state["report"], state["facts"]),
        "issues": rule_issues(state["report"], state["facts"]),
    }


def route(state):
    if (state["unsupported"] or state["issues"]) and state["attempts"] < MAX_ATTEMPTS:
        return "write"
    return END

def build_graph():
    g = StateGraph(ReportState)
    g.add_node("gather", gather)
    g.add_node("write", write)
    g.add_node("verify", verify)
    g.set_entry_point("gather")
    g.add_edge("gather", "write")
    g.add_edge("write", "verify")
    g.add_conditional_edges("verify", route, {"write": "write", END: END})
    return g.compile()


GRAPH = build_graph()


def generate_report(field_name):
    state = GRAPH.invoke({"field_name": field_name})
    return {
        "field": field_name,
        "report": state["report"],
        "verified": not state["unsupported"] and not state["issues"],
        "unsupported_numbers": state["unsupported"],
        "issues": state["issues"],
        "attempts": state["attempts"],
    }

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "colbert_corn_1"
    result = generate_report(name)
    print(result["report"])
    print("\n" + "-" * 60)
    if result["verified"]:
        status = "VERIFIED"
    else:
        status = f"UNVERIFIED numbers: {result['unsupported_numbers']} issues: {result['issues']}"
    print(f"{name}: {status} after {result['attempts']} attempt(s)")