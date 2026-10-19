"""Read schema and row-count metadata only; never prints customer rows."""
import json
from concurrent.futures import ThreadPoolExecutor
from google.cloud import bigquery
PROJECT = 'premium-odyssey-508202-k9'
client = bigquery.Client(project=PROJECT)
items = list(client.list_tables(PROJECT + '.Customers_data'))
def describe(item):
    table = client.get_table(item.reference)
    return {'name': table.table_id, 'rows': table.num_rows,
            'bytes': table.num_bytes, 'description': table.description,
            'schema': [{'name': f.name, 'type': f.field_type, 'mode': f.mode,
                        'description': f.description} for f in table.schema]}
with ThreadPoolExecutor(max_workers=6) as pool:
    result = list(pool.map(describe, items))
with open('graphkit_out/cloud_source_schema.json', 'w') as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
