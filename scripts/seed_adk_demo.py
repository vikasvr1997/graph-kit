"""Create the small synthetic BigQuery dataset used by the ADK preview.

Uses the active gcloud account. Does not replace data in populated tables.
"""
import argparse
import subprocess

from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from graphkit.graph.core.demo import TABLES, build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--dataset', default='graphkit_adk_demo')
    parser.add_argument('--reader-service-account', required=True)
    args = parser.parse_args()
    token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
    client = bigquery.Client(project=args.project, credentials=Credentials(token=token))
    dataset_id = f'{args.project}.{args.dataset}'
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = 'US'
    dataset.description = 'Synthetic GraphKit ADK demo. All data is invented.'
    dataset.labels = {'application': 'graphkit-adk', 'data': 'synthetic'}
    dataset = client.create_dataset(dataset, exists_ok=True)
    if dataset.labels.get('application') != 'graphkit-adk' or dataset.labels.get('data') != 'synthetic':
        raise ValueError('Refusing to modify a dataset not labelled as the GraphKit synthetic demo.')
    entry = bigquery.AccessEntry('READER', 'userByEmail', args.reader_service_account)
    if entry not in dataset.access_entries:
        dataset.access_entries = list(dataset.access_entries) + [entry]
        client.update_dataset(dataset, ['access_entries'])
    rows = build()
    types = {'TEXT': 'STRING', 'INTEGER': 'INT64', 'REAL': 'FLOAT64'}
    for name, (description, columns) in TABLES.items():
        schema = [bigquery.SchemaField(n, types[t], description=d) for n, t, d in columns]
        table = bigquery.Table(f'{dataset_id}.{name}', schema=schema)
        table.description = description
        table = client.create_table(table, exists_ok=True)
        if table.num_rows == 0:
            client.load_table_from_json(rows[name], table.reference,
                job_config=bigquery.LoadJobConfig(schema=schema, write_disposition='WRITE_EMPTY')).result()
        print(f'{name}: {client.get_table(table.reference).num_rows} rows')


if __name__ == '__main__':
    main()
