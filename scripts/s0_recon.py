"""Etapa 0: reconocimiento del corpus de gapfinder (solo lectura) y de la máquina.

Escribe data/s0_recon.json. Idempotente: no toca nada fuera de clonemap/data.
Uso: uv run scripts/s0_recon.py
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path("~/dev/projects/gapfinder/data/corpus.db").expanduser()
PUSHED_AFTER = "2024-10-21"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda sql: conn.execute(sql).fetchall()

out = {}
out["sources"] = q("SELECT source, count(*) FROM items GROUP BY source")
out["github_coverage"] = dict(zip(
    ["n", "readme", "pushed_at", "stars", "archived", "extra"],
    q("""SELECT count(*), sum(readme IS NOT NULL AND readme != ''), sum(last_activity_at IS NOT NULL),
                sum(stars IS NOT NULL), sum(archived IS NOT NULL), sum(extra IS NOT NULL)
         FROM items WHERE source='github'""")[0],
))
out["readme_max_len"] = q("SELECT max(length(readme)) FROM items WHERE source='github'")[0][0]

rows = q(f"""SELECT id, lower(title||' '||description||' '||coalesce(readme,'')), created_at
             FROM items WHERE source='github' AND json_extract(extra,'$.language')='Python'
             AND archived=0 AND last_activity_at >= '{PUSHED_AFTER}'""")
out["python_active"] = len(rows)
out["python_active_owners"] = len({r[0].split(":")[1].split("/")[0].lower() for r in rows})
rx = {
    "django": re.compile(r"\bdjango\b"),
    "llm": re.compile(r"\b(openai|anthropic|langchain|litellm|llama.?index|gpt-?4|chatgpt|claude|llm|ollama|rag)\b"),
    "etl": re.compile(r"\b(etl|airflow|dagster|prefect|data pipeline|dbt|luigi)\b"),
}
out["domain_keyword_hits"] = {
    d: sum(1 for _, t, ca in rows if r.search(t) and (d != "llm" or ca >= "2024-01-01")) for d, r in rx.items()
}

sysctl = lambda k: subprocess.run(["sysctl", "-n", k], capture_output=True, text=True).stdout.strip()
out["machine"] = {
    "cpu": sysctl("machdep.cpu.brand_string"),
    "cores_perf_eff": [sysctl("hw.perflevel0.physicalcpu"), sysctl("hw.perflevel1.physicalcpu")],
    "ram_gb": int(sysctl("hw.memsize")) / 2**30,
    "disk_free_gb": round(shutil.disk_usage(os.path.expanduser("~")).free / 2**30, 1),
}

(ROOT / "data").mkdir(exist_ok=True)
(ROOT / "data" / "s0_recon.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
print(json.dumps(out, indent=2, ensure_ascii=False))
