"""Etapa 5: embeddings de código locales con Salesforce/codet5p-110m-embedding (256-d, normalizados).

Elección: modelo contrastivo para recuperación de código (agrupa por intención más que por forma),
110M parámetros (entra en 8 GB con MPS) y salida de 256-d (3x menos RAM que 768-d para UMAP/kNN).
Se procesa por partes de `chunk` funciones ordenadas por largo (menos padding); cada parte se cachea
en data/<modo>/s5_parts/ y se retoma si se corta.
Salidas: data/<modo>/s5_embeddings.npy (float16, mismo orden que s5_ids.parquet), s5_ids.parquet
Uso: uv run scripts/s5_embed.py [--mode pilot|full] [--force]
"""
import hashlib
import shutil
import time

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoTokenizer

from common import load_config, out_dir, stage

cfg = load_config()
E = cfg["embed"]
OUT = out_dir(cfg)
DST, IDS, PARTS = OUT / "s5_embeddings.npy", OUT / "s5_ids.parquet", OUT / "s5_parts"
if DST.exists() and not cfg["force"]:
    print(f"ya existe {DST}; usar --force para rehacer")
    raise SystemExit
PARTS.mkdir(exist_ok=True)
torch.manual_seed(cfg["seed"])

with stage(cfg, "s5_embed", [DST, IDS]) as st:
    fn = pd.read_parquet(OUT / "s4_functions.parquet", columns=["fid", "code"])
    fn = fn.assign(_len=fn.code.str.len()).sort_values(["_len", "fid"]).reset_index(drop=True)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(E["model"], trust_remote_code=True)
    model = AutoModel.from_pretrained(E["model"], trust_remote_code=True).to(device).eval()
    if device == "mps" and E.get("fp16", True):
        model = model.half()
    st["funnel"]["device"] = device

    # Las partes dependen del orden exacto de fids: si cambió la entrada (o --force), se descartan
    fp = hashlib.sha1("".join(fn.fid).encode()).hexdigest()
    fp_file = PARTS / "fingerprint"
    if cfg["force"] or not fp_file.exists() or fp_file.read_text() != fp:
        shutil.rmtree(PARTS, ignore_errors=True)
        PARTS.mkdir()
        fp_file.write_text(fp)
    n, chunk = len(fn), E["chunk"]
    t0, done = time.time(), 0
    for p0 in range(0, n, chunk):
        part = PARTS / f"{p0:08d}.npy"
        if part.exists():
            continue
        codes = fn.code.iloc[p0:p0 + chunk].tolist()
        out = []
        with torch.no_grad():
            for i in range(0, len(codes), E["batch_size"]):
                x = tok(codes[i:i + E["batch_size"]], padding=True, truncation=True,
                        max_length=E["max_tokens"], return_tensors="pt").to(device)
                e = model(**x)
                e = e if torch.is_tensor(e) else e[0]
                out.append(torch.nn.functional.normalize(e.float(), dim=-1).cpu().numpy().astype(np.float16))
        np.save(part, np.concatenate(out))
        done += len(codes)
        print(f"  {p0 + len(codes)}/{n}  ({done / (time.time() - t0):.0f} fn/s)")

    emb = np.concatenate([np.load(PARTS / f"{p0:08d}.npy") for p0 in range(0, n, chunk)])
    np.save(DST, emb)
    fn[["fid"]].to_parquet(IDS)
    st["funnel"]["funciones_embebidas"] = len(emb)
    st["funnel"]["dim"] = int(emb.shape[1])
    st["funnel"]["truncadas_a_max_tokens_(aprox)"] = int((fn._len > E["max_tokens"] * 3.5).sum())
