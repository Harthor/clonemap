"""Etapa 2: clone shallow con sparse checkout de *.py, fijado al commit elegido en la etapa 1.

Los clones van a data/clones/<owner>__<repo> (compartidos entre pilot y full); un clone ya completo
(.clonemap_ok con el sha esperado) no se vuelve a bajar. Errores se registran y se sigue.
Salida: data/<modo>/s2_downloads.parquet
Uso: uv run scripts/s2_download.py [--mode pilot|full] [--force]
"""
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from common import clones_dir, du, load_config, out_dir, stage

cfg = load_config()
OUT = out_dir(cfg)
DST = OUT / "s2_downloads.parquet"
if DST.exists() and not cfg["force"]:
    print(f"ya existe {DST}; usar --force para rehacer")
    raise SystemExit

D = cfg["download"]
CLONES = clones_dir(cfg)
sel = pd.read_parquet(OUT / "s1_selected.parquet")


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=D["timeout_s"],
                       env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"})
    if r.returncode:
        raise RuntimeError(f"git {args[0]}: {r.stderr.strip()[-300:]}")
    return r.stdout


def clone(repo: str, sha: str) -> dict:
    path = CLONES / repo.replace("/", "__")
    ok = path / ".clonemap_ok"
    if ok.exists() and ok.read_text().strip() == sha:
        return {"repo": repo, "status": "cacheado", "path": str(path), "error": None}
    shutil.rmtree(path, ignore_errors=True)
    try:
        git("clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
            f"https://github.com/{repo}.git", str(path))
        git("sparse-checkout", "set", "--no-cone", "*.py", cwd=path)
        head = git("rev-parse", "HEAD", cwd=path).strip()
        if head != sha:  # la rama avanzó desde la etapa 1: se baja el commit exacto
            git("fetch", "--quiet", "--depth", "1", "--filter=blob:none", "origin", sha, cwd=path)
        git("checkout", "--quiet", sha, cwd=path)
        ok.write_text(sha)
        return {"repo": repo, "status": "ok", "path": str(path), "error": None}
    except Exception as e:  # noqa: BLE001 — se registra y se sigue
        shutil.rmtree(path, ignore_errors=True)
        return {"repo": repo, "status": "error", "path": None, "error": str(e)}


with stage(cfg, "s2_download", [DST, *[CLONES / r.replace("/", "__") for r in sel.repo]]) as st:
    rows = []
    with ThreadPoolExecutor(D["workers"]) as ex:
        futs = [ex.submit(clone, r.repo, r.sha) for r in sel.itertuples()]
        for i, f in enumerate(as_completed(futs), 1):
            rows.append(f.result())
            if rows[-1]["status"] == "error":
                print(f"  ERROR {rows[-1]['repo']}: {rows[-1]['error'][:150]}")
            if i % 25 == 0:
                print(f"  {i}/{len(futs)}")
    df = pd.DataFrame(rows).merge(sel[["repo", "owner", "sha", "domain"]], on="repo")
    df["bytes"] = [du(Path(p)) if p else 0 for p in df.path]
    df.to_parquet(DST)
    F = st["funnel"]
    F["repos_a_bajar"] = len(sel)
    for k, v in df.status.value_counts().items():
        F[f"  {k}"] = int(v)
    F["MB_clones"] = round(df.bytes.sum() / 2**20, 1)
