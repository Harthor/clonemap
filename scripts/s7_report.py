"""Etapa 7: reporte HTML estático local.

Top K clusters ordenados por OWNERS DISTINTOS (con código distinto: las copias cuentan una vez),
con mínimo `min_owners`. Por cluster: términos c-TF-IDF, conteos y 3–5 funciones de owners distintos,
las más cercanas al centroide, con código y link a GitHub en el commit exacto.
Incluye un resumen con conteos, tiempo y disco por etapa. No interpreta: es material para revisar a mano.
Salida: data/<modo>/report.html
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
DST = OUT / "report.html"
MAX_CODE_LINES = 60

fn = pd.read_parquet(OUT / "s4_functions.parquet").merge(pd.read_parquet(OUT / "s6_assign.parquet"), on="fid")
cl = pd.read_parquet(OUT / "s6_clusters.parquet")
stats = json.loads((OUT / "stats.json").read_text())
top = cl[cl.owners >= R["min_owners"]].sort_values(["owners", "cohesion"], ascending=False).head(R["top_k"])
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
      <h2>#{rank} · cluster {c.topic}</h2>
      <div class="kpis"><span><b>{c.owners}</b> owners distintos</span><span><b>{c.repos}</b> repos</span>
        <span><b>{c.n_functions}</b> variantes</span><span><b>{c.n_copias_total}</b> funciones incl. copias</span>
        <span><b>{c.owners_incl_copias}</b> owners incl. copias</span><span>cohesión {c.cohesion:.2f}</span>
        <span>owner con más funciones: {c.top_owner_share:.0%}</span></div>
      <div class="muted">owners por dominio: {e(doms)}</div>
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


index = "".join(f'<li><a href="#c{c.topic}">#{i} · {c.owners} owners · {e(", ".join(list(c.terms)[:5]))}</a></li>'
                for i, c in enumerate(top.itertuples(), 1))
body = "\n".join(cluster_section(i, c) for i, c in enumerate(top.itertuples(), 1))
page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>clonemap — {cfg['mode']}</title>
<style>
:root {{ --bg:#fbfbfa; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dd; --code:#f2f1ec; --acc:#2f5d8a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161615; --fg:#e8e6e1; --muted:#9a988f; --line:#2c2b29; --code:#1f1e1c; --acc:#8db4dd; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,sans-serif; max-width:1100px; margin:0 auto; padding:24px 16px; }}
a {{ color:var(--acc); }} h1 {{ margin:0 0 4px; }} h2 {{ margin:0 0 8px; font-size:18px; }}
.muted {{ color:var(--muted); font-size:13px; }} .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:13px; }}
.cluster {{ border-top:1px solid var(--line); padding:20px 0; }}
.kpis {{ display:flex; flex-wrap:wrap; gap:14px; margin-bottom:4px; }}
.terms {{ margin:8px 0; }} .term {{ display:inline-block; background:var(--code); border-radius:4px; padding:1px 7px; margin:2px; font-family:ui-monospace,Menlo,monospace; font-size:13px; }}
.ex {{ margin:12px 0; }} .exh {{ font-size:13px; margin-bottom:4px; overflow-wrap:anywhere; }}
pre {{ background:var(--code); padding:10px 12px; border-radius:6px; overflow-x:auto; font-size:12.5px; line-height:1.4; margin:0; }}
table {{ border-collapse:collapse; margin:6px 0 10px; }} td {{ border-bottom:1px solid var(--line); padding:2px 10px; font-size:13px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }} summary {{ cursor:pointer; }}
ol {{ columns:2; font-size:13px; }} @media (max-width:700px) {{ ol {{ columns:1; }} }}
</style></head><body>
<h1>clonemap · {cfg['mode']}</h1>
<p class="muted">Generado {datetime.now():%Y-%m-%d %H:%M}. Clusters de funciones con intención parecida y código distinto,
ordenados por owners distintos (mínimo {R['min_owners']}). Es material para revisión manual: un cluster no implica que falte una librería.
Cohesión = similitud coseno media al centroide (entre dos funciones al azar es ~0,23). Términos = identificadores usados por muchos owners del cluster y por pocos otros clusters.</p>
<h3>Resumen por etapa</h3>{stats_table()}
<h3>Top {len(top)} clusters</h3><ol>{index}</ol>
{body}
</body></html>"""
DST.write_text(page)
print(f"reporte: {DST} ({len(top)} clusters)")
