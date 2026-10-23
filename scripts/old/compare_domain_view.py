"""Compara el top 20 por dominio de la vista por dominio con tres criterios, sobre el piloto:

A. antes: especificidad cruda >= 80 % y >= 8 owners, ordenado por owners (clustering sin control).
B. mismo clustering que A, re-puntuado con enriquecimiento (Laplace) + q de Benjamini-Hochberg < max_q.
C. pipeline nuevo: clustering con grupo control, q < max_q, sin los marcados como genéricos.
Sigue además los clusters "utilitarios" (argparse, logging, yaml) para ver dónde quedan en cada uno.
Salida: docs/comparacion_dominio.md
Uso: uv run scripts/compare_domain_view.py
"""
import re

import pandas as pd

from common import ROOT, load_config, out_dir
from domain_stats import score_clusters

cfg = load_config()
R, DOMS = cfg["report"], cfg["selection"]["domains"]
OUT = out_dir(cfg)
BEFORE = OUT / "antes_enriquecimiento"
TOP = 20
UTIL = re.compile(r"^(argparse|argument|parser|logging|formatter|handlers|levelname|yaml)$")

# A y B: clustering viejo
old_cl = pd.read_parquet(BEFORE / "s6_clusters.parquet")
old_fn = pd.read_parquet(BEFORE / "s4_functions.parquet", columns=["fid", "owner", "domain"]).merge(
    pd.read_parquet(BEFORE / "s6_assign.parquet"), on="fid")
A = old_cl[(old_cl.owners >= 8) & (old_cl.domain_share >= 0.8)].sort_values(["owners", "cohesion"], ascending=False)
rescored = score_clusters(old_fn[old_fn.topic >= 0][["topic", "owner"]],
                          old_fn.drop_duplicates("owner").set_index("owner").domain, R, DOMS)
B_all = old_cl[["topic", "terms", "cohesion"]].merge(rescored, on="topic")
B = B_all[(B_all.owners >= R["specific_min_owners"]) & (B_all.domain_q < R["max_q"])].sort_values(
    ["enrichment", "owners"], ascending=False)

# C: clustering nuevo con control
new_cl = pd.read_parquet(OUT / "s6_clusters.parquet")
C_all = new_cl[(new_cl.owners >= R["specific_min_owners"]) & (new_cl.domain_q < R["max_q"])].sort_values(
    ["enrichment", "owners"], ascending=False)
C, C_gen = C_all[~C_all.generic], C_all[C_all.generic]


def is_util(terms) -> bool:
    return any(UTIL.match(t) for t in list(terms)[:6])


def table(df: pd.DataFrame, cols: list[str]) -> str:
    lines = ["| # | owners | " + " | ".join(cols) + " | términos |", "|---|---|" + "---|" * len(cols) + "---|"]
    for i, r in enumerate(df.head(TOP).itertuples(), 1):
        mark = " **[util]**" if is_util(r.terms) else ""
        vals = []
        for c in cols:
            v = getattr(r, c)
            vals.append(f"{v:.0%}" if c == "domain_share" else f"×{v:.2f}" if c.startswith("enr") else
                        f"{v:.1g}" if c == "domain_q" else str(v))
        lines.append(f"| {i} | {r.owners} | " + " | ".join(vals) + f" | {', '.join(list(r.terms)[:6])}{mark} |")
    return "\n".join(lines)


def util_ranks(df: pd.DataFrame, dom: str) -> str:
    sub = df[df.domain_main == dom].reset_index(drop=True)
    hits = [f"#{i + 1}" for i, t in enumerate(sub.terms) if is_util(t)]
    top = [h for h in hits if int(h[1:]) <= TOP]
    return f"{len(top)} en el top {TOP} ({', '.join(top) or '—'}); {len(hits)} en total"


md = [f"# Vista por dominio: antes y después (piloto, {pd.Timestamp.now():%Y-%m-%d})", "",
      "`[util]` = cluster cuyos primeros términos incluyen argparse/argument/parser/logging/formatter/handlers/levelname/yaml.", "",
      "| | Criterio | Clusters que pasan | django | llm |", "|---|---|---|---|---|",
      f"| A | especificidad ≥80 %, ≥8 owners, orden por owners | {len(A)} | {(A.domain_main == 'django').sum()} | {(A.domain_main == 'llm').sum()} |",
      f"| B | enriquecimiento + q<{R['max_q']} (mismo clustering que A) | {len(B)} | {(B.domain_main == 'django').sum()} | {(B.domain_main == 'llm').sum()} |",
      f"| C | B + grupo control, sin genéricos (clustering nuevo) | {len(C)} | {(C.domain_main == 'django').sum()} | {(C.domain_main == 'llm').sum()} |",
      f"| C′ | marcados como genéricos por el control | {len(C_gen)} | {(C_gen.domain_main == 'django').sum()} | {(C_gen.domain_main == 'llm').sum()} |", "",
      "## Dónde quedan los clusters utilitarios", "", "| | django | llm |", "|---|---|---|"]
for name, df in (("A", A), ("B", B), ("C", C), ("C′ genéricos", C_gen)):
    md.append(f"| {name} | {util_ranks(df, 'django')} | {util_ranks(df, 'llm')} |")
for dom in DOMS:
    md += ["", f"## {dom}", "", f"### A · antes (top {TOP})", "", table(A[A.domain_main == dom], ["domain_share"]),
           "", f"### B · enriquecimiento + BH, sin control (top {TOP})", "",
           table(B[B.domain_main == dom], ["domain_share", "enrichment", "domain_q"]),
           "", f"### C · con control, sin genéricos (top {TOP})", "",
           table(C[C.domain_main == dom], ["owners_control", "enrichment", "domain_q", "enr_vs_control"]),
           "", f"### C′ · marcados como genéricos (top {TOP})", "",
           table(C_gen[C_gen.domain_main == dom], ["owners_control", "enrichment", "domain_q", "enr_vs_control"])]
dst = ROOT / "docs" / "comparacion_dominio.md"
dst.write_text("\n".join(md) + "\n")
print(f"escrito {dst}")
