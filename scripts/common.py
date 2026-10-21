"""Helpers compartidos: config, rutas por modo (pilot/full), GitHub, métricas por etapa."""
import argparse
import json
import os
import random
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["pilot", "full"], default=cfg.get("mode", "pilot"))
    p.add_argument("--force", action="store_true", help="rehacer la etapa aunque haya salida cacheada")
    args, _ = p.parse_known_args()
    cfg["mode"], cfg["force"] = args.mode, args.force
    if cfg["mode"] == "pilot":
        for section, vals in cfg["pilot"].get("overrides", {}).items():
            cfg[section].update(vals)
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    return cfg


def out_dir(cfg) -> Path:
    """Salidas de etapas: data/<modo>/. Las cachés de APIs (data/cache) se comparten entre modos."""
    d = ROOT / cfg["paths"]["data"] / cfg["mode"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir(cfg) -> Path:
    d = ROOT / cfg["paths"]["data"] / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clones_dir(cfg) -> Path:
    d = ROOT / cfg["paths"]["clones"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def gapfinder_conn(cfg) -> sqlite3.Connection:
    db = Path(cfg["paths"]["gapfinder_db"]).expanduser()
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def github_token(cfg) -> str:
    """Lee GITHUB_TOKEN del .env de gapfinder en runtime; no se copia a ningún lado."""
    for line in Path(cfg["paths"]["gapfinder_env"]).expanduser().read_text().splitlines():
        if line.startswith("GITHUB_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("GITHUB_TOKEN no encontrado")


class GitHub:
    def __init__(self, cfg):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {github_token(cfg)}",
                               "Accept": "application/vnd.github+json"})

    def _wait_if_limited(self, r):
        if r.status_code in (403, 429) or r.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(5, reset - time.time() + 2)
            print(f"  rate limit ({r.status_code}, {r.text[:120]!r}): espero {wait:.0f}s")
            time.sleep(wait)
            return True
        return False

    def search_repos(self, q: str, page: int) -> dict:
        while True:
            r = self.s.get("https://api.github.com/search/repositories",
                           params={"q": q, "per_page": 100, "page": page, "sort": "stars"}, timeout=60)
            if not self._wait_if_limited(r):
                break
        r.raise_for_status()
        print(f"  search p{page}: {q}")
        time.sleep(2.1)  # 30 req/min
        return r.json()

    def graphql(self, query: str) -> dict | None:
        """None si GitHub responde 5xx de forma persistente (consulta demasiado pesada): el que llama la parte."""
        for attempt in range(3):
            r = self.s.post("https://api.github.com/graphql", json={"query": query}, timeout=120)
            if self._wait_if_limited(r):
                continue
            if r.status_code >= 500:
                print(f"  graphql {r.status_code}, reintento")
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:  # respuesta cortada: igual que un 5xx
                print("  graphql: respuesta no JSON, reintento")
                time.sleep(3 * (attempt + 1))
        return None


def du(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    out = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True).stdout
    return int(out.split()[0]) * 1024 if out else 0


@contextmanager
def stage(cfg, name: str, outputs: list[Path]):
    """Mide tiempo y disco de una etapa y lo guarda en data/<modo>/stats.json, junto con el embudo."""
    info = {"funnel": {}}
    t0 = time.time()
    yield info
    stats_path = out_dir(cfg) / "stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    stats[name] = {"seconds": round(time.time() - t0, 1),
                   "bytes": sum(du(p) for p in outputs), **info}
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False))
    print(f"[{name}] {stats[name]['seconds']}s, {stats[name]['bytes'] / 2**20:.1f} MB")
    for k, v in info["funnel"].items():
        print(f"  {k}: {v}")
