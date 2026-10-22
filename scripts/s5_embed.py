"""Etapa 5: embeddings de código locales con Salesforce/codet5p-110m-embedding (256-d, normalizados).

Elección: modelo contrastivo para recuperación de código (agrupa por intención más que por forma),
110M parámetros (entra en 8 GB con MPS) y salida de 256-d (3x menos RAM que 768-d para UMAP/kNN).
Caché por contenido: data/cache/emb/<modelo>-<max_tokens>/part-NNNNN.parquet con (key=sha1 del código, vec).
Solo se embebe lo que no está en la caché, en partes de `chunk` ordenadas por largo (menos padding);
si se corta, se retoma desde la última parte escrita. La caché se comparte entre pilot y full.
Salidas: data/<modo>/s5_embeddings.npy (float16, mismo orden que s5_ids.parquet), s5_ids.parquet
Uso: uv run scripts/s5_embed.py [--mode pilot|full] [--force]
"""
import hashlib
import time

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoTokenizer

from common import cache_dir, load_config, out_dir, stage

cfg = load_config()
E = cfg["embed"]
OUT = out_dir(cfg)
DST, IDS = OUT / "s5_embeddings.npy", OUT / "s5_ids.parquet"
CACHE = cache_dir(cfg) / "emb" / f"{E['model'].split('/')[-1]}-{E['max_tokens']}"
if DST.exists() and not cfg["force"]:
    print(f"ya existe {DST}; usar --force para rehacer")
    raise SystemExit
CACHE.mkdir(parents=True, exist_ok=True)
torch.manual_seed(cfg["seed"])


def code_key(code: str) -> str:
    return hashlib.sha1(code.encode()).hexdigest()


def load_cache() -> dict[str, np.ndarray]:
    out = {}
    for p in sorted(CACHE.glob("part-*.parquet")):
        df = pd.read_parquet(p)
        for k, v in zip(df.key, df.vec):
            out[k] = np.frombuffer(v, dtype=np.float16)
    return out


if __name__ == "__main__":
    with stage(cfg, "s5_embed", [DST, IDS]) as st:
        fn = pd.read_parquet(OUT / "s4_functions.parquet", columns=["fid", "code"]).sort_values("fid")
        fn["key"] = fn.code.map(code_key)
        cached = load_cache()
        todo = fn[~fn.key.isin(cached)].drop_duplicates("key")
        todo = todo.assign(_len=todo.code.str.len()).sort_values(["_len", "key"])
        st["funnel"]["funciones"] = len(fn)
        st["funnel"]["ya_en_cache"] = int(fn.key.isin(cached).sum())
        st["funnel"]["a_embeber"] = len(todo)

        if len(todo):
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            tok = AutoTokenizer.from_pretrained(E["model"], trust_remote_code=True)
            model = AutoModel.from_pretrained(E["model"], trust_remote_code=True).to(device).eval()
            if device == "mps" and E.get("fp16", True):
                model = model.half()
            st["funnel"]["device"] = device
            n_parts = len(list(CACHE.glob("part-*.parquet")))
            t0 = time.time()
            for p0 in range(0, len(todo), E["chunk"]):
                part = todo.iloc[p0:p0 + E["chunk"]]
                codes, out = part.code.tolist(), []
                with torch.no_grad():
                    for i in range(0, len(codes), E["batch_size"]):
                        x = tok(codes[i:i + E["batch_size"]], padding=True, truncation=True,
                                max_length=E["max_tokens"], return_tensors="pt").to(device)
                        e = model(**x)
                        e = e if torch.is_tensor(e) else e[0]
                        out.append(torch.nn.functional.normalize(e.float(), dim=-1).cpu().numpy().astype(np.float16))
                vecs = np.concatenate(out)
                pd.DataFrame({"key": part.key.values, "vec": [v.tobytes() for v in vecs]}).to_parquet(
                    CACHE / f"part-{n_parts:05d}.parquet")
                n_parts += 1
                cached.update(zip(part.key, vecs))
                done = p0 + len(part)
                print(f"  {done}/{len(todo)}  ({done / (time.time() - t0):.0f} fn/s)")

        emb = np.stack([cached[k] for k in fn.key])
        np.save(DST, emb)
        fn[["fid"]].to_parquet(IDS)
        st["funnel"]["dim"] = int(emb.shape[1])
        st["funnel"]["truncadas_a_max_tokens_(aprox)"] = int((fn.code.str.len() > E["max_tokens"] * 3.5).sum())
