"""Etapa 9: resumen de utilidades reimplementadas confirmadas + ¿los repos ya declaran la librería?

Lee data/<modo>/etiquetado.csv (etapa 8). Para cada utilidad confirmada toma los repos del dominio que tienen
funciones en el cluster y sus dependencias declaradas, desde la caché de la etapa 1 (requirements*.txt, Pipfile,
pyproject.toml, setup.py, setup.cfg en la raíz; si no hay ninguno, los de un nivel abajo). Solo dependencias
DECLARADAS: lo que llega de forma transitiva (p. ej. langchain-text-splitters vía langchain) no cuenta.
Salidas: data/<modo>/uso_librerias.csv, data/<modo>/resumen_post.md
Uso: uv run scripts/s9_resumen.py [--mode full]
"""
import json
import sqlite3

import pandas as pd

from common import cache_dir, load_config, out_dir
from deps import dep_names, norm_pkg

cfg = load_config()
OUT = out_dir(cfg)
ROOT_DEPS = ("req", "pyproject", "setuppy", "setupcfg", "pipfile")
kv = sqlite3.connect(cache_dir(cfg) / "api_cache.sqlite")


def cget(ns, k):
    r = kv.execute("SELECT v FROM kv WHERE ns=? AND k=?", (ns, k)).fetchone()
    return json.loads(r[0]) if r else None


def repo_deps(repo: str) -> set[str] | None:
    """None si no hay metadata cacheada o el repo no declara dependencias en ningún archivo conocido."""
    m = cget("gql3", repo.lower()) or cget("gql2", repo.lower())
    if not m or m.get("missing"):
        return None
    texts = {k: (m.get(k) or {}).get("text") for k in ROOT_DEPS}
    if not any(texts.values()):
        sub = cget("gql3_sub", repo.lower()) or cget("gql2_sub", repo.lower()) or {}
        texts = {"req": "\n".join(t for p, t in sub.items() if not p.endswith((".toml", ".py"))),
                 "pyproject": "\n".join(t for p, t in sub.items() if p.endswith(".toml")),
                 "setuppy": "\n".join(t for p, t in sub.items() if p.endswith(".py"))}
    return dep_names(texts) if any(texts.values()) else None


lab = pd.read_csv(OUT / "etiquetado.csv").fillna("")
conf = lab[(lab.estado == "confirmado") & (lab.categoria_principal == "utilidad_reimplementada")]
fn = pd.read_parquet(OUT / "s4_functions.parquet", columns=["fid", "repo", "domain"]).merge(
    pd.read_parquet(OUT / "s6_assign.parquet")[["fid", "topic"]], on="fid")

rows = []
for r in conf.itertuples():
    libs = [x.split("==")[0] for x in r.librerias_verificadas.split("; ") if x and "inexistente" not in x]
    keys = {norm_pkg(x) for x in libs}
    repos = sorted(fn[(fn.topic == r.topic) & (fn.domain == r.dominio)].repo.unique())
    deps = {rp: repo_deps(rp) for rp in repos}
    known = [rp for rp, d in deps.items() if d is not None]
    with_any = [rp for rp in known if deps[rp] & keys]
    per_lib = {x: sum(norm_pkg(x) in deps[rp] for rp in known) for x in libs}
    rows.append({"dominio": r.dominio, "topic": r.topic, "descripcion": r.descripcion_principal, "owners": r.owners,
                 "repos_control": r.repos_control, "repos_cluster": len(repos), "repos_con_deps": len(known),
                 "repos_con_alguna_lib": len(with_any),
                 "pct_con_alguna_lib": round(100 * len(with_any) / len(known), 1) if known else None,
                 "por_libreria": "; ".join(f"{x}: {n}" for x, n in per_lib.items()),
                 "librerias": "; ".join(r.librerias_verificadas.split("; ")),
                 "ejemplo_1": r.ejemplo_1, "ejemplo_2": r.ejemplo_2})
use = pd.DataFrame(rows).sort_values("owners", ascending=False)
use.to_csv(OUT / "uso_librerias.csv", index=False)

L = cfg["label"]
md = ["# Utilidades reimplementadas confirmadas", "",
      f"Top {L['top_n']} por owners de cada dominio (específicos: ≥{cfg['report']['specific_min_owners']} owners, "
      f"≤{cfg['report']['specific_max_ctrl']} repos de control). Etiquetado: {L['model_main']} + {L['model_second']}; "
      "\"confirmado\" = los dos coinciden en la categoría. Las librerías son sugerencias de los modelos, verificadas solo en "
      "su existencia en PyPI, no en que resuelvan el problema. \"Ya la declaran\" = % de los repos del cluster (con "
      "dependencias declaradas) que listan alguna de esas librerías; no cuenta dependencias transitivas.", "",
      f"Clusters etiquetados: {len(lab)} · dudosos: {int((lab.estado == 'dudoso').sum())}", "",
      "| Dominio | Descripción | Owners | Repos de control | Librerías existentes (PyPI) | Ya la declaran | Ejemplos |",
      "|---|---|---|---|---|---|---|"]
for r in use.itertuples():
    existing = "; ".join(x for x in r.librerias.split("; ") if x and "inexistente" not in x) or "—"
    pct = f"{r.pct_con_alguna_lib:.0f} % ({r.repos_con_alguna_lib}/{r.repos_con_deps})" if r.repos_con_deps else "—"
    md.append(f"| {r.dominio} | {r.descripcion} | {r.owners} | {r.repos_control} | {existing} | {pct} | "
              f"[1]({r.ejemplo_1}) · [2]({r.ejemplo_2}) |")
(OUT / "resumen_post.md").write_text("\n".join(md) + "\n")
print(use[["dominio", "owners", "repos_cluster", "repos_con_deps", "repos_con_alguna_lib", "pct_con_alguna_lib",
           "por_libreria", "descripcion"]].to_string())
print(f"escrito {OUT / 'resumen_post.md'}")
