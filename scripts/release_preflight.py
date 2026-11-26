"""Read-only occupancy check before stopping the production service."""
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from web.health_probe import read_url


def main():
    try:
        status, data, _ = read_url('http://127.0.0.1:7860', '/api/account-execution')
        rows = json.loads(data)
        if status != 200 or not isinstance(rows, list):
            raise ValueError('Cannot verify operation records')
        counts = {'active_operations': sum(bool(row['active']) for row in rows), 'active_browser_leases': 0, 'running_publication_jobs': 0}
        for name, table, condition, key in [
            ('browsers.sqlite3', 'browsers', 'active=1', 'active_browser_leases'),
            ('publish.sqlite3', 'jobs', "state='running'", 'running_publication_jobs'),
        ]:
            path = ROOT / 'outputs' / '_execution' / name
            if path.is_file():
                db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
                try:
                    counts[key] = db.execute(f'SELECT count(*) FROM {table} WHERE {condition}').fetchone()[0]
                finally:
                    db.close()
        busy = any(counts.values())
        print(json.dumps({'marker': 'ACCOUNT_BUSY' if busy else 'IDLE', 'checks': counts}))
        return 10 if busy else 0
    except Exception as error:
        print(json.dumps({'marker': 'PROBE_ERROR_MANUAL_REVIEW', 'requires_human_review': True, 'detail': f'{type(error).__name__}: {error}'}))
        return 30


if __name__ == '__main__':
    sys.exit(main())
