"""Graph/dataset query safety: read-only SQL/GQL and approved-source scope.

These checks are mandatory for dataset tools, independent of chat Model Armor.
"""
from .tools import is_read_only_graph_query, query_parts, _WRITE


def check_query(query: str, mode: str):
    import re
    body, scrubbed = query_parts(query, graph_labels=mode == 'gql')
    if not body or ';' in scrubbed or _WRITE.search(scrubbed):
        raise ValueError('Only a single read-only query is allowed.')
    if mode == 'gql':
        if not is_read_only_graph_query(body):
            raise ValueError('Expected a graph query.')
    elif mode != 'sql' or not re.match(r'^(SELECT|WITH)\b', body, re.I):
        raise ValueError('Expected SELECT or WITH SQL.')
    return body


def validate_scope(query, mode, spec, tables, adapter):
    """Reject references outside the reviewed dataset before database execution."""
    import re
    if mode == 'gql':
        ref = adapter.graph_ref(spec.name)
        prefix = re.match(r'^GRAPH\s+' + re.escape(ref) + r'\s+MATCH\b', query, re.I)
        _, tail = query_parts(query[prefix.end():] if prefix else query, graph_labels=True)
        if not prefix or re.search(r'\b(GRAPH|FROM|JOIN|GRAPH_TABLE|NEXT|UNION)\b', tail, re.I):
            raise ValueError('Agent GQL must be one MATCH query over the approved graph.')
        return
    import sqlglot
    from sqlglot import exp
    dialect = {'bigquery': 'bigquery', 'spanner': 'bigquery', 'sqlite': 'sqlite'}.get(spec.backend)
    dialect = dialect or getattr(adapter, 'sql_dialect', None)
    statements = sqlglot.parse(query, read=dialect)
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError('Expected one SQL query expression.')
    tree = statements[0]
    if any(isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Into)) for node in tree.walk()):
        raise ValueError('SQL contains a write or command.')
    allowed = set()
    for table in tables:
        parsed = sqlglot.parse_one('SELECT * FROM ' + adapter.qualify(table.name), read=dialect)
        allowed.add(tuple(part.name for part in next(parsed.find_all(exp.Table)).parts))
    # Resolve CTE aliases through SQLGlot scopes rather than trusting alias names globally.
    from sqlglot.optimizer.scope import traverse_scope, Scope
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if isinstance(source, Scope):
                continue
            if not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier):
                raise ValueError('Table functions and external sources are not allowed.')
            parts = tuple(part.name for part in source.parts)
            if parts not in allowed:
                raise ValueError(f'Table reference is outside the approved dataset: {source.sql()}')
    # Reject function calls that can contact external systems or execute remote code.
    if any(isinstance(node, exp.Anonymous) for node in tree.walk()):
        raise ValueError('Unrecognized SQL functions require a reviewed query template.')

