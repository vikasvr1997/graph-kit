"""Draw a graph in the browser with vis-network, in the style of BigQuery's graph view.

Two views:
- schema_view: one circle per node label, one arrow per edge label.
- data_view: real rows from the scan sample, linked through the edge tables.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from ..adapters.base import TableInfo
from ..core.model import NEW, PROPOSED, GraphSpec

VIS_JS = Path(__file__).with_name("vis-network.min.js")
PALETTE = ["#1a73e8", "#e8710a", "#188038", "#9334e6", "#d01884", "#12b5cb", "#c5221f", "#5f6368", "#f9ab00", "#3c4043"]


def colors(spec: GraphSpec) -> dict[str, str]:
    return {n.label: PALETTE[i % len(PALETTE)] for i, n in enumerate(spec.nodes)}


def _tip(d: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in d.items() if v not in (None, "", []))


def schema_view(spec: GraphSpec) -> tuple[list[dict], list[dict]]:
    col = colors(spec)
    nodes = []
    for n in spec.nodes:
        nodes.append({
            "id": n.label, "label": n.label, "color": col[n.label],
            "dashed": n.status == NEW, "status": n.status,
            "info": {"type": "node", "label": n.label, "table": n.table, "key": ", ".join(n.key),
                     "description": n.description, "status": n.status},
        })
    edges = []
    for label, e, rev in spec.directed_edges():
        src, dst = (e.dest, e.source) if rev else (e.source, e.dest)
        edges.append({
            "id": label, "from": src, "to": dst, "label": label,
            "dashed": e.status == NEW or (e.status == PROPOSED and e.confidence < 0.7),
            "status": e.status,
            "info": {"type": "edge", "label": label, "table": e.table, "from": src, "to": dst,
                     "source_key": ", ".join(e.source_key), "dest_key": ", ".join(e.dest_key),
                     "two-way": "yes" if e.bidirectional else "no", "confidence": e.confidence,
                     "why": e.reason, "status": e.status},
        })
    return nodes, edges


def data_view(spec: GraphSpec, tables: list[TableInfo], per_label: int = 15) -> tuple[list[dict], list[dict]]:
    """Up to `per_label` rows per node label from the sample, and the edges between them."""
    col = colors(spec)
    sample = {t.name: t.sample for t in tables}
    nodes, ids = [], set()

    def nid(label, row, cols):
        return f"{label}:" + "|".join(str(row.get(c)) for c in cols)

    for n in spec.nodes:
        name_col = next((c for c in ("name", "title") if sample.get(n.table) and c in sample[n.table][0]), None)
        for row in sample.get(n.table, [])[:per_label]:
            i = nid(n.label, row, n.key)
            ids.add(i)
            caption = "|".join(str(row.get(c)) for c in n.key)
            if name_col:
                caption += f"\n{str(row[name_col])[:22]}"
            nodes.append({"id": i, "label": caption, "color": col[n.label], "group": n.label,
                          "info": {"type": n.label, **{k: v for k, v in row.items()}}})
    edges = []
    for label, e, rev in spec.directed_edges():
        if rev:
            continue  # the reverse edge is the same rows; draw each link once
        for row in sample.get(e.table, []):
            a = nid(e.source, row, e.source_key)
            b = nid(e.dest, row, e.dest_key)
            if a in ids and b in ids:
                edges.append({"from": a, "to": b, "arrows2": e.bidirectional,  # label in the side panel only
                              "info": {"type": label, **{k: v for k, v in row.items()}}})
    return nodes, edges


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<style>
  :root { --bg:#ffffff; --fg:#202124; --muted:#5f6368; --line:#dadce0; --panel:#f8f9fa; }
  @media (prefers-color-scheme: dark) { :root { --bg:#1f1f1f; --fg:#e8eaed; --muted:#9aa0a6; --line:#3c4043; --panel:#28292a; } }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--fg); font:13px/1.4 system-ui, sans-serif; }
  #wrap { display:flex; height:__H__px; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  #net { flex:1; min-width:0; }
  #side { width:260px; border-left:1px solid var(--line); background:var(--panel); padding:12px; overflow:auto; }
  #side h4 { margin:0 0 8px; font-size:13px; }
  #side table { border-collapse:collapse; width:100%; }
  #side td { padding:3px 4px; border-bottom:1px solid var(--line); vertical-align:top; word-break:break-word; }
  #side td:first-child { color:var(--muted); white-space:nowrap; }
  #legend { display:flex; flex-wrap:wrap; gap:10px; padding:8px 0 0; color:var(--muted); }
  #legend span { display:inline-flex; align-items:center; gap:5px; }
  #legend i { width:10px; height:10px; border-radius:50%; display:inline-block; }
  .hint { color:var(--muted); }
  @media (max-width:640px) { #wrap { flex-direction:column; } #side { width:auto; border-left:0; border-top:1px solid var(--line); max-height:180px; } }
</style>
<script>__VIS__</script></head><body>
<div id="wrap"><div id="net"></div><div id="side"><h4>Details</h4><div id="info" class="hint">Click a node or edge to see its properties. Drag to move, scroll to zoom.</div></div></div>
<div id="legend">__LEGEND__</div>
<script>
const N = __NODES__, E = __EDGES__;
const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
const fg = dark ? '#e8eaed' : '#202124', edgeC = dark ? '#9aa0a6' : '#80868b';
const nodes = new vis.DataSet(N.map(n => ({
  id: n.id, label: n.label, info: n.info, shape: 'dot', size: __SIZE__,
  color: { background: n.color, border: n.dashed ? '#f9ab00' : n.color, highlight: { background: n.color, border: fg } },
  borderWidth: n.dashed ? 3 : 1, shapeProperties: { borderDashes: n.dashed ? [4, 3] : false },
  font: { color: fg, size: 13, multi: false },
})));
const edges = new vis.DataSet(E.map((e, i) => ({
  id: e.id || ('e' + i), from: e.from, to: e.to, label: e.label, info: e.info,
  arrows: { to: { enabled: true, scaleFactor: 0.6 }, from: { enabled: !!e.arrows2, scaleFactor: 0.6 } },
  dashes: !!e.dashed, color: { color: e.dashed ? '#f9ab00' : edgeC, highlight: fg },
  font: { color: fg, size: 10, strokeWidth: 3, strokeColor: dark ? '#1f1f1f' : '#ffffff', align: 'middle' },
  smooth: { type: 'dynamic' },
})));
const net = new vis.Network(document.getElementById('net'), { nodes, edges }, {
  physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -60, springLength: __SPRING__ }, stabilization: { iterations: 200 } },
  interaction: { hover: true, tooltipDelay: 150 },
});
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function show(info) {
  if (!info) return;
  document.getElementById('info').innerHTML = '<table>' + Object.entries(info)
    .filter(([k, v]) => v !== null && v !== '')
    .map(([k, v]) => '<tr><td>' + esc(k) + '</td><td>' + esc(v) + '</td></tr>').join('') + '</table>';
}
net.on('click', p => {
  if (p.nodes.length) show(nodes.get(p.nodes[0]).info);
  else if (p.edges.length) show(edges.get(p.edges[0]).info);
});
</script></body></html>"""


def _js(data) -> str:
    # Safe inside <script>: a value containing "</script>" can't end the tag.
    return json.dumps(data, default=str).replace("</", "<\\/")


def render(nodes: list[dict], edges: list[dict], legend: dict[str, str], height: int = 560, big: bool = True) -> str:
    vis = VIS_JS.read_text() if VIS_JS.exists() else ""
    legend_html = "".join(f'<span><i style="background:{c}"></i>{html.escape(k)}</span>' for k, c in legend.items())
    legend_html += '<span class="hint">Orange dashes: new or low-confidence, needs review</span>'
    return (TEMPLATE.replace("__VIS__", vis)
            .replace("__H__", str(height))
            .replace("__NODES__", _js(nodes))
            .replace("__EDGES__", _js(edges))
            .replace("__LEGEND__", legend_html)
            .replace("__SIZE__", "22" if big else "12")
            .replace("__SPRING__", "170" if big else "90"))
