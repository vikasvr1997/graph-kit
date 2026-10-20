"""Run test queries as GQL and as SQL, check they agree, and time them.

Queries where both answers agree are saved as verified examples. An agent
can put those in its prompt as few-shot examples, which makes its own
graph queries more accurate.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from graphkit.graph.adapters.base import Adapter
from graphkit.graph.adapters.base import GraphNotSupported
from graphkit.graph.benchmarking.generator import EvalQuery
from graphkit.graph.benchmarking.generator import normalize


@dataclass
class BenchResult:
    id: str
    question: str
    source: str
    gql_ms: float | None = None  # median wall-clock time
    sql_ms: float | None = None
    gql_server_ms: float | None = None  # time the database reports (BigQuery only)
    sql_server_ms: float | None = None
    gql_bytes: int | None = None
    sql_bytes: int | None = None
    rows: int | None = None
    match: bool | None = None  # None = couldn't compare
    faster: str = ""  # "gql", "sql" or ""
    error: str = ""


def _time(adapter: Adapter, sql: str, repeat: int):
    runs = [adapter.run(sql) for _ in range(repeat)]
    server = [r.server_ms for r in runs if r.server_ms is not None]
    return (runs[-1], statistics.median(r.elapsed_ms for r in runs),
            statistics.median(server) if server else None)


def run_bench(adapter: Adapter, queries: list[EvalQuery], repeat: int = 3) -> list[BenchResult]:
    results = []
    for q in queries:
        r = BenchResult(id=q.id, question=q.question, source=q.source)
        gql_rows = sql_rows = None
        try:
            res, r.sql_ms, r.sql_server_ms = _time(adapter, q.sql, repeat)
            sql_rows, r.sql_bytes, r.rows = res.rows, res.bytes_processed, len(res.rows)
        except Exception as e:  # noqa: BLE001 - report every failure in the table
            r.error = f"SQL failed: {e}"
        if adapter.supports_graph:
            try:
                res, r.gql_ms, r.gql_server_ms = _time(adapter, q.gql, repeat)
                gql_rows, r.gql_bytes = res.rows, res.bytes_processed
            except GraphNotSupported as e:
                r.error = r.error or str(e)
            except Exception as e:  # noqa: BLE001
                r.error = (r.error + " | " if r.error else "") + f"GQL failed: {e}"
        else:
            r.error = r.error or "GQL not run: this source has no graph engine (SQL timed only)."
        if gql_rows is not None and sql_rows is not None:
            r.match = normalize(gql_rows, q.compare) == normalize(sql_rows, q.compare)
        if r.gql_ms is not None and r.sql_ms is not None:
            r.faster = "gql" if r.gql_ms < r.sql_ms else "sql"
        results.append(r)
    return results


def summary(results: list[BenchResult]) -> dict:
    compared = [r for r in results if r.match is not None]
    gql = [r.gql_ms for r in results if r.gql_ms is not None]
    sql = [r.sql_ms for r in results if r.sql_ms is not None]
    return {
        "queries": len(results),
        "compared": len(compared),
        "matched": sum(r.match for r in compared),
        "errors": sum("failed" in r.error for r in results),
        "gql_median_ms": round(statistics.median(gql), 1) if gql else None,
        "sql_median_ms": round(statistics.median(sql), 1) if sql else None,
        "gql_faster": sum(r.faster == "gql" for r in results),
    }


def save(results: list[BenchResult], queries: list[EvalQuery], out_dir: str | Path) -> dict[str, Path]:
    """Write bench.json (everything) and examples.json (verified queries only)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    by_id = {q.id: q for q in queries}
    bench = out / "bench.json"
    bench.write_text(json.dumps({"summary": summary(results), "results": [asdict(r) for r in results]}, indent=2) + "\n")
    examples = out / "examples.json"
    verified = [{"question": by_id[r.id].question, "gql": by_id[r.id].gql, "median_ms": r.gql_ms}
                for r in results if r.match]
    examples.write_text(json.dumps(verified, indent=2) + "\n")
    return {"bench": bench, "examples": examples}


def benchmark_agent(agent, questions: list[str], repeat: int = 1) -> dict:
    """Measure full QA latency, separately from SQL/GQL execution benchmarks.

    Sequential baseline only; load/concurrency tests belong in the serving layer.
    Failures are included in request counts but excluded from successful latency
    percentiles so error rates must always be read alongside the timings.
    """
    import math
    import time
    if repeat < 1 or not questions or any(not isinstance(q, str) or not q.strip() for q in questions):
        raise ValueError('Provide nonempty questions and repeat >= 1.')
    runs = []
    for question in questions:
        for _ in range(repeat):
            started = time.perf_counter()
            try:
                result = agent.answer(question)
                runs.append({'question': question, 'status': result['status'],
                             'elapsed_ms': (time.perf_counter()-started)*1000,
                             'timings_ms': result.get('timings_ms', {}),
                             'query': result.get('query', ''), 'error': ''})
            except Exception as error:
                runs.append({'question': question, 'status': 'error',
                             'elapsed_ms': (time.perf_counter()-started)*1000, 'error': str(error)})
    successful = sorted(r['elapsed_ms'] for r in runs if r['status'] == 'success')
    def percentile(p):
        return round(successful[max(0, math.ceil(len(successful)*p)-1)], 2) if successful else None
    return {'summary': {'requests': len(runs), 'successful': len(successful),
                        'abstained': sum(r['status'] == 'abstained' for r in runs),
                        'errors': sum(r['status'] == 'error' for r in runs),
                        'p50_ms': percentile(.5), 'p95_ms': percentile(.95), 'p99_ms': percentile(.99)},
            'runs': runs}
