"""Etapa 8b: nombre y descripción en inglés simple de los clusters etiquetados, para el explorador público.

Mismos clusters y mismas funciones de ejemplo que la etapa 8 (s8_label.build_jobs, seed fija). Haiku devuelve
un nombre corto ("Parse JSON from model replies") y una oración sin jerga. No cambia ninguna etiqueta.
Tope de gasto propio (`describe.budget_usd`) y corte por saldo; respuestas cacheadas en llm_labels.sqlite.
Salida: data/<modo>/descripciones_en.csv
Uso: uv run scripts/s8b_describe_en.py [--mode full]
"""
import hashlib
import json
import re

import pandas as pd

import s8_label as S

D = S.cfg["describe"]
S.L["budget_usd"] = D["budget_usd"]  # el OpenRouter de s8 corta con este tope
PROMPT = """Below are {k} Python functions from different, unrelated projects (all of them are {domain} apps). \
A clustering step grouped them because they seem to do the same job.

Describe that shared job for a general technical audience that may not write Python (for example, someone reading LinkedIn).
Rules: plain English, no jargon, no library or function names, no words like "cluster", "function", "owner" or "repo".

Answer ONLY with a JSON object, no text around it:
{{"name": "<2 to 6 words naming what the code does, sentence case, e.g. 'Parse JSON from model replies'>",
  "description": "<one simple sentence, at most 25 words, saying what this code does and why an app needs it>"}}

{functions}"""
DOMAIN_EN = {"llm": "LLM (AI chatbot or agent)", "django": "Django web"}


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    if not d or not str(d.get("name", "")).strip() or not str(d.get("description", "")).strip():
        return None
    return {"name": str(d["name"]).strip().rstrip("."), "description": str(d["description"]).strip()}


if __name__ == "__main__":
    jobs = S.build_jobs()
    orr, rows, stopped = S.OpenRouter(), [], None
    bal0 = orr.balance()
    model = S.L["model_second"]
    try:
        for sec, d, rank, c, ex in jobs:
            blocks = [f"### Function {i}\n```python\n{S.cut(r.code)}\n```" for i, r in enumerate(ex.itertuples(), 1)]
            prompt = PROMPT.format(k=len(ex), domain=DOMAIN_EN[d], functions="\n\n".join(blocks))
            k = hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()
            hit = S.db.execute("SELECT response FROM calls WHERE k=?", (k,)).fetchone()
            out = parse(hit[0]) if hit else None
            if out is None:
                text, cost, resp_model, gen_id = orr.chat(model, prompt)
                S.db.execute("INSERT OR REPLACE INTO calls (k, model, response, cost, resp_model, gen_id) "
                             "VALUES (?,?,?,?,?,?)", (k, model, text, cost, resp_model, gen_id))
                S.db.commit()
                out = parse(text) or {"name": "", "description": ""}
            rows.append({"topic": c.topic, "dominio": d, "name_en": out["name"], "description_en": out["description"]})
            print(f"  c{c.topic}: {out['name']} — {out['description'][:90]} · gasto {orr.spent:.4f} USD")
    except S.Budget as e:
        stopped = str(e)
        print(f"FRENADO: {stopped}")
    pd.DataFrame(rows).to_csv(S.OUT / "descripciones_en.csv", index=False)
    print(f"escrito {S.OUT / 'descripciones_en.csv'} · {sum(bool(r['name_en']) for r in rows)}/{len(jobs)} con texto · "
          f"gasto informado {orr.spent:.4f} USD · saldo {bal0:.4f} -> {orr.balance():.4f}"
          + (f" · FRENADO: {stopped}" if stopped else ""))
