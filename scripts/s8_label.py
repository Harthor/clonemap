"""Etapa 8: etiquetado de clusters con Jev 1.13 (categoría y verificación de librerías) + Haiku (texto).

Clusters: top `top_n` por owners de "Específicos de <dominio>" y top `top_nonexclusive` de "Enriquecidos no
exclusivos" (vista por dominio, s7_report.domain_sections). Por cluster, K funciones de owners distintos del
dominio (seed fija; código cortado a `max_code_lines`).

- Jev (typesafe/jev-1.13, System One) vía OpenRouter POST /api/v1/systemone con el SDK oficial typesafe-sdk,
  igual que gapfinder (src/gapfinder/verify.py: OpenRouterJevVerifier): state chico y estructurado, una
  proposición (Noul) por pregunta con criterios de verdadero/falso, modelo fijo (sin router).
  4 proposiciones, una por categoría; se guardan las 4 probabilidades. Categoría de Jev = la más probable;
  "ambigua" si la diferencia con la segunda es < `jev_ambiguous_margin`.
- Haiku (chat completions): mismo prompt de antes; da la categoría, la descripción en una línea y hasta 3
  librerías de PyPI si es utilidad_reimplementada.
- Confirmado = Jev no ambiguo y Haiku coinciden en la categoría; si no, dudoso.
- Librerías: cada una que propuso Haiku se verifica en PyPI (existe + última versión) y con Jev:
  "la librería provee funcionalidad que resuelve directamente <descripción de Haiku>"; se aceptan las de
  probabilidad >= `jev_lib_min_prob` que además existen en PyPI.

Gasto: costo real por llamada (usage.cost); corta si el acumulado llega a `budget_usd` o el saldo de la cuenta
baja de `min_balance_usd`. Toda respuesta se cachea en data/cache/llm_labels.sqlite con el modelo en la clave,
y se guarda el modelo que respondió: si no es el pedido, la llamada falla.
Key: OPENROUTER_API_KEY en el entorno o en clonemap/.env (gitignored); no se imprime ni se copia.
Salida: data/<modo>/etiquetado.csv (el resumen lo arma s9_resumen.py)
Uso: uv run scripts/s8_label.py [--mode full] [--dry-run]
"""
import argparse
import asyncio
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
p.add_argument("--dry-run", action="store_true", help="arma los pedidos sin llamar a ningún modelo")
args, _ = p.parse_known_args()

CATS = ["uso_sdk", "idiomatico_framework", "utilidad_reimplementada", "otro"]
SEC_SPECIFIC = "Específicos de {d}"
SEC_NONEXCL = "Enriquecidos no exclusivos (más de 3 repos de control, cociente ≥×5)"

# --- Haiku: prompt de chat (sin cambios respecto de la pasada anterior, así su caché sigue valiendo) --------
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

# --- Jev: una proposición por categoría, mismas definiciones que el prompt de Haiku ------------------------
JEV_CATEGORY_QUESTIONS = {
    "uso_sdk": {
        "instructions": "Is the code in `functions` mostly calling the API of an SDK or external service (for example an OpenAI client or boto3), with little logic of its own?",
        "true": "Most of each function is building arguments for and calling a third-party SDK or service API.",
        "false": "The functions contain substantial logic of their own beyond calling an SDK or service.",
    },
    "idiomatico_framework": {
        "instructions": "Are the `functions` the idiomatic way of using a framework (for example Django or DRF views, forms, serializers, admin, management commands)?",
        "true": "The functions follow the standard patterns the framework prescribes for this job.",
        "false": "The functions are not framework boilerplate; they could live outside the framework.",
    },
    "utilidad_reimplementada": {
        "instructions": "Does each of the `functions` reimplement by hand a generic utility with its own logic, something a reusable library could provide?",
        "true": "Each repository wrote its own version of the same generic utility logic.",
        "false": "The functions are mostly SDK calls, framework boilerplate, app-specific logic, or unrelated to each other.",
    },
    "otro": {
        "instructions": "Are the `functions` none of these: SDK calls, idiomatic framework code, or a hand-reimplemented generic utility; or is the group incoherent?",
        "true": "The group fits none of those three descriptions, or the functions do unrelated things.",
        "false": "The group clearly fits one of: SDK calls, idiomatic framework code, or a reimplemented generic utility.",
    },
}


def library_question(name: str) -> dict:
    """Proposición: "La librería <nombre> provee funcionalidad que resuelve directamente: <descripción>"."""
    return {"instructions": f"Does the Python library `{name}` (from PyPI) provide functionality that directly solves `need`?",
            "true": "Using this library, `need` is solved directly by functionality it ships, without writing the core logic by hand.",
            "false": "The library is unrelated, only helps indirectly, or solves a different problem."}


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
for col in ("resp_model TEXT", "gen_id TEXT"):  # modelo que respondió e id (las respuestas viejas no los tienen)
    try:
        db.execute(f"ALTER TABLE calls ADD COLUMN {col}")
    except sqlite3.OperationalError:
        pass
db.execute("CREATE TABLE IF NOT EXISTS jev_calls (k TEXT PRIMARY KEY, model TEXT, resp_model TEXT, gen_id TEXT, "
           "answers TEXT, cost REAL)")
db.execute("CREATE TABLE IF NOT EXISTS pypi (name TEXT PRIMARY KEY, version TEXT)")


class Budget(Exception):
    pass


class OpenRouter:
    def __init__(self):
        self.key = load_key()
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {self.key}"
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

    @staticmethod
    def same_model(asked: str, got: str | None) -> bool:
        return str(got or "").startswith(asked)  # se admite sufijo de versión/fecha, no otro modelo

    def chat(self, model: str, prompt: str) -> tuple[str, float, str, str]:
        self.check()
        r = self.s.post("https://openrouter.ai/api/v1/chat/completions", timeout=180, json={
            "model": model, "temperature": 0, "max_tokens": L["max_tokens"], "usage": {"include": True},
            "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        d = r.json()
        cost = float((d.get("usage") or {}).get("cost") or 0.0)
        self.spent += cost
        if not self.same_model(model, d.get("model")):
            raise RuntimeError(f"pedí {model} y respondió {d.get('model')} (id {d.get('id')})")
        return d["choices"][0]["message"]["content"], cost, d.get("model"), d.get("id")

    def system_one(self, state: dict, questions: dict) -> tuple[dict[str, float], float, str, str]:
        """Igual que gapfinder.OpenRouterJevVerifier: SDK oficial con base_url de OpenRouter y un response_model
        que conserva id, model y usage.cost (el SDK los descarta por defecto)."""
        from pydantic import BaseModel
        from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulAnswer, NoulCriteria

        class Usage(BaseModel):
            input_tokens: int
            output_tokens: int
            cost: float | None = None

        class Resp(BaseModel):
            id: str | None = None
            model: str
            provider: str | None = None
            answers: dict[str, NoulAnswer]
            usage: Usage

        self.check()
        nouls = {k: Noul(instructions=q["instructions"], criteria=NoulCriteria(true=q["true"], false=q["false"]))
                 for k, q in questions.items()}

        async def go():
            async with AsyncTypeSafeClient(model=L["jev_model"], api_key=self.key,
                                           base_url="https://openrouter.ai/api") as client:
                return await client.system_one(state, nouls, response_model=Resp)

        r = asyncio.run(go())
        cost = float(r.usage.cost or 0.0)
        self.spent += cost
        if not self.same_model(L["jev_model"], r.model):
            raise RuntimeError(f"pedí {L['jev_model']} y respondió {r.model} (id {r.id})")
        return {k: float(a.noul) for k, a in r.answers.items()}, cost, r.model, r.id


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


def cut(code: str) -> str:
    lines = code.splitlines()
    return "\n".join(lines[:L["max_code_lines"]]) + ("\n# ... (cortado)" if len(lines) > L["max_code_lines"] else "")


def build_prompt(ex: pd.DataFrame, domain: str) -> str:
    blocks = [f"### Función {i} (repo {i})\n```python\n{cut(r.code)}\n```" for i, r in enumerate(ex.itertuples(), 1)]
    return PROMPT.format(k=len(ex), domain=domain, functions="\n\n".join(blocks))


def jev_state(ex: pd.DataFrame, domain: str) -> dict:
    return {"domain": f"Python apps of the '{domain}' domain; each function comes from a different repository",
            "functions": [cut(r.code) for r in ex.itertuples()]}


def haiku(orr, prompt: str) -> dict:
    model = L["model_second"]
    k = hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()
    hit = db.execute("SELECT response FROM calls WHERE k=?", (k,)).fetchone()
    if hit and parse_label(hit[0])["categoria"] != "sin_respuesta_valida":
        return parse_label(hit[0])
    text, cost, resp_model, gen_id = orr.chat(model, prompt)
    db.execute("INSERT OR REPLACE INTO calls (k, model, response, cost, resp_model, gen_id) VALUES (?,?,?,?,?,?)",
               (k, model, text, cost, resp_model, gen_id))
    db.commit()
    return parse_label(text)


def jev(orr, state: dict, questions: dict) -> dict[str, float]:
    k = hashlib.sha1(json.dumps([L["jev_model"], state, questions], sort_keys=True).encode()).hexdigest()
    hit = db.execute("SELECT answers FROM jev_calls WHERE k=?", (k,)).fetchone()
    if hit:
        return json.loads(hit[0])
    answers, cost, resp_model, gen_id = orr.system_one(state, questions)
    db.execute("INSERT OR REPLACE INTO jev_calls VALUES (?,?,?,?,?,?)",
               (k, L["jev_model"], resp_model, gen_id, json.dumps(answers), cost))
    db.commit()
    return answers


def build_jobs() -> list[tuple]:
    """Clusters a etiquetar con sus ejemplos: (sección, dominio, puesto, cluster, ejemplos). Determinístico (seed),
    así cualquier pasada posterior (p. ej. s8b_describe_en.py) ve exactamente las mismas funciones."""
    secs = domain_sections(cl)
    jobs = []
    for d in cfg["selection"]["domains"]:  # mismo orden y rng que la pasada anterior: la caché de Haiku vale
        rng = random.Random(cfg["seed"])
        for rank, c in enumerate(secs[SEC_SPECIFIC.format(d=d)].head(L["top_n"]).itertuples(), 1):
            jobs.append((f"específico {d}", d, rank, c, examples(c, d, rng)))
    rng = random.Random(cfg["seed"])
    for rank, c in enumerate(secs[SEC_NONEXCL].head(L["top_nonexclusive"]).itertuples(), 1):
        jobs.append(("enriquecido no exclusivo", c.domain_main, rank, c, examples(c, c.domain_main, rng)))
    return jobs


if __name__ == "__main__":
    jobs = build_jobs()
    print(f"{len(jobs)} clusters")
    if args.dry_run:
        print(json.dumps(jev_state(jobs[0][4], jobs[0][1]))[:1200])
        raise SystemExit

    orr, rows, stopped = OpenRouter(), [], None
    bal0 = orr.balance()
    print(f"saldo inicial OpenRouter: {bal0:.4f} USD")
    try:
        for sec, d, rank, c, ex in jobs:
            h = haiku(orr, build_prompt(ex, d))
            probs = jev(orr, jev_state(ex, d), JEV_CATEGORY_QUESTIONS)
            ranked = sorted(probs.items(), key=lambda kv: -kv[1])
            jcat, margin = ranked[0][0], ranked[0][1] - ranked[1][1]
            ambiguous = margin < L["jev_ambiguous_margin"]
            libs, lib_probs = h["librerias"], {}
            if libs:
                lp = jev(orr, {"need": h["descripcion"]},
                         {f"lib{i}": library_question(x) for i, x in enumerate(libs)})
                lib_probs = {x: lp[f"lib{i}"] for i, x in enumerate(libs)}
            ver = {x: pypi_version(x) for x in libs}
            ok = [x for x in libs if ver[x] and lib_probs.get(x, 0) >= L["jev_lib_min_prob"]]
            rows.append({
                "seccion": sec, "dominio": d, "puesto": rank, "topic": c.topic, "owners": c.owners_main,
                "repos_control": c.owners_control, "pct_dominio": round(100 * c.domain_prev, 1),
                "pct_control": round(100 * c.control_prev, 1), "enriquecimiento": round(c.enrichment, 2),
                "terminos": ", ".join(list(c.terms)[:6]),
                **{f"jev_p_{k}": round(probs[k], 3) for k in CATS},
                "categoria_jev": jcat, "jev_margen": round(margin, 3), "jev_ambigua": ambiguous,
                "categoria_haiku": h["categoria"], "descripcion_haiku": h["descripcion"],
                "librerias_haiku": "; ".join(libs),
                "estado": "confirmado" if (not ambiguous and jcat == h["categoria"]) else "dudoso",
                "librerias_jev": "; ".join(f"{x}: {lib_probs[x]:.2f}" for x in libs),
                "librerias_pypi": "; ".join(f"{x}=={ver[x]}" if ver[x] else f"{x} (inexistente)" for x in libs),
                "librerias_aceptadas": "; ".join(f"{x}=={ver[x]}" for x in ok),
                "ejemplo_1": ex.url.iloc[0], "ejemplo_2": ex.url.iloc[1] if len(ex) > 1 else ""})
            print(f"  {sec} #{rank} c{c.topic}: jev {jcat}{' (ambigua)' if ambiguous else ''} / haiku {h['categoria']}"
                  f" · libs {len(ok)}/{len(libs)} · gasto {orr.spent:.4f} USD")
    except Budget as e:
        stopped = str(e)
        print(f"FRENADO: {stopped}")

    pd.DataFrame(rows).to_csv(OUT / "etiquetado.csv", index=False)
    bal1 = orr.balance()
    print(f"escrito {OUT / 'etiquetado.csv'} · gasto informado {orr.spent:.4f} USD · saldo {bal0:.4f} -> {bal1:.4f}"
          + (f" · FRENADO: {stopped}" if stopped else ""))
