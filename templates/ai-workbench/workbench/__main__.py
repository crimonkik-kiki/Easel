import argparse
import json
import os
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description='Start an independent AI workbench on loopback')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    brand = json.loads((ROOT / 'workbench.json').read_text(encoding='utf-8'))
    from .runtime_env import web_environment
    os.environ.update(web_environment(dict(os.environ)))
    from .app import create_app
    app = create_app(ROOT)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port or brand.get('port', 7870)))
    app.state.shutdown = lambda: setattr(server, 'should_exit', True)
    server.run()


if __name__ == '__main__':
    main()
