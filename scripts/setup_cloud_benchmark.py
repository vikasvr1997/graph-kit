"""Copy a bounded freight dataset to isolated BigQuery and free-trial Spanner targets.

Original tables are never modified. Re-running verifies existing target tables;
all row copies are limited to this explicitly named benchmark namespace.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from google.cloud import bigquery, spanner

PROJECT = 'premium-odyssey-508202-k9'
DATASET = 'graphkit_validation'
INSTANCE = 'graphkit-benchmark'
DATABASE = 'graphkit_validation'
REGION = 'us-east1'
TABLES = {
    'customers': ('customer_data', ['customer_id','customer_type','credit_terms_days','primary_freight_type',
        'account_status','contract_start_date','annual_revenue_potential'], 'customer_id'),
    'drivers': ('drivers', ['driver_id','employment_status','years_experience'], 'driver_id'),
    'routes': ('routes', None, 'route_id'),
    'facilities': ('facilities', None, 'facility_id'),
    'loads': ('loads', None, 'load_id'),
    'trips': ('trips', None, 'trip_id'),
    'events': ('daily-events', None, 'event_id'),
    'fuel_purchases': ('fuel_purchases', ['fuel_purchase_id','trip_id','truck_id','driver_id','purchase_date',
        'location_city','location_state','gallons','price_per_gallon','total_cost'], 'fuel_purchase_id'),
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['bigquery','spanner'], required=True)
    args = parser.parse_args()
    out = Path('graphkit_out/cloud_validation')
    out.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=PROJECT, location=REGION)
    counts = {}
    if args.phase == 'bigquery':
        ds = bigquery.Dataset(f'{PROJECT}.{DATASET}')
        ds.location = REGION
        ds.description = 'Isolated GraphKit comparison; projection of Customers_data; original is unchanged.'
        ds.labels = {'purpose':'graphkit-benchmark'}
        ds.default_table_expiration_ms = 7 * 24 * 3600 * 1000
        client.create_dataset(ds, exists_ok=True)
        for target, (source, columns, key) in TABLES.items():
            projection = ', '.join(f'`{c}`' for c in columns) if columns else '*'
            sql = f'CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.{target}` AS SELECT {projection} FROM `{PROJECT}.Customers_data.{source}`'
            client.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=1024**3)).result(timeout=180)
            check = list(client.query(f'SELECT COUNT(*) AS n, COUNT(DISTINCT `{key}`) AS unique_keys FROM `{PROJECT}.{DATASET}.{target}`',
                job_config=bigquery.QueryJobConfig(maximum_bytes_billed=1024**3)).result())[0]
            if check.n != check.unique_keys:
                raise ValueError(f'{target}: null or duplicate primary keys')
            table = client.get_table(f'{PROJECT}.{DATASET}.{target}')
            if not table.table_constraints or not table.table_constraints.primary_key:
                client.query(f'ALTER TABLE `{PROJECT}.{DATASET}.{target}` ADD PRIMARY KEY (`{key}`) NOT ENFORCED').result()
            counts[target] = check.n
            print(json.dumps({'backend':'bigquery','table':target,'rows':check.n}),flush=True)
    else:
        db = spanner.Client(project=PROJECT).instance(INSTANCE).database(DATABASE)
        ddl = []
        for target, (_, _, key) in TABLES.items():
            table = client.get_table(f'{PROJECT}.{DATASET}.{target}')
            defs = []
            for field in table.schema:
                kind = {'STRING':'STRING(MAX)','INTEGER':'INT64','FLOAT':'FLOAT64','BOOLEAN':'BOOL',
                        'DATE':'DATE','TIMESTAMP':'TIMESTAMP'}[field.field_type]
                if field.name == key:
                    kind = 'STRING(256) NOT NULL'
                defs.append(f'`{field.name}` {kind}')
            ddl.append(f'CREATE TABLE IF NOT EXISTS `{target}` (' + ', '.join(defs) + f') PRIMARY KEY (`{key}`)')
        db.update_ddl(ddl).result(timeout=240)
        for target, (_, _, key) in TABLES.items():
            table = client.get_table(f'{PROJECT}.{DATASET}.{target}')
            columns = [f.name for f in table.schema]
            with db.snapshot() as snap:
                existing = list(snap.execute_sql(f'SELECT COUNT(*) FROM `{target}`'))[0][0]
            if existing == table.num_rows:
                print(json.dumps({'backend':'spanner','table':target,'rows':existing,'already_loaded':True}),flush=True)
                counts[target] = existing
                continue
            # Idempotent key upserts; four bounded in-flight chunks maximum.
            def write(chunk):
                with db.batch() as batch:
                    batch.insert_or_update(table=target, columns=columns, values=chunk)
                return len(chunk)
            futures = []
            loaded = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                chunk = []
                for row in client.list_rows(table, page_size=5000):
                    chunk.append(tuple(row[c] for c in columns))
                    if len(chunk) == 500:
                        futures.append(pool.submit(write, chunk)); chunk = []
                        if len(futures) >= 4:
                            loaded += futures.pop(0).result()
                if chunk:
                    futures.append(pool.submit(write, chunk))
                for future in futures:
                    loaded += future.result()
            with db.snapshot() as snap:
                actual = list(snap.execute_sql(f'SELECT COUNT(*) FROM `{target}`'))[0][0]
            if actual != table.num_rows:
                raise ValueError(f'{target}: source {table.num_rows} != target {actual}')
            counts[target] = actual
            print(json.dumps({'backend':'spanner','table':target,'rows':actual}),flush=True)
    (out / f'{args.phase}_counts.json').write_text(json.dumps(counts,indent=2))

if __name__ == '__main__':
    main()
