"""Run the FieldPilot eval suite.

Usage:
    python -m app.evals.run            # all cases
    python -m app.evals.run elmore     # only cases whose id contains 'elmore'
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.agent.chat import ChatSession
from app.agent.report import generate_report
from app.agent.report import UNICODE_DASHES, generate_report

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "results"
PAUSE_S = 3  # pause between cases to stay under the free tier rate limit

JUDGE_PROMPT = """You grade answers from an agronomy assistant.
Decide whether the ANSWER meets the CRITERION. Judge only the criterion, nothing else.
Reply with only JSON: {"pass": true or false, "reason": "one short sentence"}"""


@lru_cache
def judge_llm():
    model = os.getenv("GROQ_JUDGE_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    return ChatGroq(model=model, temperature=0, max_retries=5)


def judge(question, answer, criterion):
    """LLM-as-judge for reasoning checks that code can't do."""
    msg = f"QUESTION: {question}\n\nANSWER:\n{answer}\n\nCRITERION: {criterion}"
    reply = judge_llm().invoke([SystemMessage(JUDGE_PROMPT), HumanMessage(msg)]).content
    m = re.search(r"\{.*\}", reply, re.S)
    try:
        data = json.loads(m.group(0))
        return bool(data.get("pass")), data.get("reason", "")
    except (AttributeError, json.JSONDecodeError):
        return False, f"could not parse judge reply: {reply[:120]}"

def run_case(case):
    config = {"run_name": f"eval:{case['id']}", "tags": ["eval"]}

    if case.get("type") == "report":
        r = generate_report(case["field"], config=config)
        question = "Write the field report."
        answer, tools = r["report"], None
        verified, problems = r["verified"], r["unsupported_numbers"] + r["issues"]
    else:
        session = ChatSession(case["field"])
        for q in case.get("setup", []):
            session.ask(q)
        r = session.ask(case["question"], config=config)
        question = case["question"]
        answer, tools = r["answer"], r["tools_used"]
        verified, problems = r["verified"], r["unsupported"] + r.get("issues", [])

    checks = {"verified": (verified, "" if verified else f"problems: {problems}")}

    if tools is not None and any(k in case for k in ("expect_tools", "forbid_tools", "max_tools")):
        missing = [t for t in case.get("expect_tools", []) if t not in tools]
        forbidden = [t for t in case.get("forbid_tools", []) if t in tools]
        ok = not missing and not forbidden
        if "max_tools" in case:
            ok = ok and len(tools) <= case["max_tools"]
        checks["tools"] = (ok, f"used {tools}, missing {missing}, forbidden {forbidden}")

    low = UNICODE_DASHES.sub("-", answer).lower()
    if case.get("must_include"):
        missing = [g for g in case["must_include"] if not any(alt.lower() in low for alt in g)]
        checks["includes"] = (not missing, f"missing {missing}")
    if case.get("must_not_include"):
        found = [p for p in case["must_not_include"] if p.lower() in low]
        checks["excludes"] = (not found, f"contains {found}")
    if case.get("judge"):
        checks["judge"] = judge(question, answer, case["judge"])

    return {
        "id": case["id"],
        "passed": all(ok for ok, _ in checks.values()),
        "checks": {k: {"ok": ok, "detail": d} for k, (ok, d) in checks.items()},
        "tools": tools,
        "answer": answer,
    }
def main():
    cases = json.loads((HERE / "cases.json").read_text())
    if len(sys.argv) > 1:
        wanted = sys.argv[1].split(",")
        cases = [c for c in cases if any(w in c["id"] for w in wanted)]

    results, t0 = [], time.time()
    for i, case in enumerate(cases, 1):
        try:
            r = run_case(case)
        except Exception as e:
            r = {"id": case["id"], "passed": False, "tools": None, "answer": "",
                 "checks": {"error": {"ok": False, "detail": f"{type(e).__name__}: {e}"}}}
        results.append(r)
        print(f"[{i}/{len(cases)}] {'PASS' if r['passed'] else 'FAIL'}  {case['id']}")
        for name, c in r["checks"].items():
            if not c["ok"]:
                print(f"      {name}: {c['detail']}")
        time.sleep(PAUSE_S)

    n = len(results)
    errored = sum("error" in r["checks"] for r in results)
    completed = n - errored
    passed = sum(r["passed"] for r in results)
    by_check = {}
    for r in results:
        for name, c in r["checks"].items():
            ok, total = by_check.get(name, (0, 0))
            by_check[name] = (ok + c["ok"], total + 1)

    print(f"\n{passed}/{completed} completed cases passed ({100 * passed / max(completed, 1):.0f}%), "
          f"{errored} errored, in {time.time() - t0:.0f}s")
    for name, (ok, total) in by_check.items():
        print(f"  {name:<9} {ok}/{total}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"results_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({
        "summary": {"passed": passed, "total": n,
                    "by_check": {k: {"passed": a, "total": b} for k, (a, b) in by_check.items()}},
        "results": results,
    }, indent=1))
    print(f"  saved -> {out}")


if __name__ == "__main__":
    main()