"""Etapa 9: resumen de utilidades reimplementadas confirmadas + ¿los repos ya declaran la librería?

Lee data/<modo>/etiquetado.csv (etapa 8). Confirmada = Jev 1.13 (no ambigua) y Haiku coinciden en
utilidad_reimplementada; descripción de Haiku; librerías = las que propuso Haiku, existen en PyPI y Jev acepta
(prob >= jev_lib_min_prob). Para cada utilidad confirmada toma los repos del dominio que tienen
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
conf = lab[(lab.estado == "confirmado") & (lab.categoria_jev == "utilidad_reimplementada")]
fn = pd.read_parquet(OUT / "s4_functions.parquet", columns=["fid", "repo", "domain"]).merge(
    pd.read_parquet(OUT / "s6_assign.parquet")[["fid", "topic"]], on="fid")

rows = []
for r in conf.itertuples():
    libs = [x.split("==")[0] for x in r.librerias_aceptadas.split("; ") if x]
    keys = {norm_pkg(x) for x in libs}
    repos = sorted(fn[(fn.topic == r.topic) & (fn.domain == r.dominio)].repo.unique())
    deps = {rp: repo_deps(rp) for rp in repos}
    known = [rp for rp, d in deps.items() if d is not None]
    with_any = [rp for rp in known if deps[rp] & keys]
    per_lib = {x: sum(norm_pkg(x) in deps[rp] for rp in known) for x in libs}
    rows.append({"seccion": r.seccion, "dominio": r.dominio, "topic": r.topic, "descripcion": r.descripcion_haiku,
                 "owners": r.owners, "pct_dominio": r.pct_dominio, "pct_control": r.pct_control,
                 "repos_control": r.repos_control, "repos_cluster": len(repos), "repos_con_deps": len(known),
                 "repos_con_alguna_lib": len(with_any),
                 "pct_con_alguna_lib": round(100 * len(with_any) / len(known), 1) if known else None,
                 "por_libreria": "; ".join(f"{x}: {n}" for x, n in per_lib.items()),
                 "librerias": r.librerias_aceptadas, "librerias_jev": r.librerias_jev,
                 "ejemplo_1": r.ejemplo_1, "ejemplo_2": r.ejemplo_2})
use = pd.DataFrame(rows, columns=["seccion", "dominio", "topic", "descripcion", "owners", "pct_dominio", "pct_control",
                                  "repos_control", "repos_cluster", "repos_con_deps", "repos_con_alguna_lib",
                                  "pct_con_alguna_lib", "por_libreria", "librerias", "librerias_jev", "ejemplo_1",
                                  "ejemplo_2"]).sort_values("owners", ascending=False)
use.to_csv(OUT / "uso_librerias.csv", index=False)

L = cfg["label"]
amb = int(lab.jev_ambigua.astype(str).eq("True").sum())
md = ["# Utilidades reimplementadas confirmadas", "",
      f"Clusters etiquetados: top {L['top_n']} por owners de cada dominio entre los específicos (≥{cfg['report']['specific_min_owners']} "
      f"owners, ≤{cfg['report']['specific_max_ctrl']} repos de control) y top {L['top_nonexclusive']} de los enriquecidos no exclusivos "
      f"(>{cfg['report']['specific_max_ctrl']} repos de control, cociente ≥×{cfg['report']['generic_max_enr_ctrl']:g}). "
      f"Categoría: {L['jev_model']} (4 proposiciones, gana la más probable; \"ambigua\" si le gana a la segunda por menos de "
      f"{L['jev_ambiguous_margin']}) y {L['model_second']}; \"confirmado\" = Jev no ambiguo y Haiku coinciden. Descripción: Haiku. "
      f"Librerías: las que propuso Haiku que existen en PyPI y que Jev acepta (probabilidad ≥{L['jev_lib_min_prob']}) para "
      "\"resuelve directamente\" la descripción. \"Ya la declaran\" = % de los repos del cluster que listan alguna de esas "
      "librerías en sus dependencias declaradas (no cuenta dependencias transitivas).", "",
      f"Clusters etiquetados: {len(lab)} · confirmados: {int((lab.estado == 'confirmado').sum())} · "
      f"dudosos: {int((lab.estado == 'dudoso').sum())} (de esos, {amb} con Jev ambiguo)", "",
      "| Sección | Dominio | Descripción | Owners | % dominio / % control | Librerías aceptadas (PyPI) | Ya la declaran | Ejemplos |",
      "|---|---|---|---|---|---|---|---|"]
for r in use.itertuples():
    pct = f"{r.pct_con_alguna_lib:.0f} % ({r.repos_con_alguna_lib}/{r.repos_con_deps})" if r.librerias and r.repos_con_deps else "—"
    md.append(f"| {r.seccion} | {r.dominio} | {r.descripcion} | {r.owners} | {r.pct_dominio:g} % / {r.pct_control:g} % "
              f"({r.repos_control} repos) | {r.librerias or '—'} | {pct} | [1]({r.ejemplo_1}) · [2]({r.ejemplo_2}) |")
ne = lab[lab.seccion == "enriquecido no exclusivo"]
md += ["", "## Enriquecidos no exclusivos (todos los etiquetados)", "",
       f"En el control aparecen en más de {cfg['report']['specific_max_ctrl']} repos, pero proporcionalmente ≥×"
       f"{cfg['report']['generic_max_enr_ctrl']:g} más en el dominio. La sección tiene {len(ne)} clusters en total.", "",
       "| # | Dominio | Descripción (Haiku) | Owners | % dominio | % control | Jev | Haiku | Estado |", "|---|---|---|---|---|---|---|---|---|"]
for r in ne.itertuples():
    jv = r.categoria_jev + (" (ambigua)" if str(r.jev_ambigua) == "True" else "")
    md.append(f"| {r.puesto} | {r.dominio} | {r.descripcion_haiku} | {r.owners} | {r.pct_dominio:g} % | {r.pct_control:g} % | "
              f"{jv} | {r.categoria_haiku} | {r.estado} |")
(OUT / "resumen_post.md").write_text("\n".join(md) + "\n")
print(use[["seccion", "dominio", "owners", "repos_cluster", "repos_con_deps", "repos_con_alguna_lib", "pct_con_alguna_lib",
           "por_libreria", "descripcion"]].to_string())
print(f"escrito {OUT / 'resumen_post.md'}")
