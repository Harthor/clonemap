"""Etapa 6b: anota los clusters de la etapa 6 sin re-clusterizar.

- Estadísticas de dominio contra el grupo control (domain_stats.py): enriquecimiento, p de Fisher, q de BH,
  marca de "genérico".
- Marca de "idiomático del framework" (framework.py): fracción de las funciones del cluster que son métodos
  de clases que heredan directamente de clases base de Django/DRF/Channels; marcado si >= `framework_min_frac`.
Reescribe esas columnas en data/<modo>/s6_clusters.parquet (idempotente: siempre recalcula desde s4/s6_assign).
Uso: uv run scripts/s6b_annotate.py [--mode pilot|full]
"""
import pandas as pd

from common import clones_dir, load_config, out_dir, stage
from domain_stats import score_clusters
from framework import framework_methods

LEGACY = ["domain_base", "domain_share", "enr_vs_control"]  # columnas de la versión anterior de domain_stats

if __name__ == "__main__":
    cfg = load_config()
    R = cfg["report"]
    OUT = out_dir(cfg)
    CLUSTERS = OUT / "s6_clusters.parquet"
    with stage(cfg, "s6b_annotate", [CLUSTERS]) as st:
        F = st["funnel"]
        fn = pd.read_parquet(OUT / "s4_functions.parquet",
                             columns=["fid", "repo", "owner", "domain", "path", "start", "is_method"])
        fn = fn.merge(pd.read_parquet(OUT / "s6_assign.parquet")[["fid", "topic"]], on="fid")
        inc = fn[fn.topic >= 0]

        dstats = score_clusters(inc[["topic", "owner"]], fn.drop_duplicates("owner").set_index("owner").domain,
                                R, cfg["selection"]["domains"])

        sel = pd.read_parquet(OUT / "s1_selected.parquet")
        django_repos = set(sel.repo[sel.domains.map(lambda d: "django" in list(d))])
        fw = framework_methods(inc, clones_dir(cfg), django_repos, cfg["parse"]["workers"])
        frac = inc.assign(fw=inc.fid.map(fw)).groupby("topic").fw.mean().rename("framework_frac")

        cl = pd.read_parquet(CLUSTERS)
        cl = cl.drop(columns=[c for c in [*dstats.columns, *LEGACY, "framework_frac", "framework"]
                              if c in cl.columns and c != "topic"])
        cl = cl.merge(dstats, on="topic").merge(frac.reset_index(), on="topic")
        cl["framework"] = cl.framework_frac >= R["framework_min_frac"]
        cl.to_parquet(CLUSTERS)

        F["metodos_de_clases_framework"] = int(fw.sum())
        fam = cl[cl.owners_main >= R["specific_min_owners"]]
        spec = fam[(fam.owners_control <= R["specific_max_ctrl"]) & ~fam.framework & ~fam.generic]
        for d in cfg["selection"]["domains"]:
            F[f"especificos_(<= {R['specific_max_ctrl']} control):{d}"] = int((spec.domain_main == d).sum())
        F["  genericos"] = int(fam.generic.sum())
        F["  framework"] = int(fam.framework.sum())
        F["  genericos_y_framework"] = int((fam.generic & fam.framework).sum())
        F["clusters_framework_total"] = int(cl.framework.sum())
