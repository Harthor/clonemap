"""Etapa 8: etiquetado con LLM (OpenRouter) del top N por owners de cada dominio (específicos del dominio).

Por cluster se pasan K funciones de owners distintos del dominio (seed fija; código cortado a `max_code_lines`)
y se pide JSON: categoria (uso_sdk / idiomatico_framework / utilidad_reimplementada / otro), descripcion
(una línea) y, si es utilidad_reimplementada, hasta 3 librerías de PyPI que ya lo resuelvan.
Modelo principal + segunda pasada con otro modelo, mismo prompt: "confirmado" si coinciden en categoría,
"dudoso" si no. Cada librería propuesta se verifica contra https://pypi.org/pypi/<nombre>/json.

Gasto: se pide a OpenRouter el costo real de cada llamada (usage.include) y se corta si el acumulado llega
a `budget_usd` o si el saldo de la cuenta baja de `min_balance_usd`. Respuestas cacheadas en
data/cache/llm_labels.sqlite (re-correr no vuelve a pagar).
`max_tokens` incluye los tokens de razonamiento de los modelos que razonan (Haiku 5.5 se comía 400 enteros).
Key: OPENROUTER_API_KEY en el entorno o en clonemap/.env (gitignored); no se imprime ni se copia.
Salida: data/<modo>/etiquetado.csv (el resumen lo arma s9_resumen.py)
Uso: uv run scripts/s8_label.py [--mode full] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys

import pandas as pd
import requests

from common import ROOT, cache_dir
from s7_report import cfg, cl, domain_sections, fn, OUT

L = cfg["label"]
p = argparse.ArgumentParser()
p.add_argument("--dry-run", action="store_true", help="arma prompts y estima tokens sin llamar a ningún LLM")
args, _ = p.parse_known_args()

CATS = ["uso_sdk", "idiomatico_framework", "utilidad_reimplementada", "otro"]
PROMPT = """Abajo hay {k} funciones Python de repos distintos (owners distintos) que un clustering agrupó porque parecen \
tener la misma intención. Los repos son apps del dominio "{domain}".

Clasificá el grupo en UNA categoría:
- uso_sdk: el código es mayormente llamar a la API de un SDK o servicio (ej. cliente de OpenAI, boto3) con poca lógica propia.
- idiomatico_framework: es la forma idiomática de usar un framework (ej. vistas, forms o serializers de Django/DRF).
- utilidad_reimplementada: cada repo reimplementa a mano una utilidad genérica con lógica propia.
- otro: nada de lo anterior, o el grupo no es coherente.

Respondé SOLO un objeto JSON, sin texto alrededor:
{{"categoria": "<una de: uso_sdk, idiomatico_framework, utilidad_reimplementada, otro>",
  "descripcion": "<qué hacen estas funciones, en una línea, en español>",
  "librerias_pypi": ["<si categoria es utilidad_reimplementada: hasta 3 nombres de paquetes de PyPI que ya lo resuelvan; si no, lista vacía>"]}}

{functions}"""


def load_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("falta OPENROUTER_API_KEY (entorno o clonemap/.env)")


db = sqlite3.connect(cache_dir(cfg) / "llm_labels.sqlite")
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE IF NOT EXISTS calls (k TEXT PRIMARY KEY, model TEXT, response TEXT, cost REAL)")
# modelo que respondió de verdad e id de la generación (las respuestas de antes de este cambio no los tienen)
for col in ("resp_model TEXT", "gen_id TEXT"):
    try:
        db.execute(f"ALTER TABLE calls ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
db.execute("CREATE TABLE IF NOT EXISTS pypi (name TEXT PRIMARY KEY, version TEXT)")


class Budget(Exception):
    pass


class OpenRouter:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {load_key()}"
        self.spent = 0.0

    def balance(self) -> float:
        d = self.s.get("https://openrouter.ai/api/v1/credits", timeout=30).json()["data"]
        return d["total_credits"] - d["total_usage"]

    def check(self):
        bal = self.balance()
        if bal < L["min_balance_usd"]:
            raise Budget(f"saldo de OpenRouter {bal:.2f} USD < {L['min_balance_usd']} USD")
        if self.spent >= L["budget_usd"]:
            raise Budget(f"gasto acumulado {self.spent:.4f} USD >= tope {L['budget_usd']} USD")

    def chat(self, model: str, prompt: str) -> tuple[str, float, str, str]:
        self.check()
        r = self.s.post("https://openrouter.ai/api/v1/chat/completions", timeout=180, json={
            "model": model, "temperature": 0, "max_tokens": L["max_tokens"], "usage": {"include": True},
            "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        d = r.json()
        cost = float((d.get("usage") or {}).get("cost") or 0.0)
        self.spent += cost
        # sin routers: el que responde tiene que ser el modelo pedido (se admite sufijo de versión/fecha)
        if not str(d.get("model") or "").startswith(model):
            raise RuntimeError(f"pedí {model} y respondió {d.get('model')} (id {d.get('id')})")
        return d["choices"][0]["message"]["content"], cost, d.get("model"), d.get("id")


def parse_label(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    cat = d.get("categoria") if d.get("categoria") in CATS else "sin_respuesta_valida"
    libs = [str(x).strip() for x in (d.get("librerias_pypi") or []) if str(x).strip()][:3]
    return {"categoria": cat, "descripcion": str(d.get("descripcion") or "").strip(), "librerias": libs}


def pypi_version(name: str) -> str | None:
    key = re.sub(r"[-_.]+", "-", name.lower())
    row = db.execute("SELECT version FROM pypi WHERE name=?", (key,)).fetchone()
    if row:
        return row[0] or None
    r = requests.get(f"https://pypi.org/pypi/{key}/json", timeout=30)
    ver = r.json()["info"]["version"] if r.status_code == 200 else ""
    db.execute("INSERT OR REPLACE INTO pypi VALUES (?,?)", (key, ver))
    db.commit()
    return ver or None


def examples(c, domain: str, rng: random.Random) -> pd.DataFrame:
    sub = fn[(fn.topic == c.topic) & (fn.domain == domain)].sort_values("fid")
    owners = sorted(sub.owner.unique())
    rng.shuffle(owners)
    return pd.DataFrame([sub[sub.owner == o].sample(1, random_state=rng.randrange(2**31)).iloc[0]
                         for o in owners[:L["examples"]]])


def build_prompt(ex: pd.DataFrame, domain: str) -> str:
    blocks = []
    for i, r in enumerate(ex.itertuples(), 1):
        lines = r.code.splitlines()
        code = "\n".join(lines[:L["max_code_lines"]]) + ("\n# ... (cortado)" if len(lines) > L["max_code_lines"] else "")
        blocks.append(f"### Función {i} (repo {i})\n```python\n{code}\n```")
    return PROMPT.format(k=len(ex), domain=domain, functions="\n\n".join(blocks))


if __name__ == "__main__":
    secs = domain_sections(cl)
    jobs = []
    for d in cfg["selection"]["domains"]:
        rng = random.Random(cfg["seed"])
        for rank, c in enumerate(secs[f"Específicos de {d}"].head(L["top_n"]).itertuples(), 1):
            ex = examples(c, d, rng)
            jobs.append((d, rank, c, ex, build_prompt(ex, d)))
    n_chars = sum(len(j[4]) for j in jobs)
    print(f"{len(jobs)} clusters, ~{n_chars / 3.5 / 1000:.0f}k tokens de entrada por modelo (aprox.)")
    if args.dry_run:
        print(jobs[0][4][:1500])
        raise SystemExit

    orr, rows, stopped = OpenRouter(), [], None
    print(f"saldo inicial OpenRouter: {orr.balance():.2f} USD")
    try:
        for d, rank, c, ex, prompt in jobs:
            labels = {}
            for role, model in (("principal", L["model_main"]), ("segundo", L["model_second"])):
                k = hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()
                hit = db.execute("SELECT response FROM calls WHERE k=?", (k,)).fetchone()
                # una respuesta cacheada inválida (p. ej. cortada) se vuelve a pedir
                if hit and parse_label(hit[0])["categoria"] != "sin_respuesta_valida":
                    text = hit[0]
                else:
                    text, cost, resp_model, gen_id = orr.chat(model, prompt)
                    db.execute("INSERT OR REPLACE INTO calls (k, model, response, cost, resp_model, gen_id) "
                               "VALUES (?,?,?,?,?,?)", (k, model, text, cost, resp_model, gen_id))
                    db.commit()
                labels[role] = parse_label(text)
            a, b = labels["principal"], labels["segundo"]
            libs = list(dict.fromkeys(a["librerias"] + b["librerias"]))
            ver = {x: pypi_version(x) for x in libs}
            rows.append({"dominio": d, "puesto": rank, "topic": c.topic, "owners": c.owners_main,
                         "repos_control": c.owners_control, "terminos": ", ".join(list(c.terms)[:6]),
                         "categoria_principal": a["categoria"], "descripcion_principal": a["descripcion"],
                         "librerias_principal": "; ".join(a["librerias"]),
                         "categoria_segundo": b["categoria"], "descripcion_segundo": b["descripcion"],
                         "librerias_segundo": "; ".join(b["librerias"]),
                         "estado": "confirmado" if a["categoria"] == b["categoria"] else "dudoso",
                         "librerias_verificadas": "; ".join(f"{x}=={v}" if v else f"{x} (inexistente)" for x, v in ver.items()),
                         "ejemplo_1": ex.url.iloc[0], "ejemplo_2": ex.url.iloc[1] if len(ex) > 1 else ""})
            print(f"  {d} #{rank} c{c.topic}: {a['categoria']} / {b['categoria']} · gasto {orr.spent:.4f} USD")
    except Budget as e:
        stopped = str(e)
        print(f"FRENADO: {stopped}")

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "etiquetado.csv", index=False)
    if stopped:
        print(f"etiquetado incompleto: {stopped}")
    print(f"escrito {OUT / 'etiquetado.csv'} · gasto {orr.spent:.4f} USD (el resumen lo arma s9_resumen.py)")
