#!/usr/bin/env python3
"""Local-only static gallery server, plus an optional live-search API.

Static file serving has no dependencies, same as before. The live-search
routes under /api/live/ need the `live/` folder's adapter, which needs
homeharvest/requests/tenacity installed (see
live/realtor_adapter.py) — not required just to view the snapshot app.
Those imports are deliberately deferred into _live_manager() so that
running this with a plain system python3 (no packages) still serves the
snapshot exactly as before; only /api/live/* calls fail, with a clear
503, if the packages aren't available to whatever Python is running this.
"""
import argparse
import json
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
LIVE_DIR = ROOT / 'live'

_live_lock = threading.Lock()
_live_manager_instance = None
_live_import_error = None


def _live_manager():
    """Lazily imports and returns a process-wide SearchManager singleton.
    Raises the original ImportError (cached) if the live/ package isn't
    importable in this interpreter."""
    global _live_manager_instance, _live_import_error
    if _live_manager_instance is not None:
        return _live_manager_instance
    if _live_import_error is not None:
        raise _live_import_error
    try:
        sys.path.insert(0, str(LIVE_DIR))
        from search_session import SearchManager  # noqa: PLC0415
        _live_manager_instance = SearchManager()
        return _live_manager_instance
    except Exception as exc:  # noqa: BLE001 - cache and re-raise for every later call too
        _live_import_error = exc
        raise


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def _send_json(self, status, payload):
        body = json.dumps(payload, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length) or b'{}')

    def _route_live(self, method):
        parts = [p for p in self.path.split('?')[0].split('/') if p]
        # parts[0] == 'api', parts[1] == 'live'
        try:
            manager = _live_manager()
        except Exception as exc:  # noqa: BLE001
            self._send_json(503, {
                'error': 'live_search_unavailable',
                'message': (
                    'This server process cannot import the live-search adapter '
                    f'({type(exc).__name__}: {exc}). Run server.py with the Python '
                    'environment that has homeharvest/requests/tenacity installed '
                    '(see live/realtor_adapter.py) — the snapshot gallery itself '
                    'does not need this.'
                ),
            })
            return

        if method == 'POST' and len(parts) == 2:  # POST /api/live  (create + first step)
            body = self._read_json_body()
            try:
                from search_session import SearchParams  # noqa: PLC0415
                params = SearchParams(
                    location=str(body.get('location', '')).strip(),
                    radius_miles=body.get('radiusMiles'),
                    beds_min=int(body.get('minBeds', 0)),
                    beds_max=int(body.get('maxBeds')) if body.get('maxBeds') is not None else 10,
                    price_max=float(body.get('maxRent')) if body.get('maxRent') is not None else 10 ** 9,
                    price_min=float(body.get('minRent', 0) or 0),
                )
            except (TypeError, ValueError) as exc:
                self._send_json(400, {'error': 'invalid_params', 'message': str(exc)})
                return
            if not params.location:
                self._send_json(400, {'error': 'invalid_params', 'message': 'location is required'})
                return
            with _live_lock:
                search_id = manager.create(params)
                snapshot = manager.step(search_id)
            self._send_json(200, snapshot)
            return

        if method == 'GET' and len(parts) == 3:  # GET /api/live/<id>
            search_id = parts[2]
            session = manager.get(search_id)
            if session is None:
                self._send_json(404, {'error': 'unknown_search_id'})
                return
            self._send_json(200, session.snapshot())
            return

        if method == 'POST' and len(parts) == 4 and parts[3] == 'step':  # POST /api/live/<id>/step
            search_id = parts[2]
            try:
                with _live_lock:
                    snapshot = manager.step(search_id)
            except KeyError:
                self._send_json(404, {'error': 'unknown_search_id'})
                return
            self._send_json(200, snapshot)
            return

        if method == 'POST' and len(parts) == 4 and parts[3] == 'cancel':  # POST /api/live/<id>/cancel
            search_id = parts[2]
            with _live_lock:
                ok = manager.cancel(search_id)
            if not ok:
                self._send_json(404, {'error': 'unknown_search_id'})
                return
            self._send_json(200, manager.get(search_id).snapshot())
            return

        if method == 'GET' and len(parts) == 5 and parts[3] == 'photos':  # GET /api/live/<id>/photos/<property_id>
            search_id, property_id = parts[2], parts[4]
            photos = manager.get_photos(search_id, property_id)
            if photos is None:
                self._send_json(404, {'error': 'unknown_search_or_property'})
                return
            self._send_json(200, {'photos': photos})
            return

        self._send_json(404, {'error': 'unknown_route'})

    def do_GET(self):
        if self.path.split('?')[0].startswith('/api/live'):
            self._route_live('GET')
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split('?')[0].startswith('/api/live'):
            self._route_live('POST')
            return
        self.send_error(404, 'Not found')


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8768)
parser.add_argument('--no-open', action='store_true')
args = parser.parse_args()
try:
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
except OSError:
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
url = f'http://127.0.0.1:{server.server_port}/'
print(f'Nearby gallery: {url}\nKeep this terminal open. Press Control-C to stop.', flush=True)
if not args.no_open:
    threading.Timer(.3, lambda: webbrowser.open(url)).start()
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
