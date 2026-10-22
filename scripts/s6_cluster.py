"""Etapa 6: clustering con BERTopic (UMAP + HDBSCAN), sin representación por LLM.

Prefiltro kNN opcional (FAISS): solo pasan funciones con al menos `knn_min_other_owners` vecinos de
OTROS owners con similitud coseno >= `knn_sim`. Una función sin vecinos de otros owners no puede
terminar en un cluster con muchos owners, y así UMAP entra en 8 GB de RAM.
Dominio por cluster (domain_stats.py): enriquecimiento con Laplace vs base, q de Benjamini-Hochberg,
enriquecimiento vs grupo control y marca de "genérico". `owners` cuenta solo owners de dominio (sin control).
Términos: identificadores partidos (snake_case / camelCase) ponderados por owners distintos x idf entre
clusters; también se guarda el c-TF-IDF de BERTopic (terms_ctfidf), que tiende a reflejar al owner dominante.
Salidas: data/<modo>/s6_assign.parquet (fid, topic, sim_centroide), data/<modo>/s6_clusters.parquet
Uso: uv run scripts/s6_cluster.py [--mode pilot|full] [--force]
"""
import keyword
import re

import faiss
import numpy as np
import pandas as pd
from bertopic import BERTopic
from hdbscan import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP

from common import load_config, out_dir, stage
from domain_stats import score_clusters

cfg = load_config()
C = cfg["cluster"]
OUT = out_dir(cfg)
ASSIGN, CLUSTERS = OUT / "s6_assign.parquet", OUT / "s6_clusters.parquet"
if CLUSTERS.exists() and not cfg["force"]:
    print(f"ya existe {CLUSTERS}; usar --force para rehacer")
    raise SystemExit

STOP = set(keyword.kwlist) | {
    "self", "cls", "none", "true", "false", "return", "args", "kwargs", "str", "int", "float", "bool",
    "dict", "list", "tuple", "set", "len", "print", "isinstance", "super", "init", "get", "the", "and",
    "for", "not", "with", "from", "import", "def", "class", "value", "data", "result", "res", "obj", "item",
    "key", "val", "name", "type", "range", "enumerate", "append", "format", "raise", "except", "try", "elif"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STRING = re.compile(r"(\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"[^\"\n]*\"|'[^'\n]*')")


def ident_words(code: str) -> str:
    words = []
    for ident in IDENT.findall(STRING.sub(" ", re.sub(r"#[^\n]*", " ", code))):
        for part in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", ident).split("_"):
            w = part.lower()
            if len(w) > 2 and w not in STOP and not w.isdigit():
                words.append(w)
    return " ".join(words)


with stage(cfg, "s6_cluster", [ASSIGN, CLUSTERS]) as st:
    F = st["funnel"]
    fn = pd.read_parquet(OUT / "s4_functions.parquet")
    ids = pd.read_parquet(OUT / "s5_ids.parquet")
    emb = np.load(OUT / "s5_embeddings.npy").astype(np.float32)
    fn = fn.set_index("fid").loc[ids.fid].reset_index()
    F["funciones_entrada"] = len(fn)

    use_pref = C["prefilter"] == "on" or (C["prefilter"] == "auto" and len(fn) > C["prefilter_auto_above"])
    if use_pref:
        index = faiss.IndexFlatIP(emb.shape[1])
        index.add(emb)
        k = C["knn_k"] + 1
        owners = fn.owner.astype("category").cat.codes.to_numpy()
        keep = np.zeros(len(fn), bool)
        for s in range(0, len(fn), 20000):
            sims, nbr = index.search(emb[s:s + 20000], k)
            for row in range(len(nbr)):
                i = s + row
                ok = (sims[row] >= C["knn_sim"]) & (nbr[row] >= 0)
                other = set(owners[nbr[row][ok]]) - {owners[i]}
                keep[i] = len(other) >= C["knn_min_other_owners"]
        fn, emb = fn[keep].reset_index(drop=True), emb[keep]
        F["prefiltro_knn"] = f"sí (sim>={C['knn_sim']}, >= {C['knn_min_other_owners']} otros owners en {C['knn_k']} vecinos)"
    else:
        F["prefiltro_knn"] = "no"
    F["funciones_a_bertopic"] = len(fn)

    docs = [ident_words(f"{q.replace('.', ' ')}\n{c}") or "empty" for q, c in zip(fn.qualname, fn.code)]
    topic_model = BERTopic(
        embedding_model=None,
        umap_model=UMAP(n_neighbors=C["umap_n_neighbors"], n_components=C["umap_n_components"], min_dist=0.0,
                        metric="cosine", random_state=cfg["seed"], low_memory=True),
        hdbscan_model=HDBSCAN(min_cluster_size=C["min_cluster_size"], min_samples=C.get("min_samples"),
                              metric="euclidean", cluster_selection_method="eom", prediction_data=False),
        vectorizer_model=CountVectorizer(token_pattern=r"\b[a-z][a-z0-9]{2,}\b", min_df=2),
        calculate_probabilities=False, top_n_words=12, verbose=True)
    topics, _ = topic_model.fit_transform(docs, embeddings=emb)
    fn["topic"] = topics

    # Similitud de cada función al centroide de su cluster (espacio original, coseno)
    sim = np.full(len(fn), np.nan, np.float32)
    rows = []
    # Términos por owners: palabra usada por muchos owners del cluster y por pocos clusters (idf).
    # El c-TF-IDF de BERTopic queda dominado por el owner con más funciones en el cluster.
    owner_words = fn.assign(w=[set(d.split()) for d in docs])
    word_clusters = {}
    for t, ws in owner_words[owner_words.topic >= 0].groupby("topic").w:
        for w in set().union(*ws):
            word_clusters[w] = word_clusters.get(w, 0) + 1
    n_topics = max(1, len(set(topics)) - (1 if -1 in topics else 0))

    def owner_terms(sub: pd.DataFrame, k: int = 12) -> list[str]:
        per_owner = sub.groupby("owner").w.agg(lambda ws: set().union(*ws))
        cnt = {}
        for ws in per_owner:
            for w in ws:
                cnt[w] = cnt.get(w, 0) + 1
        score = {w: c / len(per_owner) * np.log(n_topics / word_clusters[w]) for w, c in cnt.items() if c >= 2}
        return [w for w, _ in sorted(score.items(), key=lambda kv: -kv[1])[:k]]

    for t, idx in fn.groupby("topic").indices.items():  # índices posicionales sobre fn completo
        if t < 0:
            continue
        cen = emb[idx].mean(axis=0)
        cen /= np.linalg.norm(cen) + 1e-9
        sim[idx] = emb[idx] @ cen
        sub = fn.iloc[idx]
        copy_owners = set().union(*map(set, sub.copy_owner_list))
        ctfidf = [w for w, _ in (topic_model.get_topic(t) or [])]
        top_owner_share = sub.owner.value_counts(normalize=True).iloc[0]
        rows.append({"topic": t, "n_functions": len(idx),
                     "top_owner_share": float(top_owner_share), "terms": owner_terms(owner_words.iloc[idx]),
                     "terms_ctfidf": ctfidf,
                     "repos": sub.repo.nunique(), "owners_incl_copias": len(copy_owners),
                     "n_copias_total": int(sub.n_copies.sum()),
                     "domains": sub.drop_duplicates("owner").domain.value_counts().to_dict(),
                     "cohesion": float(sim[idx].mean())})
    fn["sim_centroid"] = sim
    fn[["fid", "topic", "sim_centroid"]].to_parquet(ASSIGN)
    owner_dom = fn.drop_duplicates("owner").set_index("owner").domain
    dstats = score_clusters(fn[fn.topic >= 0][["topic", "owner"]], owner_dom, cfg["report"], cfg["selection"]["domains"])
    cl = pd.DataFrame(rows).merge(dstats, on="topic").sort_values(["owners", "n_functions"], ascending=False)
    cl["domains"] = cl.domains.map(lambda d: {k: int(v) for k, v in d.items()})
    cl.to_parquet(CLUSTERS)

    F["clusters"] = len(cl)
    F["funciones_en_clusters"] = int((fn.topic >= 0).sum())
    F["funciones_ruido"] = int((fn.topic < 0).sum())
    for m in (3, 5, 8, 15):
        F[f"clusters_con_>={m}_owners"] = int((cl.owners >= m).sum())
    spec = cl[(cl.owners >= cfg["report"]["specific_min_owners"]) & (cl.domain_q < cfg["report"]["max_q"])]
    for d, n in spec.domain_main.value_counts().items():
        F[f"clusters_enriquecidos_q<{cfg['report']['max_q']}:{d}"] = int(n)
    F["  de_esos_genericos_por_control"] = int(spec.generic.sum())
