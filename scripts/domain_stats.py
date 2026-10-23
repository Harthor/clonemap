"""Estadísticas de dominio por cluster (las usan la etapa 6 y s6b_annotate.py).

Todo se cuenta por owners (= repos: hay un repo por owner), no por funciones. Con k_d = owners del
dominio d en el cluster y N_d = owners del dominio d en toda la corrida (ídem k_ctrl, N_ctrl para el control):
- enriquecimiento de d = prevalencia en d / prevalencia en el control, con Laplace en los dos lados:
  ((k_d + a) / (N_d + 2a)) / ((k_ctrl + a) / (N_ctrl + 2a)). El dominio principal es el de mayor enriquecimiento.
- p = Fisher exacto unilateral (mayor) sobre la misma comparación: [[k_d, N_d - k_d], [k_ctrl, N_ctrl - k_ctrl]].
- q = Benjamini-Hochberg sobre los clusters con >= `specific_min_owners` owners del dominio principal
  (la familia que se filtra en el reporte).
- genérico = presencia alta en el control (k_ctrl / N_ctrl >= `generic_min_ctrl_prev`) y enriquecimiento
  < `generic_max_enr_ctrl`. Se marca, no se borra.
"""
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control, fisher_exact

CONTROL = "control"


def score_clusters(members: pd.DataFrame, owner_domain: pd.Series, R: dict, domains: list[str]) -> pd.DataFrame:
    """members: columnas topic, owner (topic >= 0). owner_domain: owner -> dominio (incluye 'control')."""
    a = R["laplace_alpha"]
    N = owner_domain.value_counts()
    if not N.get(CONTROL, 0):
        raise ValueError("el enriquecimiento se calcula contra el grupo control y no hay owners de control")
    doms = [d for d in domains if N.get(d, 0)]
    prev = lambda k, n: (k + a) / (n + 2 * a)
    rows = []
    for t, owners in members.groupby("topic").owner:
        cnt = owner_domain.loc[owners.unique()].value_counts()
        k = {d: int(cnt.get(d, 0)) for d in [*doms, CONTROL]}
        kc, nc = k[CONTROL], int(N[CONTROL])
        enr = {d: prev(k[d], N[d]) / prev(kc, nc) for d in doms}
        main = max(enr, key=enr.get)
        p = fisher_exact([[k[main], N[main] - k[main]], [kc, nc - kc]], alternative="greater").pvalue
        rows.append({"topic": t, "owners": sum(k[d] for d in doms), "owners_main": k[main],
                     "owners_control": kc, "domain_main": main,
                     "domain_prev": k[main] / N[main], "control_prev": kc / nc,
                     "enrichment": enr[main], "domain_p": float(p),
                     **{f"enr_{d}": v for d, v in enr.items()},
                     "generic": bool(kc / nc >= R["generic_min_ctrl_prev"] and enr[main] < R["generic_max_enr_ctrl"])})
    out = pd.DataFrame(rows)
    fam = out.owners_main >= R["specific_min_owners"]
    out["domain_q"] = np.nan
    if fam.any():
        out.loc[fam, "domain_q"] = false_discovery_control(out.loc[fam, "domain_p"].to_numpy(), method="bh")
    return out
