"""Hoja de revisión manual: los N primeros clusters de un dominio en el orden de la vista por dominio,
con owners, enriquecimiento, q y K funciones de ejemplo de owners distintos del dominio, elegidas al azar
con la seed de config, con el código completo y el link al archivo en GitHub (commit exacto).
Salida: data/<modo>/revision_top<N>_<dominio>.md
Uso: uv run scripts/review_sheet.py [--mode pilot|full] [--domain llm] [--top 10] [--k 6]
"""
import argparse
import random

import pandas as pd

from s7_report import R, cfg, cl, domain_sections, fn, OUT

p = argparse.ArgumentParser()
p.add_argument("--domain", default="llm")
p.add_argument("--top", type=int, default=10)
p.add_argument("--k", type=int, default=6)
args, _ = p.parse_known_args()

top = domain_sections(cl)[f"Enriquecidos en {args.domain}"].head(args.top)
rng = random.Random(cfg["seed"])
md = [f"# Revisión manual: top {args.top} clusters de {args.domain} ({cfg['mode']})", "",
      f"Orden de la vista por dominio: enriquecimiento contra el control (≥{R['specific_min_owners']} owners del dominio, "
      f"q<{R['max_q']}, sin genéricos ni idiomáticos del framework). {args.k} funciones por cluster, de owners distintos "
      f"del dominio, elegidas al azar (seed {cfg['seed']}), no las más cercanas al centroide.", ""]
for i, c in enumerate(top.itertuples(), 1):
    sub = fn[(fn.topic == c.topic) & (fn.domain == args.domain)].sort_values("fid")
    owners = sorted(sub.owner.unique())
    rng.shuffle(owners)
    picks = [sub[sub.owner == o].sample(1, random_state=rng.randrange(2**31)).iloc[0] for o in owners[:args.k]]
    md += [f"## {i}. Cluster {c.topic}: {', '.join(list(c.terms)[:6])}", "",
           f"- Owners del dominio: **{c.owners_main}** ({c.domain_prev:.1%} de los repos {args.domain}); "
           f"de control: {c.owners_control} ({c.control_prev:.1%})",
           f"- Enriquecimiento vs control: **×{c.enrichment:.2f}** · p={c.domain_p:.2g} · q={c.domain_q:.2g}",
           f"- Funciones en el cluster: {c.n_functions} · cohesión {c.cohesion:.2f} · "
           f"owner con más funciones: {c.top_owner_share:.0%}", ""]
    for j, r in enumerate(picks, 1):
        md += [f"### {i}.{j} `{r.qualname}` — [{r.repo}/{r.path}#L{r.start}-L{r.end}]({r.url})", "",
               "```python", r.code.rstrip(), "```", ""]
dst = OUT / f"revision_top{args.top}_{args.domain}.md"
dst.write_text("\n".join(md))
print(f"escrito {dst} ({len(top)} clusters)")
