"""Verify ADK/Vertex AI queries against the preview's two synthetic workspaces."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--model', default='gemini-3.5-flash')
    args = parser.parse_args()
    token = subprocess.check_output(['gcloud', 'auth', 'print-identity-token'], text=True).strip()
    def call(path, body=None):
        request = urllib.request.Request(args.url.rstrip('/') + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'HTTP {error.code}: {error.read().decode()}') from error
    report = {'service': args.url, 'runtime': call('/api/dataset/runtime'),
              'model': args.model, 'synthetic_data_only': True, 'runs': []}
    for workspace in ['SupplyChain', 'BigQueryDemo']:
        started = time.perf_counter()
        result = call('/api/semantic/ask', {'name': workspace,
            'question': 'How many suppliers are there?', 'generation_model': args.model,
            'use_embeddings': False, 'mode': 'sql'})
        values = [v for row in result.get('rows', []) for v in row.values()]
        passed = (result.get('status') == 'success' and result.get('engine') == 'adk'
                  and values == [8] and 'table:suppliers' in result.get('references', []))
        report['runs'].append({'workspace': workspace, 'expected_count': 8, 'passed': passed,
                               'http_elapsed_ms': round((time.perf_counter()-started)*1000, 2),
                               'result': result})
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report['runs'][-1]), flush=True)
    if not all(run['passed'] for run in report['runs']):
        raise SystemExit('ADK preview validation failed; inspect the report.')


if __name__ == '__main__':
    main()
