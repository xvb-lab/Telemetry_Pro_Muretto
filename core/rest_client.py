"""
core/rest_client.py — Poller REST condiviso per gli endpoint LMU.

Prima ogni widget apriva il proprio thread e faceva la propria chiamata a
/rest/watch/standings. Qui un singolo poller per endpoint serve tutti i
widget: si abbonano allo stesso endpoint e ricevono l'ultimo dato in cache.

Risparmio: meno thread, meno richieste HTTP duplicate verso localhost:6397.
"""
import json
import time
import threading
import urllib.request

LMU_API = "http://localhost:6397"


class _EndpointPoller:
    """Polla un singolo endpoint REST a intervallo fisso, tiene l'ultimo dato."""

    def __init__(self, path: str, interval: float = 0.1):
        self.path = path
        self.interval = interval
        self._data = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get(self):
        with self._lock:
            return self._data

    def _loop(self):
        url = f"{LMU_API}{self.path}"
        while self._running:
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=1) as resp:
                    data = json.loads(resp.read())
                with self._lock:
                    self._data = data
            except Exception:
                pass
            time.sleep(self.interval)


class RestClient:
    """Gestore globale dei poller per endpoint. Singleton.

    Uso:
        rc = RestClient.instance()
        rc.subscribe("/rest/watch/standings")     # avvia il poller (idempotente)
        data = rc.get("/rest/watch/standings")    # ultimo dato in cache
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._pollers: dict[str, _EndpointPoller] = {}
        self._plock = threading.Lock()

    @classmethod
    def instance(cls) -> "RestClient":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def subscribe(self, path: str, interval: float = 0.1):
        with self._plock:
            if path not in self._pollers:
                p = _EndpointPoller(path, interval)
                p.start()
                self._pollers[path] = p

    def get(self, path: str):
        with self._plock:
            p = self._pollers.get(path)
        return p.get() if p else None

    def stop_all(self):
        with self._plock:
            for p in self._pollers.values():
                p.stop()
            self._pollers.clear()
