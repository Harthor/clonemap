"""Etapa 1: selección de repos (apps, no librerías) en los dominios de config (django, llm).

Fuentes de candidatos:
  - corpus de gapfinder (solo lectura): repos Python activos con keyword de dominio.
  - GitHub Search API (stars>=N) para ampliar cada dominio más allá del corpus (casi todo >=100 estrellas).
Se excluyen repos de papers (arXiv/BibTeX en el README).
Después, en orden aleatorio con seed y por tandas, GraphQL trae metadata + archivos de dependencias,
se chequea PyPI y se aplican los filtros hasta cubrir la cuota de cada dominio.

Salidas: data/<modo>/s1_candidates.parquet (todo lo evaluado, con motivo de descarte)
         data/<modo>/s1_selected.parquet
Uso: uv run scripts/s1_select.py [--mode pilot|full] [--force]
"""
import json
import random
import re
import sqlite3
import tomllib
from datetime import date, timedelta

import pandas as pd
import requests

from common import ROOT, GitHub, cache_dir, gapfinder_conn, load_config, out_dir, stage

cfg = load_config()
S = cfg["selection"]
OUT = out_dir(cfg)
CAND, SEL = OUT / "s1_candidates.parquet", OUT / "s1_selected.parquet"
if SEL.exists() and not cfg["force"]:
    print(f"ya existe {SEL}; usar --force para rehacer")
    raise SystemExit

QUOTAS = dict(cfg["pilot"]["quotas"]) if cfg["mode"] == "pilot" else {d: S["target_per_domain"] for d in S["domains"]}
QUOTAS["control"] = S["control_n"]
GROUPS = S["domains"] + ["control"]  # control: Python cualquiera, sin dependencias de los dominios

# --- keywords -------------------------------------------------------------------------------
KW = {
    "django": re.compile(r"\bdjango\b"),
    "llm": re.compile(r"\b(openai|anthropic|langchain|langgraph|litellm|llama.?index|gpt-?4o?|chatgpt|claude|llms?|ollama|rag)\b"),
}
# Material didáctico. En nombre/descripción se es amplio; en el README solo frases fuertes.
EDU_NAME = re.compile(
    r"(tutorial|course|curso|awesome|leetcode|exercise|homework|assignment|boilerplate|starter|template|"
    r"cookiecutter|bootcamp|workshop|lesson|learn-|-learn\b|learning-|examples?\b|sample|demo\b|100.?days|"
    r"interview|kata|practice|hello.?world|cheat.?sheet|udemy|coursera|cs50|scaffold|skeleton|playground|"
    r"\bbook\b|chapter|week.?\d|day.?\d|lab.?\d|study)", re.I)
EDU_README = re.compile(
    r"(this (tutorial|course|workshop|repository contains (the )?(code|exercises|examples))|in this course|"
    r"for learning purposes|educational purposes|boilerplate|starter (kit|template|project)|"
    r"homework|assignment|bootcamp|udemy|coursera|follow along|step.by.step guide)", re.I)

# Dependencias que definen dominio (nombres de paquete normalizados con '-').
DEPS = {
    "django": {"django"},
    "llm": {"openai", "anthropic", "langchain", "langchain-core", "langchain-community", "langchain-openai",
            "langgraph", "litellm", "llama-index", "llama-index-core", "ollama", "google-generativeai",
            "google-genai", "mistralai", "cohere", "groq", "instructor", "dspy", "dspy-ai", "crewai",
            "pyautogen", "autogen-agentchat", "pydantic-ai", "openai-agents", "smolagents", "haystack-ai"},
}
DOMAIN_PRIORITY = ["django", "llm"]  # si hay varios, gana el más escaso
# Código de papers / benchmarks: no son apps
PAPER_README = re.compile(
    r"(arxiv\.org|arxiv:\s*\d{4}\.\d+|@(inproceedings|article|misc|software)\s*\{|bibtex|"
    r"official (pytorch |jax |tensorflow )?(code|implementation)|our paper|"
    r"accepted (at|to|by) (neurips|iclr|icml|acl|emnlp|naacl|cvpr|iccv|eccv|aaai|kdd|sigir|colm))", re.I)

PY_BYTES_PER_LINE = 35  # estimación gruesa: bytes de Python reportados por GitHub / líneas


def norm_pkg(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def dep_names(texts: dict) -> set[str]:
    """Extrae nombres de paquetes de requirements*.txt / pyproject / setup.py / setup.cfg / Pipfile."""
    names = set()
    for line in (texts.get("req") or "").splitlines() + (texts.get("pipfile") or "").splitlines():
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line.split("#")[0])
        if m:
            names.add(norm_pkg(m.group(1)))
    blob = " ".join(texts.get(k) or "" for k in ("pyproject", "setuppy", "setupcfg"))
    for m in re.finditer(r"""["'\s]([A-Za-z][A-Za-z0-9._-]*)\s*(?:[<>=!~\[;"',]|$)""", blob, re.M):
        names.add(norm_pkg(m.group(1)))
    return names


def declared_package(texts: dict) -> str | None:
    if texts.get("pyproject"):
        try:
            t = tomllib.loads(texts["pyproject"])
            name = t.get("project", {}).get("name") or t.get("tool", {}).get("poetry", {}).get("name")
            if name:
                return name
        except tomllib.TOMLDecodeError:
            pass
    for key, rx in (("setupcfg", r"^\s*name\s*=\s*([A-Za-z0-9._-]+)"), ("setuppy", r"""name\s*=\s*["']([A-Za-z0-9._-]+)["']""")):
        m = re.search(rx, texts.get(key) or "", re.M)
        if m:
            return m.group(1)
    return None


# --- cachés de APIs (compartidas entre pilot y full) -------------------------------------------
cache = sqlite3.connect(cache_dir(cfg) / "api_cache.sqlite")
cache.execute("CREATE TABLE IF NOT EXISTS kv (ns TEXT, k TEXT, v TEXT, PRIMARY KEY (ns, k))")


def cget(ns, k):
    r = cache.execute("SELECT v FROM kv WHERE ns=? AND k=?", (ns, k)).fetchone()
    return json.loads(r[0]) if r else None


def cput(ns, k, v):
    cache.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (ns, k, json.dumps(v)))
    cache.commit()


gh = GitHub(cfg)
NS = "gql3"  # namespace de caché de la consulta GraphQL actual


def search_all(base_q: str) -> list[dict]:
    """Search API con partición por rangos de estrellas y de fecha de push para no pasar de 1000 por consulta."""
    out = []
    lo_date = date.fromisoformat(S["pushed_after"])
    star_ranges = [(3, 4), (5, 7), (8, 12), (13, 20), (21, 40), (41, 100), (101, 400), (401, None)]
    star_ranges = [(max(a, S["supplement_min_stars"]), b) for a, b in star_ranges if b is None or b >= S["supplement_min_stars"]]

    def run(stars, d0, d1):
        sq = f"stars:{stars[0]}..{stars[1]}" if stars[1] else f"stars:>={stars[0]}"
        q = f"{base_q} language:Python fork:false archived:false {sq} pushed:{d0}..{d1}"
        first = cget("search", f"{q}|1") or gh.search_repos(q, 1)
        cput("search", f"{q}|1", first)
        total = first["total_count"]
        if total > 1000 and d0 < d1:
            mid = d0 + (d1 - d0) // 2
            run(stars, d0, mid)
            run(stars, mid + timedelta(days=1), d1)
            return
        items = first["items"]
        for page in range(2, min(10, (total - 1) // 100 + 1) + 1):
            res = cget("search", f"{q}|{page}") or gh.search_repos(q, page)
            cput("search", f"{q}|{page}", res)
            items += res["items"]
        out.extend(items)

    for sr in star_ranges:
        run(sr, lo_date, date.fromisoformat(S["snapshot_date"]))
    return out


with stage(cfg, "s1_select", [CAND, SEL]) as st:
    F = st["funnel"]
    rng = random.Random(cfg["seed"])

    # 1. Pool del corpus
    conn = gapfinder_conn(cfg)
    rows = conn.execute(
        """SELECT substr(id, 8), title, description, coalesce(readme,''), created_at, stars
           FROM items WHERE source='github' AND json_extract(extra,'$.language')='Python'
           AND archived=0 AND last_activity_at >= ?""", (S["pushed_after"],)).fetchall()
    pool, control_pool = {}, {}
    for full, title, desc, readme, created, stars in rows:
        text = f"{title} {desc} {readme}".lower()
        kw = [d for d in S["domains"] if KW[d].search(text) and (d != "llm" or created >= S["llm_created_after"])]
        cand = dict(repo=full, src="corpus", kw_domains=kw, desc=desc, readme=readme, stars=stars, created_at=created)
        # Control: repos del corpus sin ninguna keyword de dominio (las dependencias se verifican después)
        (pool if kw else control_pool)[full.lower()] = cand
    F["pool_corpus_python_activo_con_keyword"] = len(pool)

    # 2. Complemento por Search API
    searches = {"django": ["django"],
                "llm": [f"llm OR openai OR anthropic OR langchain OR chatgpt created:>={S['llm_created_after']}",
                        f"litellm OR ollama OR rag OR gpt OR claude created:>={S['llm_created_after']}"]}
    n_search = 0
    for dom, qs in ((d, q) for d, q in searches.items() if d in S["domains"]):
        for q in qs:
            for it in search_all(q):
                key = it["full_name"].lower()
                if key in pool:
                    if dom not in pool[key]["kw_domains"]:
                        pool[key]["kw_domains"].append(dom)
                    continue
                n_search += 1
                pool[key] = dict(repo=it["full_name"], src="search", kw_domains=[dom],
                                 desc=it.get("description") or "", readme="", stars=it["stargazers_count"],
                                 created_at=it["created_at"])
    F["pool_search_nuevos"] = n_search
    F["pool_total"] = len(pool)
    control_pool = {k: c for k, c in control_pool.items() if k not in pool}
    F["pool_control_corpus_sin_keyword"] = len(control_pool)

    # 3. Filtro didáctico (nombre/descripción/README truncado del corpus)
    for c in [*pool.values(), *control_pool.values()]:
        name = c["repo"].split("/")[1]
        c["edu"] = bool(EDU_NAME.search(f"{name} {c['desc']}") or EDU_README.search(c["readme"]))
        c["paper"] = bool(PAPER_README.search(c["readme"]))
    F["descartados_didactico_prefetch"] = sum(c["edu"] for c in pool.values())
    F["descartados_paper_prefetch"] = sum(c["paper"] and not c["edu"] for c in pool.values())

    # 4. Orden aleatorio por dominio y evaluación por tandas hasta cubrir cuotas
    queues = {d: [] for d in GROUPS}
    for c in sorted(pool.values(), key=lambda c: c["repo"].lower()):
        if not c["edu"] and not c["paper"]:
            for d in c["kw_domains"]:
                queues[d].append(c)
    queues["control"] = [c for c in sorted(control_pool.values(), key=lambda c: c["repo"].lower())
                         if not c["edu"] and not c["paper"]]
    for d in queues:
        rng.shuffle(queues[d])
    # Se evalúan primero los repos ya seleccionados en el piloto (clones y embeddings cacheados);
    # el piloto es una muestra aleatoria del mismo pool, así que no sesga la selección.
    PILOT_SEL = ROOT / cfg["paths"]["data"] / "pilot" / "s1_selected.parquet"
    if PILOT_SEL.exists():
        prev = set(pd.read_parquet(PILOT_SEL).repo.str.lower())
        for d in queues:
            queues[d].sort(key=lambda c: c["repo"].lower() in prev)  # estable: los previos al final (pop)

    GQL_FIELDS = """nameWithOwner isFork isArchived pushedAt createdAt stargazerCount
      primaryLanguage { name }
      languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
      defaultBranchRef { name target { oid } }
      root: object(expression: "HEAD:") { ... on Tree { entries { name type } } }
      req: object(expression: "HEAD:requirements.txt") { ... on Blob { text } }
      pyproject: object(expression: "HEAD:pyproject.toml") { ... on Blob { text } }
      setuppy: object(expression: "HEAD:setup.py") { ... on Blob { text } }
      setupcfg: object(expression: "HEAD:setup.cfg") { ... on Blob { text } }
      pipfile: object(expression: "HEAD:Pipfile") { ... on Blob { text } }
      readme: object(expression: "HEAD:README.md") { ... on Blob { text } }"""

    def fetch_chunk(chunk: list[str]):
        parts = []
        for j, r in enumerate(chunk):
            o, n = r.split("/", 1)
            parts.append(f'r{j}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) {{ {GQL_FIELDS} }}')
        res = gh.graphql("query {" + "\n".join(parts) + "}")
        if res is None:  # demasiado pesado: se parte a la mitad
            if len(chunk) == 1:
                cput(NS, chunk[0].lower(), {"missing": True, "error": "graphql_5xx"})
                return
            fetch_chunk(chunk[:len(chunk) // 2])
            fetch_chunk(chunk[len(chunk) // 2:])
            return
        data = res.get("data") or {}
        for j, r in enumerate(chunk):
            v = data.get(f"r{j}")
            if v:
                for k in ("readme", "req", "pyproject", "setuppy", "setupcfg", "pipfile"):
                    if v.get(k) and v[k].get("text"):
                        v[k]["text"] = v[k]["text"][:20000]
            cput(NS, r.lower(), v or {"missing": True})

    ROOT_DEPS = ("req", "pyproject", "setuppy", "setupcfg", "pipfile")
    SUB_DEP_FILE = re.compile(r"^(requirements[\w.-]*\.txt|pyproject\.toml|pipfile|setup\.py)$", re.I)

    def sub_dep_paths(m: dict) -> list[str]:
        """Archivos de dependencias un nivel abajo (backend/requirements.txt, requirements/base.txt, ...)."""
        paths = []
        for e in (m.get("root") or {}).get("entries") or []:
            if e["type"] == "blob" and re.match(r"requirements[\w.-]*\.txt$", e["name"], re.I):
                paths.append(e["name"])
            if e["type"] == "tree" and not e["name"].startswith("."):
                for sub in (e.get("object") or {}).get("entries") or []:
                    if sub["type"] == "blob" and (SUB_DEP_FILE.match(sub["name"]) or
                                                  (e["name"].lower() == "requirements" and sub["name"].endswith(".txt"))):
                        paths.append(f"{e['name']}/{sub['name']}")
        return paths[:8]

    def fetch_subdeps(repos_meta: dict):
        todo = [(r, sub_dep_paths(m)) for r, m in repos_meta.items()
                if not m.get("missing") and not any((m.get(k) or {}).get("text") for k in ROOT_DEPS)
                and cget(NS + "_sub", r.lower()) is None and cget("gql2_sub", r.lower()) is None]
        for r, paths in todo:
            if not paths:
                cput(NS + "_sub", r.lower(), {})
        todo = [(r, p) for r, p in todo if p]
        for i in range(0, len(todo), 10):
            parts = []
            for j, (r, paths) in enumerate(todo[i:i + 10]):
                o, n = r.split("/", 1)
                files = " ".join(f'f{k}: object(expression: {json.dumps("HEAD:" + p)}) {{ ... on Blob {{ text }} }}'
                                 for k, p in enumerate(paths))
                parts.append(f"r{j}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) {{ {files} }}")
            res = gh.graphql("query {" + "\n".join(parts) + "}") or {}
            data = res.get("data") or {}
            for j, (r, paths) in enumerate(todo[i:i + 10]):
                v = data.get(f"r{j}") or {}
                cput(NS + "_sub", r.lower(), {p: ((v.get(f"f{k}") or {}).get("text") or "")[:20000]
                                              for k, p in enumerate(paths)})

    TREE_Q = 'root: object(expression: "HEAD:") { ... on Tree { entries { name type object { ... on Tree { entries { name type } } } } } }'

    def fetch_trees(metas: dict):
        """Árbol de un nivel solo para repos sin dependencias en la raíz (la consulta anidada para todos da 502)."""
        need = [r for r, m in metas.items() if not m.get("missing")
                and not any((m.get(k) or {}).get("text") for k in ROOT_DEPS)
                and not any("object" in e for e in (m.get("root") or {}).get("entries") or [])
                and cget(NS + "_tree", r.lower()) is None]
        for i in range(0, len(need), 10):
            chunk = need[i:i + 10]
            parts = [f"r{j}: repository(owner: {json.dumps(r.split('/', 1)[0])}, name: {json.dumps(r.split('/', 1)[1])}) {{ {TREE_Q} }}"
                     for j, r in enumerate(chunk)]
            data = (gh.graphql("query {" + "\n".join(parts) + "}") or {}).get("data") or {}
            for j, r in enumerate(chunk):
                cput(NS + "_tree", r.lower(), ((data.get(f"r{j}") or {}).get("root")) or {})
        for r, m in metas.items():
            tree = cget(NS + "_tree", r.lower())
            if tree:
                m["root"] = tree

    def fetch_meta(repos: list[str]) -> dict:
        # gql2 = caché del piloto anterior (con árbol anidado para todos); sigue sirviendo
        todo = [r for r in repos if cget(NS, r.lower()) is None and cget("gql2", r.lower()) is None]
        for i in range(0, len(todo), 15):
            fetch_chunk(todo[i:i + 15])
        metas = {r: cget(NS, r.lower()) or cget("gql2", r.lower()) for r in repos}
        fetch_trees(metas)
        fetch_subdeps(metas)
        for r, m in metas.items():
            m["sub"] = cget(NS + "_sub", r.lower()) or cget("gql2_sub", r.lower()) or {}
        return metas

    def pypi_exists(pkg: str, repo: str) -> bool:
        """Librería si el paquete existe en PyPI y apunta a este repo o se llama igual que el repo."""
        key = norm_pkg(pkg)
        v = cget("pypi", key)
        if v is None:
            r = requests.get(f"https://pypi.org/pypi/{key}/json", timeout=30)
            v = {"exists": False}
            if r.status_code == 200:
                info = r.json()["info"]
                urls = " ".join([info.get("home_page") or "", info.get("download_url") or "",
                                 *(info.get("project_urls") or {}).values()]).lower()
                v = {"exists": True, "urls": urls}
            cput("pypi", key, v)
        if not v["exists"]:
            return False
        return f"github.com/{repo.lower()}" in v["urls"] or key == norm_pkg(repo.split("/")[1])

    seen_owners, selected, evaluated = set(), {d: [] for d in GROUPS}, []
    lo, hi = S["min_py_lines"] * PY_BYTES_PER_LINE, S["max_py_lines"] * PY_BYTES_PER_LINE

    def evaluate(c: dict, queue: str) -> tuple[str, dict]:
        m = c["meta"]
        if m.get("missing"):
            return "no_accesible", {}
        if m["isFork"]:
            return "fork", {}
        if m["isArchived"]:
            return "archivado", {}
        if (m.get("primaryLanguage") or {}).get("name") != "Python":
            return "lenguaje_no_python", {}
        if m["pushedAt"] < S["pushed_after"]:
            return "push_viejo", {}
        py = sum(e["size"] for e in m["languages"]["edges"] if e["node"]["name"] == "Python")
        info = {"py_bytes": py, "est_py_lines": py // PY_BYTES_PER_LINE}
        if not lo <= py <= hi:
            return "tamano_fuera_de_rango", info
        readme = (m.get("readme") or {}).get("text") or ""
        if EDU_README.search(readme):
            return "didactico_readme", info
        if PAPER_README.search(readme):
            return "paper_readme", info
        texts = {k: (m.get(k) or {}).get("text") for k in ROOT_DEPS}
        pkg = declared_package(texts)  # solo paquetes declarados en la raíz
        if not any(texts.values()) and m["sub"]:
            texts = {"req": "\n".join(t for p, t in m["sub"].items() if not p.endswith((".toml", ".py"))),
                     "pyproject": "\n".join(t for p, t in m["sub"].items() if p.endswith(".toml")),
                     "setuppy": "\n".join(t for p, t in m["sub"].items() if p.endswith(".py"))}
            info["deps_location"] = "subdir"
        else:
            info["deps_location"] = "root"
        info["declared_package"] = pkg
        if pkg and pypi_exists(pkg, c["repo"]):
            return "publica_en_pypi", info
        root_entries = (m.get("root") or {}).get("entries") or []
        entries = {e["name"].lower() for e in root_entries}
        sub_manage = any(s["name"] == "manage.py" for e in root_entries
                         for s in ((e.get("object") or {}).get("entries") or []))
        info["app_signals"] = sorted(entries & {"manage.py", "requirements.txt", "dockerfile", "docker-compose.yml",
                                                "docker-compose.yaml", "compose.yml", "compose.yaml", "requirements"})
        deps = dep_names(texts)
        doms = [d for d in S["domains"] if deps & DEPS[d]]
        if ("manage.py" in entries or sub_manage) and "django" not in doms:
            doms.append("django")
        if "llm" in doms and m["createdAt"] < S["llm_created_after"]:
            doms.remove("llm")
        if not doms and not any(texts.values()):
            return "sin_archivos_de_dependencias", info
        if queue == "control":
            if doms:
                return "control_con_dependencia_de_dominio", info
            info["domains"], info["domain"] = [], "control"
        elif not doms:
            return "sin_dependencia_de_dominio", info
        else:
            info["domains"] = doms
            info["domain"] = next(d for d in DOMAIN_PRIORITY if d in doms)
        info["sha"] = m["defaultBranchRef"]["target"]["oid"] if m.get("defaultBranchRef") else None
        if not info["sha"]:
            return "sin_rama_default", info
        return "ok", info

    BATCH = 40
    while True:
        open_doms = [d for d in GROUPS if len(selected[d]) < QUOTAS.get(d, 0) and queues[d]]
        if not open_doms:
            break
        batch = []
        for d in open_doms:
            need = QUOTAS[d] - len(selected[d])
            while queues[d] and len([b for b in batch if b[0] == d]) < min(BATCH, need * 2 + 5):
                c = queues[d].pop()
                if not c.get("done"):
                    batch.append((d, c))
        metas = fetch_meta([c["repo"] for _, c in batch])
        for d, c in batch:
            if c.get("done"):
                continue
            c["done"] = True
            owner = c["repo"].split("/")[0].lower()
            c["meta"] = metas[c["repo"]]
            if owner in seen_owners:
                status, info = "owner_repetido", {}
            else:
                status, info = evaluate(c, d)
            if status == "ok":
                dom = info["domain"]
                if len(selected[dom]) >= QUOTAS.get(dom, 0):
                    status = "cuota_llena"
                else:
                    seen_owners.add(owner)
                    selected[dom].append(c["repo"])
            evaluated.append({"repo": c["repo"], "owner": c["repo"].split("/")[0], "src": c["src"],
                              "queue": d, "kw_domains": c["kw_domains"], "status": status,
                              "stars": c["meta"].get("stargazerCount", c["stars"]),
                              "pushed_at": c["meta"].get("pushedAt"), "created_at": c["meta"].get("createdAt"),
                              **{k: info.get(k) for k in ("py_bytes", "est_py_lines", "declared_package",
                                                          "app_signals", "deps_location", "domains", "domain", "sha")}})
        print("  seleccionados:", {d: len(v) for d, v in selected.items()}, "| evaluados:", len(evaluated))

    cand = pd.DataFrame(evaluated)
    cand.to_parquet(CAND)
    sel = cand[cand.status == "ok"].copy()
    sel.to_parquet(SEL)

    F["evaluados_con_graphql"] = len(cand)
    for k, v in cand.status.value_counts().items():
        F[f"  estado:{k}"] = int(v)
    F["seleccionados"] = len(sel)
    for k, v in sel.domain.value_counts().items():
        F[f"  dominio:{k}"] = int(v)
    F["  deps_en_subcarpeta"] = int((sel.deps_location == "subdir").sum())
