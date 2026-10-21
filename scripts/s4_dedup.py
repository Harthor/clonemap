"""Etapa 4: near-duplicates con MinHash + LSH; se colapsan a un representante con conteo de copias.

MinHash (datasketch) sobre shingles de k tokens del código sin comentarios. El LSH se hace por bandas
con numpy (bucket = misma banda) y cada candidato se verifica contra el primero del bucket con la
Jaccard estimada >= threshold. Lo que se busca después es MISMA INTENCIÓN con CÓDIGO DISTINTO, así que
las copias cuentan como una sola variante.
Salidas: data/<modo>/s4_functions.parquet (representantes), data/<modo>/s4_groups.parquet (fid -> grupo)
Uso: uv run scripts/s4_dedup.py [--mode pilot|full] [--force]
"""
import re
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from datasketch import MinHash
from datasketch.lsh import _optimal_param

from common import load_config, out_dir, stage

cfg = load_config()
D = cfg["dedup"]
OUT = out_dir(cfg)
DST, GROUPS = OUT / "s4_functions.parquet", OUT / "s4_groups.parquet"
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")
COMMENT = re.compile(r"#[^\n]*")


def shingles(code: str) -> set[bytes]:
    toks = TOKEN.findall(COMMENT.sub("", code))
    k = D["shingle_tokens"]
    if len(toks) <= k:
        return {" ".join(toks).encode()}
    return {" ".join(toks[i:i + k]).encode() for i in range(len(toks) - k + 1)}


def minhash_chunk(codes: list[str]) -> np.ndarray:
    sets = [shingles(c) for c in codes]
    mhs = MinHash.bulk(sets, num_perm=D["num_perm"], seed=cfg["seed"])
    return np.stack([m.hashvalues for m in mhs]).astype(np.uint64)


class DSU:
    def __init__(self, n):
        self.p = np.arange(n)

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


if __name__ == "__main__":
    if DST.exists() and not cfg["force"]:
        print(f"ya existe {DST}; usar --force para rehacer")
        raise SystemExit
    with stage(cfg, "s4_dedup", [DST, GROUPS]) as st:
        fn = pd.read_parquet(OUT / "s3_functions.parquet")
        codes = fn.code.tolist()
        chunks = [codes[i:i + 2000] for i in range(0, len(codes), 2000)]
        with ProcessPoolExecutor(cfg["parse"]["workers"]) as ex:
            H = np.concatenate(list(ex.map(minhash_chunk, chunks)))

        b, r = _optimal_param(D["threshold"], D["num_perm"], 0.5, 0.5)
        dsu = DSU(len(fn))
        for band in range(b):
            keys = np.ascontiguousarray(H[:, band * r:(band + 1) * r])
            _, inv = np.unique(keys, axis=0, return_inverse=True)
            order = np.argsort(inv, kind="stable")
            inv_sorted = inv[order]
            starts = np.flatnonzero(np.r_[True, inv_sorted[1:] != inv_sorted[:-1]])
            ends = np.r_[starts[1:], len(order)]
            for s, e in zip(starts, ends):
                if e - s < 2:
                    continue
                members = order[s:e]
                head = members[0]
                jac = (H[members[1:]] == H[head]).mean(axis=1)
                for m in members[1:][jac >= D["threshold"]]:
                    dsu.union(head, m)

        fn["group"] = [dsu.find(i) for i in range(len(fn))]
        g = fn.groupby("group").agg(n_copies=("fid", "size"), copy_owners=("owner", "nunique"),
                                    copy_owner_list=("owner", lambda s: sorted(set(s))))
        rep_idx = fn.sort_values("fid").groupby("group").head(1).index  # representante determinístico
        reps = fn.loc[rep_idx].join(g, on="group").drop(columns=["group"])
        reps["group"] = fn.loc[rep_idx, "group"].values
        reps.to_parquet(DST)
        fn[["fid", "group", "owner", "repo", "url"]].to_parquet(GROUPS)

        F = st["funnel"]
        F["lsh_bandas_x_filas"] = f"{b}x{r}"
        F["funciones_entrada"] = len(fn)
        F["grupos_con_copias"] = int((g.n_copies > 1).sum())
        F["funciones_colapsadas"] = int(len(fn) - len(reps))
        F["grupos_copiados_por_>=3_owners"] = int((g.copy_owners >= 3).sum())
        F["representantes"] = len(reps)
