"""Etapa 7: reporte HTML estático local, en dos vistas que se linkean entre sí.

- report.html: top K clusters por OWNERS DISTINTOS (con código distinto: las copias cuentan una vez),
  mínimo `min_owners`.
- report_dominio.html: clusters enriquecidos en un dominio (q de Benjamini-Hochberg < `max_q`) con
  >= `specific_min_owners` owners de dominio, agrupados por dominio y ordenados por enriquecimiento
  (ver domain_stats.py). Los marcados como "genéricos" por el grupo control van en una sección aparte.
Por cluster: términos, conteos, estadísticas de dominio y 3–5 funciones de owners distintos, las más
cercanas al centroide, con código y link a GitHub en el commit exacto. Más un resumen con conteos,
tiempo y disco por etapa. No interpreta: es material para revisar a mano.
Salidas: data/<modo>/report.html, data/<modo>/report_dominio.html
Uso: uv run scripts/s7_report.py [--mode pilot|full]
"""
import html
import json
from datetime import datetime

import pandas as pd

from common import load_config, out_dir

cfg = load_config()
R = cfg["report"]
OUT = out_dir(cfg)
VIEWS = {"owners": OUT / "report.html", "dominio": OUT / "report_dominio.html"}
MAX_CODE_LINES = 60

fn = pd.read_parquet(OUT / "s4_functions.parquet").merge(pd.read_parquet(OUT / "s6_assign.parquet"), on="fid")
cl = pd.read_parquet(OUT / "s6_clusters.parquet")
stats = json.loads((OUT / "stats.json").read_text())
e = html.escape


def code_block(code: str) -> str:
    lines = code.splitlines()
    extra = f"\n# … ({len(lines) - MAX_CODE_LINES} líneas más)" if len(lines) > MAX_CODE_LINES else ""
    return f"<pre><code>{e(chr(10).join(lines[:MAX_CODE_LINES]) + extra)}</code></pre>"


def examples(topic: int) -> str:
    sub = fn[fn.topic == topic].sort_values("sim_centroid", ascending=False).drop_duplicates("owner")
    out = []
    for r in sub.head(R["examples_per_cluster"]).itertuples():
        copies = f" · {r.n_copies} copias en {r.copy_owners} owners" if r.n_copies > 1 else ""
        out.append(f"""<div class="ex"><div class="exh"><a href="{e(r.url)}" target="_blank" rel="noopener">
          {e(r.repo)}/{e(r.path)}</a> <span class="mono">{e(r.qualname)}</span>
          <span class="muted">· {r.domain} · sim {r.sim_centroid:.2f}{copies}</span></div>{code_block(r.code)}</div>""")
    return "\n".join(out)


def cluster_section(rank: int, c) -> str:
    doms = " · ".join(f"{k}: {int(v)}" for k, v in sorted(((k, v) for k, v in c.domains.items() if v), key=lambda kv: -kv[1]))
    terms = " ".join(f'<span class="term">{e(t)}</span>' for t in c.terms)
    return f"""<section class="cluster" id="c{c.topic}">
      <h2>#{rank} · cluster {c.topic}{' <span class="tag">genérico</span>' if c.generic else ''}{' <span class="tag">idiomático del framework</span>' if c.framework else ''}</h2>
      <div class="kpis"><span><b>{c.owners}</b> owners de dominio</span><span><b>{c.owners_control}</b> de control</span><span><b>{c.repos}</b> repos</span>
        <span><b>{c.n_functions}</b> variantes</span><span><b>{c.n_copias_total}</b> funciones incl. copias</span>
        <span><b>{c.owners_incl_copias}</b> owners incl. copias</span><span>cohesión {c.cohesion:.2f}</span>
        <span>owner con más funciones: {c.top_owner_share:.0%}</span></div>
      <div class="muted">owners por grupo: {e(doms)} · <b>{c.domain_main}</b>: enriquecimiento vs control <b>×{c.enrichment:.2f}</b>
        (en {c.domain_prev:.1%} de los repos {c.domain_main} vs {c.control_prev:.1%} del control; p={c.domain_p:.2g},
        q={"—" if pd.isna(c.domain_q) else f"{c.domain_q:.2g}"}) · métodos de clases base de Django/DRF: {c.framework_frac:.0%}</div>
      <div class="terms">{terms}</div>
      <details open><summary>Funciones representativas (owners distintos, más cercanas al centroide)</summary>
      {examples(c.topic)}</details></section>"""


def stats_table() -> str:
    rows = []
    for name, s in stats.items():
        funnel = "".join(f"<tr><td>{e(str(k))}</td><td class='num'>{e(str(v))}</td></tr>" for k, v in s["funnel"].items())
        rows.append(f"""<details><summary><b>{name}</b> — {s['seconds'] / 60:.1f} min · {s['bytes'] / 2**20:.0f} MB</summary>
          <table>{funnel}</table></details>""")
    return "\n".join(rows)


CSS = """<style>
:root { --bg:#fbfbfa; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dd; --code:#f2f1ec; --acc:#2f5d8a; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#e8e6e1; --muted:#9a988f; --line:#2c2b29; --code:#1f1e1c; --acc:#8db4dd; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,sans-serif; max-width:1100px; margin:0 auto; padding:24px 16px; }
a { color:var(--acc); } h1 { margin:0 0 4px; } h2 { margin:0 0 8px; font-size:18px; }
.muted { color:var(--muted); font-size:13px; } .mono { font-family:ui-monospace,Menlo,monospace; font-size:13px; }
.cluster { border-top:1px solid var(--line); padding:20px 0; }
.kpis { display:flex; flex-wrap:wrap; gap:14px; margin-bottom:4px; }
.terms { margin:8px 0; } .term { display:inline-block; background:var(--code); border-radius:4px; padding:1px 7px; margin:2px; font-family:ui-monospace,Menlo,monospace; font-size:13px; }
.ex { margin:12px 0; } .exh { font-size:13px; margin-bottom:4px; overflow-wrap:anywhere; }
pre { background:var(--code); padding:10px 12px; border-radius:6px; overflow-x:auto; font-size:12.5px; line-height:1.4; margin:0; }
table { border-collapse:collapse; margin:6px 0 10px; } td { border-bottom:1px solid var(--line); padding:2px 10px; font-size:13px; }
.tag { font-size:12px; font-weight:normal; background:var(--code); border:1px solid var(--line); border-radius:4px; padding:1px 6px; }
.num { text-align:right; font-variant-numeric:tabular-nums; } summary { cursor:pointer; }
ol { columns:2; font-size:13px; } @media (max-width:700px) { ol { columns:1; } }
</style>"""

def render(view: str, sections: list[tuple[str, pd.DataFrame]], intro: str) -> int:
    nav = " · ".join(f'<a href="{p.name}">{"por owners" if v == "owners" else "por dominio"}</a>'
                     if v != view else f'<b>{"por owners" if v == "owners" else "por dominio"}</b>'
                     for v, p in VIEWS.items())
    index, body, rank = [], [], 0
    for title, df in sections:
        if title:
            index.append(f"<h4>{e(title)} ({len(df)})</h4>")
            body.append(f"<h3>{e(title)}</h3>")
        items = []
        for c in df.itertuples():
            rank += 1
            items.append(f'<li><a href="#c{c.topic}">#{rank} · {c.owners} owners · {e(", ".join(list(c.terms)[:5]))}</a></li>')
            body.append(cluster_section(rank, c))
        index.append(f"<ol start='{rank - len(df) + 1}'>{''.join(items)}</ol>")
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>clonemap — {cfg['mode']} — {view}</title>
CSS</head><body>
<h1>clonemap · {cfg['mode']}</h1>
<p>Vista: {nav}</p>
<p class="muted">Generado {datetime.now():%Y-%m-%d %H:%M}. Clusters de funciones con intención parecida y código distinto.
{intro} Es material para revisión manual: un cluster no implica que falte una librería.
Cohesión = similitud coseno media al centroide (entre dos funciones al azar es ~0,23). Términos = identificadores usados por muchos
owners del cluster y por pocos otros clusters. Enriquecimiento = fracción de los repos del dominio que aparecen en el cluster dividida
por la fracción de los repos de control (~300 repos Python sin Django ni LLM) que aparecen, con Laplace en los dos lados; se cuenta por
repos, no por funciones. p = Fisher exacto unilateral sobre esa misma comparación; q = p corregido por Benjamini-Hochberg sobre los
clusters con ≥ {R['specific_min_owners']} owners del dominio. "Genérico" = el cluster aparece en ≥ {R['generic_min_ctrl_prev']:.0%}
de los repos de control y su enriquecimiento es &lt; ×{R['generic_max_enr_ctrl']:g}. "Idiomático del framework" = ≥ {R['framework_min_frac']:.0%}
de sus funciones son métodos de clases que heredan directamente de clases base de Django/DRF/Channels (por AST). Ambos se listan aparte, no se borran.
El control sale del corpus de gapfinder (casi todo ≥100 estrellas); los repos de dominio, mayormente de la Search API.</p>
<h3>Resumen por etapa</h3>{stats_table()}
<h3>Índice</h3>{''.join(index)}
{''.join(body)}
</body></html>"""
    VIEWS[view].write_text(page.replace("CSS", CSS, 1))
    return rank


by_owners = cl[cl.owners >= R["min_owners"]].sort_values(["owners", "cohesion"], ascending=False).head(R["top_k"])
n1 = render("owners", [("", by_owners)], f"Ordenados por owners distintos (mínimo {R['min_owners']}).")

def domain_sections(cl: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Sección de cada cluster en la vista por dominio (completa, sin cortar en top N), ordenada por owners.
    Base: >= specific_min_owners owners del dominio principal. Precedencia: framework > genérico > específico.
    Específico del dominio = <= specific_max_ctrl repos de control. Enriquecimiento y q son solo informativos."""
    base = cl[cl.owners_main >= R["specific_min_owners"]]
    order = ["owners_main", "owners"]
    out = {f"Específicos de {d}": base[(base.domain_main == d) & ~base.framework & ~base.generic
                                         & (base.owners_control <= R["specific_max_ctrl"])]
           for d in cfg["selection"]["domains"]}
    out["Idiomáticos del framework (métodos de clases base de Django/DRF)"] = base[base.framework]
    out["Marcados como genéricos (presencia alta en el grupo control)"] = base[base.generic & ~base.framework]
    return {k: v.sort_values(order, ascending=False) for k, v in out.items()}


if __name__ == "__main__":
    by_owners = cl[cl.owners >= R["min_owners"]].sort_values(["owners", "cohesion"], ascending=False).head(R["top_k"])
    n1 = render("owners", [("", by_owners)], f"Ordenados por owners distintos (mínimo {R['min_owners']}).")
    secs = domain_sections(cl)
    per_sec = max(1, R["top_k"] // len(cfg["selection"]["domains"]))
    n2 = render("dominio", [(t, df.head(per_sec)) for t, df in secs.items()],
                f"Específicos del dominio = ≥ {R['specific_min_owners']} owners del dominio principal y ≤ {R['specific_max_ctrl']} "
                f"repos de control; por sección (hasta {per_sec} por sección) y ordenados por owners. Enriquecimiento y q son informativos.")
    print(f"reporte: {VIEWS['owners']} ({n1} clusters), {VIEWS['dominio']} ({n2} clusters)")
