"""Command line for the graph kit. Run `graphkit --help`."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .core import workflow
from .benchmarking.runner import summary
from .core.ddl import create_graph_ddl


def _location(a) -> dict:
    if a.backend == "bigquery":
        loc = {"project": a.project, "dataset": a.dataset, "region": a.region}
        if a.data_project:
            loc["data_project"] = a.data_project
        return loc
    if a.backend == "spanner":
        return {"project": a.project, "instance": a.instance, "database": a.database}
    return {"path": a.path}


def _yes(question: str, assume: bool) -> bool:
    if assume:
        return True
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="graphkit", description="Find table relationships and build property graphs.")
    p.add_argument("--root", default="graphkit_out", help="Folder for graph files (default: graphkit_out)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("demo", help="Write a small made-up supply-chain dataset (CSV + SQLite)")
    s.add_argument("--out", default="demo")

    s = sub.add_parser("scan", help="Scan tables and save a proposed graph (draft)")
    s.add_argument("--name", required=True, help="Graph name, e.g. SupplyChain")
    s.add_argument("--backend", choices=["bigquery", "spanner", "sqlite"], required=True)
    s.add_argument("--project")
    s.add_argument("--dataset")
    s.add_argument("--data-project")
    s.add_argument("--region", default="US", help="BigQuery dataset location")
    s.add_argument("--instance")
    s.add_argument("--database")
    s.add_argument("--path", help="SQLite file")
    s.add_argument("--sample", type=int, default=100, help="Rows to sample per table")
    s.add_argument("--descriptions", help="JSON file with extra table/column descriptions")
    s.add_argument("--no-value-check", action="store_true", help="Don't run small queries to check links")
    s.add_argument("--llm", action="store_true", help="Ask Gemini to improve labels and directions")

    for cmd, text in (("show", "Print the draft graph"), ("ddl", "Print the CREATE PROPERTY GRAPH statement")):
        s = sub.add_parser(cmd, help=text)
        s.add_argument("--name", required=True)

    s = sub.add_parser("confirm", help="Approve the draft and write Terraform (does not apply)")
    s.add_argument("--name", required=True)
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("apply", help="Run Terraform for the approved graph")
    s.add_argument("--name", required=True)
    s.add_argument("--plan", action="store_true", help="Only show the plan")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("bench", help="Generate test queries, run GQL vs SQL, compare and time")
    s.add_argument("--name", required=True)
    s.add_argument("--hops", type=int, default=3)
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--llm", type=int, default=0, help="Also ask Gemini for this many harder questions")
    s.add_argument("--repeat", type=int, default=3)

    s = sub.add_parser("watch", help="Re-scan an approved graph; exit code 3 if new items need review")
    s.add_argument("--name", required=True)
    s.add_argument("--sample", type=int, default=100)

    sub.add_parser("ui", help="Open the graph editor in the browser (Streamlit)")

    s = sub.add_parser("web", help="Run the API backend for the React graph editor")
    s.add_argument("--port", type=int, default=8765)

    s = sub.add_parser("chat-eval", help="Evaluate the chat agent: tool routing, guardrails, latency")
    s.add_argument("--name", required=True)
    s.add_argument("--embedding-model", required=True)
    s.add_argument("--generation-model", default=None, help="Defaults to GRAPHKIT_MODEL")

    s = sub.add_parser("semantic", help="Propose, approve, embed or publish reviewed schema metadata")
    s.add_argument("action", choices=["propose", "approve", "embed", "publish"])
    s.add_argument("--name", required=True)
    s.add_argument("--llm", action="store_true", help="Suggest descriptions and aliases with Gemini")
    s.add_argument("--embedding-model", help="Explicit embedding model identifier")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("ask", help="Answer a question using an approved semantic dataset")
    s.add_argument("--name", required=True)
    s.add_argument("--question", required=True)
    s.add_argument("--embedding-model", required=True)
    s.add_argument("--mode", choices=["auto", "sql", "gql"], default="auto")

    s = sub.add_parser("agent-bench", help="Measure end-to-end question-answer latency")
    s.add_argument("--name", required=True)
    s.add_argument("--questions", required=True, help="JSON array of question strings")
    s.add_argument("--embedding-model", required=True)
    s.add_argument("--repeat", type=int, default=1)

    a = p.parse_args(argv)

    if a.cmd == "demo":
        from .core.demo import make
        print(f"Demo data written: {make(a.out)}")
        return 0
    if a.cmd == "ui":
        app = Path(__file__).parent / "ui" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])
    if a.cmd == "web":
        import os
        import uvicorn
        os.environ["GRAPHKIT_HOME"] = a.root
        uvicorn.run("graphkit.api.application:app", host="127.0.0.1", port=a.port)
        return 0

    if a.cmd == "chat-eval":
        import asyncio
        import functools
        from .chat.eval import run_eval, summary as eval_summary
        from .benchmarking.chat_integration import GRAPH_CASES
        from .agents.chat_agent import get_runner
        from .agents.llm import MODEL, _ask
        from .semantic.workflow import GeminiEmbeddings
        ws = workflow.Workspace(a.root, a.name)
        ask = functools.partial(_ask, model=a.generation_model or MODEL)
        embed_question = GeminiEmbeddings(a.embedding_model).question
        runner = get_runner(ws, ask, embed_question, a.embedding_model, a.generation_model or MODEL)
        runs = asyncio.run(run_eval(runner, cases=GRAPH_CASES))
        for r in runs:
            mark = "OK  " if r.tool_ok and r.guardrail_ok and r.status != "error" else "FAIL"
            print(f"{mark} tool={r.tool_called!s:<14} blocked={r.blocked!s:<5} {r.elapsed_ms:>8.1f} ms  {r.question}")
        s = eval_summary(runs)
        print(json.dumps(s, indent=2))
        return 0 if s["all_passed"] else 1

    ws = workflow.Workspace(a.root, a.name)
    if a.cmd == "scan":
        spec, notes = workflow.do_scan(ws, a.backend, _location(a), sample_rows=a.sample,
                                       descriptions_file=a.descriptions, check_values=not a.no_value_check,
                                       use_llm=a.llm)
        print(f"Draft saved to {ws.draft_path}: {len(spec.nodes)} nodes, {len(spec.edges)} edges.")
        for n in notes:
            print(f"  note: {n}")
        print("Next: review it with `graphkit ui` or `graphkit show`, then `graphkit confirm`.")
        return 0

    if a.cmd == "semantic":
        from .semantic import workflow as semantic
        if a.action == "propose":
            from .agents.llm import _ask
            semantic.propose_catalog(ws, _ask if a.llm else None)
            print(f"Review descriptions and aliases in {ws.dir / 'semantic.draft.json'}")
        elif a.action == "approve":
            if not _yes("Approve the reviewed semantic draft and generate semantic table deployment?", a.yes):
                return 1
            semantic.approve_catalog(ws)
            print("Semantic catalog approved. Review terraform/semantic.sql and semantic.tf.")
        elif a.action == "embed":
            if not a.embedding_model:
                p.error("semantic embed requires --embedding-model")
            provider = semantic.GeminiEmbeddings(a.embedding_model)
            artifact = semantic.embed_catalog(ws, provider.documents, a.embedding_model)
            print(f"Embedded {len(artifact['ids'])} approved catalog items.")
        elif a.action == "publish":
            if not _yes("Publish approved metadata and embeddings to the configured database?", a.yes):
                return 1
            print(f"Published {semantic.publish(ws)} catalog rows.")
        return 0
    if a.cmd in ("ask", "agent-bench"):
        from .agents.dataset_agent import DatasetAgent
        from .semantic.workflow import GeminiEmbeddings
        from .agents.llm import _ask
        provider = GeminiEmbeddings(a.embedding_model)
        agent = DatasetAgent(ws, _ask, provider.question, a.embedding_model)
        if a.cmd == "ask":
            print(json.dumps(agent.answer(a.question, mode=a.mode), indent=2, default=str))
        else:
            from .benchmarking.runner import benchmark_agent
            questions = json.loads(Path(a.questions).read_text())
            if not isinstance(questions, list):
                p.error("--questions must contain a JSON array")
            report = benchmark_agent(agent, questions, repeat=a.repeat)
            (ws.dir / "agent_bench.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report['summary'], indent=2))
        return 0

    spec = ws.draft()
    if spec is None:
        print(f"No graph named {a.name} in {a.root}. Run `graphkit scan` first.", file=sys.stderr)
        return 1

    if a.cmd == "show":
        for n in spec.nodes:
            print(f"node  {n.label:<20} {n.table} key({', '.join(n.key)})  [{n.status}]")
        for lbl, e, rev in spec.directed_edges():
            src, dst = (e.dest, e.source) if rev else (e.source, e.dest)
            print(f"edge  ({src})-[:{lbl}]->({dst})  via {e.table}  conf {e.confidence}  [{e.status}]")
        for prob in spec.validate():
            print(f"problem: {prob}")
        return 0
    if a.cmd == "ddl":
        print(create_graph_ddl(spec))
        return 0
    if a.cmd == "confirm":
        print(json.dumps(workflow.pending_changes(ws), indent=2))
        if not _yes("Approve this graph?", a.yes):
            return 1
        print(f"Approved. Written: {workflow.confirm(ws, spec)}")
        return 0
    if a.cmd == "apply":
        approved = ws.approved()
        if approved is None:
            print("Nothing approved yet. Run `graphkit confirm` first.", file=sys.stderr)
            return 1
        if not a.plan and not _yes(f"Create/replace graph {a.name} in {approved.location.get('project')}?", a.yes):
            return 1
        code, log = workflow.apply(ws, "plan" if a.plan else "apply")
        print(log)
        return code
    if a.cmd == "bench":
        qs, results = workflow.do_bench(ws, max_hops=a.hops, limit=a.limit, llm_questions=a.llm, repeat=a.repeat)
        for r in results:
            mark = {True: "OK  ", False: "DIFF", None: "--  "}[r.match]
            print(f"{mark} gql {r.gql_ms or '-':>8} ms  sql {r.sql_ms if r.sql_ms is None else round(r.sql_ms, 1):>8} ms  {r.question}")
        print(json.dumps(summary(results), indent=2))
        print(f"Saved {ws.dir / 'bench.json'} and {ws.dir / 'examples.json'}")
        return 0
    if a.cmd == "watch":
        new = workflow.do_watch(ws, sample_rows=a.sample)
        if new:
            print(f"{len(new)} new items need review: {', '.join(new)}")
            return 3
        print("No new tables or links.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
