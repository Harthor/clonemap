"""Etapa 10: exporta site/data.json para el explorador estático (site/index.html, GitHub Pages).

Textos públicos en inglés: nombre y descripción de la etapa 8b (las descripciones de la etapa 8 están en español
y no se exportan). Incluye solo lo necesario: por dominio, el top `site_top_n` por owners de cada sección de la vista por dominio
(específico, enriquecido no exclusivo, genérico, framework), más todos los clusters etiquetados.
Por cluster: descripción (Haiku si está etiquetado), términos, owners, % del dominio vs % del control, etiquetas,
librerías aceptadas por Jev y % de repos que ya las declaran, y hasta `site_examples` ejemplos de owners
distintos del dominio (los más cercanos al centroide).
Del código ajeno NO se copia la función: solo sus primeras `site_snippet_lines` líneas (la firma) y el link al
archivo en GitHub en el commit exacto.
Uso: uv run scripts/s10_export_site.py [--mode full]
"""
import json
import textwrap
from datetime import date

import pandas as pd

from common import ROOT
from s7_report import R, cfg, cl, domain_sections, fn, OUT

S = cfg["site"]
SECTION_IDS = {"Específicos de": "specific", "Enriquecidos no exclusivos": "nonexclusive",
               "Idiomáticos del framework": "framework", "Marcados como genéricos": "generic"}


def section_id(title: str) -> str:
    return next(v for k, v in SECTION_IDS.items() if title.startswith(k))


def snippet(code: str) -> str:
    """Las primeras líneas de la función (firma incluida), sin el resto del cuerpo."""
    lines = textwrap.dedent(code).splitlines()
    return "\n".join(lines[:S["site_snippet_lines"]])


def nan_none(x):
    return None if pd.isna(x) else x


lab = pd.read_csv(OUT / "etiquetado.csv").set_index("topic")
en = pd.read_csv(OUT / "descripciones_en.csv").set_index("topic")  # nombre y descripción en inglés (etapa 8b)
use = pd.read_csv(OUT / "uso_librerias.csv").set_index("topic")
secs = {}  # "Específicos de django" y "de llm" van a la misma sección: se concatenan, ordenadas por owners
for t, df in domain_sections(cl).items():
    secs[section_id(t)] = pd.concat([secs.get(section_id(t), df.iloc[:0]), df]).sort_values(
        ["owners_main", "owners"], ascending=False)

picked = {}  # topic -> sección
for sid, df in secs.items():
    for d in cfg["selection"]["domains"]:
        for t in df[df.domain_main == d].head(S["site_top_n"]).topic:
            picked.setdefault(t, sid)
for t in lab.index:
    picked.setdefault(t, next(sid for sid, df in secs.items() if t in set(df.topic)))

clusters = []
for t, sid in picked.items():
    c = cl.set_index("topic").loc[t]
    d = c.domain_main
    ex = fn[(fn.topic == t) & (fn.domain == d)].sort_values("sim_centroid", ascending=False).drop_duplicates("owner")
    item = {
        "id": int(t), "domain": d, "section": sid, "terms": list(c.terms)[:8],
        "owners": int(c.owners_main), "owners_control": int(c.owners_control),
        "pct_domain": round(100 * c.domain_prev, 1), "pct_control": round(100 * c.control_prev, 1),
        "enrichment": round(float(c.enrichment), 2), "variants": int(c.n_functions), "cohesion": round(float(c.cohesion), 2),
        "examples": [{"repo": r.repo, "path": r.path, "name": r.qualname, "url": r.url, "lines": f"{r.start}-{r.end}",
                      "snippet": snippet(r.code)} for r in ex.head(S["site_examples"]).itertuples()],
    }
    if t in lab.index:
        lr = lab.loc[t]
        item["label"] = {
            "name": en.loc[t, "name_en"], "description": en.loc[t, "description_en"], "jev": lr.categoria_jev, "jev_ambiguous": bool(lr.jev_ambigua),
            "jev_probs": {k: float(lr[f"jev_p_{k}"]) for k in ("uso_sdk", "idiomatico_framework", "utilidad_reimplementada", "otro")},
            "haiku": lr.categoria_haiku, "status": lr.estado,
            "libraries": [x for x in str(nan_none(lr.librerias_aceptadas) or "").split("; ") if x],
            "libraries_rejected": [x.split(": ")[0] for x in str(nan_none(lr.librerias_jev) or "").split("; ")
                                   if x and float(x.split(": ")[1]) < cfg["label"]["jev_lib_min_prob"]],
        }
        if t in use.index:
            u = use.loc[t]
            item["label"]["already_declared_pct"] = nan_none(u.pct_con_alguna_lib) if item["label"]["libraries"] else None
            item["label"]["already_declared"] = f"{int(u.repos_con_alguna_lib)}/{int(u.repos_con_deps)}"
    clusters.append(item)
clusters.sort(key=lambda x: -x["owners"])

st = json.loads((OUT / "stats.json").read_text())
f1, f3, f4, f6 = (st[k]["funnel"] for k in ("s1_select", "s3_parse", "s4_dedup", "s6_cluster"))
sizes = {k.split(":")[1]: int(v) for k, v in f1.items() if k.strip().startswith("dominio:")}  # repos seleccionados
data = {
    "generated": str(date.today()),
    "run": {"repos": sizes, "candidates_evaluated": f1["evaluados_con_graphql"], "candidate_pool": f1["pool_total"],
            "functions": f3["funciones_finales"], "variants": f4["representantes"], "clusters": f6["clusters"],
            "clusters_8_owners": f6["clusters_con_>=8_owners"], "section_sizes": {k: len(v) for k, v in secs.items()},
            "llm_cost_usd": S["llm_cost_usd"]},
    "params": {"specific_max_ctrl": R["specific_max_ctrl"], "min_owners": R["specific_min_owners"],
               "generic_min_ctrl_prev": R["generic_min_ctrl_prev"], "generic_max_enr_ctrl": R["generic_max_enr_ctrl"],
               "framework_min_frac": R["framework_min_frac"], "jev_lib_min_prob": cfg["label"]["jev_lib_min_prob"],
               "jev_ambiguous_margin": cfg["label"]["jev_ambiguous_margin"]},
    "headline": next(c for c in clusters if c["id"] == S["headline_topic"]),
    "clusters": clusters,
}
dst = ROOT / "site" / "data.json"
dst.parent.mkdir(exist_ok=True)
dst.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
print(f"escrito {dst}: {len(clusters)} clusters, {dst.stat().st_size / 1024:.0f} KB")
