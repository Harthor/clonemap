"""Estadísticas de dominio por cluster (las usa la etapa 6; también sirve para re-puntuar un clustering viejo).

Por cluster, con n = owners del cluster (dominios + control) y k_d = owners del dominio d:
- enriquecimiento (vs base) = ((k_d + a) / (n + a·G)) / base_d, con suavizado de Laplace (a, G grupos)
  y base_d = owners de d / owners totales. El dominio principal es el de mayor enriquecimiento.
- p = binomial unilateral (k_d de n con prob. base_d); q = Benjamini-Hochberg sobre los clusters con
  >= `specific_min_owners` owners de dominio (la familia que se filtra en el reporte).
- enriquecimiento vs control = prevalencia en d / prevalencia en el grupo control, ambas suavizadas:
  (k_d + a) / (N_d + 2a)  ÷  (k_ctrl + a) / (N_ctrl + 2a).
- genérico = presencia alta en el control: fracción de los owners de control que aparecen en el cluster
  >= `generic_min_ctrl_prev` (se marca, no se borra; el cociente vs control queda como dato).
"""
import numpy as np
import pandas as pd
from scipy.stats import binomtest, false_discovery_control

CONTROL = "control"


def score_clusters(members: pd.DataFrame, owner_domain: pd.Series, R: dict, domains: list[str]) -> pd.DataFrame:
    """members: columnas topic, owner (topic >= 0). owner_domain: owner -> dominio (incluye 'control')."""
    a = R["laplace_alpha"]
    N = owner_domain.value_counts()
    groups = [d for d in domains if N.get(d, 0)] + ([CONTROL] if N.get(CONTROL, 0) else [])
    n_total = int(N[groups].sum())
    base = {d: N[d] / n_total for d in groups}
    rows = []
    for t, owners in members.groupby("topic").owner:
        doms = owner_domain.loc[owners.unique()].value_counts()
        n = int(doms.sum())
        k = {d: int(doms.get(d, 0)) for d in groups}
        enr = {d: ((k[d] + a) / (n + a * len(groups))) / base[d] for d in groups if d != CONTROL}
        main = max(enr, key=enr.get)
        row = {"topic": t, "owners": n - k.get(CONTROL, 0), "owners_control": k.get(CONTROL, 0),
               "domain_main": main, "domain_share": k[main] / n, "domain_base": base[main],
               "enrichment": enr[main],
               "domain_p": float(binomtest(k[main], n, base[main], alternative="greater").pvalue),
               **{f"enr_{d}": v for d, v in enr.items()}}
        if CONTROL in groups:
            prev = lambda d: (k[d] + a) / (N[d] + 2 * a)
            row["enr_vs_control"] = prev(main) / prev(CONTROL)
            row["control_prev"] = k[CONTROL] / N[CONTROL]
            row["generic"] = bool(row["control_prev"] >= R["generic_min_ctrl_prev"])
        else:
            row["enr_vs_control"], row["control_prev"], row["generic"] = np.nan, np.nan, False
        rows.append(row)
    out = pd.DataFrame(rows)
    fam = out.owners >= R["specific_min_owners"]
    out["domain_q"] = np.nan
    if fam.any():
        out.loc[fam, "domain_q"] = false_discovery_control(out.loc[fam, "domain_p"].to_numpy(), method="bh")
    return out
