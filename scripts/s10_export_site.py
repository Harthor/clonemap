"""Etapa 10: exporta site/data.json para el explorador estático (site/index.html, GitHub Pages).

Textos públicos en inglés: nombre y descripción de la etapa 8b (las descripciones de la etapa 8 están en español
y no se exportan). Incluye solo lo necesario: por dominio, el top `site_top_n` por owners de cada sección de la vista por dominio
(específico, enriquecido no exclusivo, genérico, framework), más todos los clusters etiquetados.
Por cluster: descripción (Haiku si está etiquetado), términos, owners, % del dominio vs % del control, etiquetas,
librerías aceptadas por Jev y % de repos que ya las declaran, y hasta `site_examples` ejemplos de owners
distintos del dominio (los más cercanos al centroide).
Del código ajeno NO se copia la función: solo sus primeras `site_snippet_lines` líneas (la firma) y el link al
archivo en GitHub en el commit exacto.
También escribe en site/index.html el HTML estático del <head> (meta y Open Graph), el hero, los números y las
tarjetas de utilidades confirmadas, entre marcadores <!-- static:x -->, para que se vean sin JavaScript.
Uso: uv run scripts/s10_export_site.py [--mode full]
"""
import html
import json
import re
import textwrap
from datetime import date

import pandas as pd

from common import ROOT
from s7_report import R, cfg, cl, domain_sections, fn, OUT

S = cfg["site"]
SECTION_IDS = {"Específicos de": "specific", "Enriquecidos no exclusivos": "nonexclusive",
               "Idiomáticos del framework": "framework", "Marcados como genéricos": "generic"}


def section_id(title: str) -> str:
    return next(v for k, v in SECTION_IDS.items() if title.startswith(k))


def snippet(code: str) -> str:
    """Las primeras líneas de la función (firma incluida), sin el resto del cuerpo."""
    lines = textwrap.dedent(code).splitlines()
    return "\n".join(lines[:S["site_snippet_lines"]])


def nan_none(x):
    return None if pd.isna(x) else x


lab = pd.read_csv(OUT / "etiquetado.csv").set_index("topic")
en = pd.read_csv(OUT / "descripciones_en.csv").set_index("topic")  # nombre y descripción en inglés (etapa 8b)
use = pd.read_csv(OUT / "uso_librerias.csv").set_index("topic")
secs = {}  # "Específicos de django" y "de llm" van a la misma sección: se concatenan, ordenadas por owners
for t, df in domain_sections(cl).items():
    secs[section_id(t)] = pd.concat([secs.get(section_id(t), df.iloc[:0]), df]).sort_values(
        ["owners_main", "owners"], ascending=False)

picked = {}  # topic -> sección
for sid, df in secs.items():
    for d in cfg["selection"]["domains"]:
        for t in df[df.domain_main == d].head(S["site_top_n"]).topic:
            picked.setdefault(t, sid)
for t in lab.index:
    picked.setdefault(t, next(sid for sid, df in secs.items() if t in set(df.topic)))

clusters = []
for t, sid in picked.items():
    c = cl.set_index("topic").loc[t]
    d = c.domain_main
    ex = fn[(fn.topic == t) & (fn.domain == d)].sort_values("sim_centroid", ascending=False).drop_duplicates("owner")
    item = {
        "id": int(t), "domain": d, "section": sid, "terms": list(c.terms)[:8],
        "owners": int(c.owners_main), "owners_control": int(c.owners_control),
        "pct_domain": round(100 * c.domain_prev, 1), "pct_control": round(100 * c.control_prev, 1),
        "enrichment": round(float(c.enrichment), 2), "variants": int(c.n_functions), "cohesion": round(float(c.cohesion), 2),
        "examples": [{"repo": r.repo, "path": r.path, "name": r.qualname, "url": r.url, "lines": f"{r.start}-{r.end}",
                      "snippet": snippet(r.code)} for r in ex.head(S["site_examples"]).itertuples()],
    }
    if t in lab.index:
        lr = lab.loc[t]
        item["label"] = {
            "name": S.get("name_overrides", {}).get(int(t), en.loc[t, "name_en"]),
            "description": en.loc[t, "description_en"], "jev": lr.categoria_jev, "jev_ambiguous": bool(lr.jev_ambigua),
            "jev_probs": {k: float(lr[f"jev_p_{k}"]) for k in ("uso_sdk", "idiomatico_framework", "utilidad_reimplementada", "otro")},
            "haiku": lr.categoria_haiku, "status": lr.estado,
            "libraries": [x for x in str(nan_none(lr.librerias_aceptadas) or "").split("; ") if x],
            "libraries_rejected": [x.split(": ")[0] for x in str(nan_none(lr.librerias_jev) or "").split("; ")
                                   if x and float(x.split(": ")[1]) < cfg["label"]["jev_lib_min_prob"]],
        }
        if t in use.index:
            u = use.loc[t]
            # Base = todos los proyectos del dominio en el cluster (la misma que el número grande de la tarjeta);
            # un proyecto sin dependencias declaradas cuenta como que no la declara.
            item["label"]["already_declared_pct"] = (round(100 * u.repos_con_alguna_lib / u.repos_cluster, 1)
                                                     if item["label"]["libraries"] else None)
            item["label"]["already_declared"] = f"{int(u.repos_con_alguna_lib)}/{int(u.repos_cluster)}"
    clusters.append(item)
clusters.sort(key=lambda x: -x["owners"])

st = json.loads((OUT / "stats.json").read_text())
f1, f3, f4, f6 = (st[k]["funnel"] for k in ("s1_select", "s3_parse", "s4_dedup", "s6_cluster"))
sizes = {k.split(":")[1]: int(v) for k, v in f1.items() if k.strip().startswith("dominio:")}  # repos seleccionados
data = {
    "generated": str(date.today()),
    "run": {"repos": sizes, "candidates_evaluated": f1["evaluados_con_graphql"], "candidate_pool": f1["pool_total"],
            "functions": f3["funciones_finales"], "variants": f4["representantes"], "clusters": f6["clusters"],
            "clusters_8_owners": f6["clusters_con_>=8_owners"], "section_sizes": {k: len(v) for k, v in secs.items()},
            "llm_cost_usd": S["llm_cost_usd"]},
    "params": {"specific_max_ctrl": R["specific_max_ctrl"], "min_owners": R["specific_min_owners"],
               "generic_min_ctrl_prev": R["generic_min_ctrl_prev"], "generic_max_enr_ctrl": R["generic_max_enr_ctrl"],
               "framework_min_frac": R["framework_min_frac"], "jev_lib_min_prob": cfg["label"]["jev_lib_min_prob"],
               "jev_ambiguous_margin": cfg["label"]["jev_ambiguous_margin"]},
    "headline": next(c for c in clusters if c["id"] == S["headline_topic"]),
    "clusters": clusters,
}
# --- HTML estático: head (meta / Open Graph), hero, números y tarjetas, para que se vean sin JavaScript y los lean
# buscadores y vistas previas. Se reescriben entre marcadores <!-- static:x --> ... <!-- /static:x --> de site/index.html.
APP = {"llm": "LLM", "django": "Django"}
e = html.escape
h = data["headline"]
H_PCT, H_CTRL = round(h["pct_domain"]), round(h["pct_control"])
H_LIB, H_USE = h["label"]["libraries"][0].split("==")[0], round(h["label"]["already_declared_pct"])
n_repos = sum(data["run"]["repos"].values())
title = f"{H_PCT}% of LLM apps write their own parser for the JSON the model returns"
desc = (f"In regular Python projects it's {H_CTRL}%. A library for this exists ({H_LIB}); only {H_USE}% of those apps use it. "
        f"A look at what projects keep rewriting, across {n_repos:,} GitHub projects.")
url = S["site_url"]


def times(c) -> str:
    return f"×{max(1, round(c['enrichment']))}"


def library_line(c) -> str:
    L = c["label"]
    if not L["libraries"]:
        return '<span class="none">No existing library passed our check</span>'
    names = ", ".join(x.split("==")[0] for x in L["libraries"])
    used = (f" — {round(L['already_declared_pct'])}% of these projects use {'one' if len(L['libraries']) > 1 else 'it'}"
            if L.get("already_declared_pct") is not None else "")
    return f"<span>Existing: {e(names)}{e(used)}</span>"


static = {
    "head": f"""<title>clonemap — what projects keep rewriting</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="clonemap">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{url}og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{e(f'{H_PCT}% of LLM apps vs {H_CTRL}% of regular Python projects write their own parser for JSON from model replies.')}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{url}og.png">""",
    "hero": f"""<h1><em>{H_PCT}% of LLM apps</em> write their own parser for the JSON the model returns.</h1>
<p class="lead">In regular Python projects it's {H_CTRL}%. A library for this exists ({e(H_LIB)}); only {H_USE}% of those apps use it.</p>
<div class="numbers">
  <div><b>{n_repos:,}</b><span>GitHub projects analyzed</span></div>
  <div><b>{data['run']['functions']:,}</b><span>functions read and compared</span></div>
  <div><b>${data['run']['llm_cost_usd']:.2f}</b><span>total cost of the analysis</span></div>
</div>""",
    "cards": "\n".join(
        f"""<button type="button" class="card" data-id="{c['id']}" aria-label="{e(c['label']['name'])}: see details">
  <span class="kicker">{APP[c['domain']]} apps</span>
  <h3>{e(c['label']['name'])}</h3>
  <div class="stat"><div><b>{c['owners']:,}</b><span>projects wrote it</span></div><div><b>{times(c)}</b><span>vs. regular Python</span></div></div>
  <div class="lib">{library_line(c)}</div>
</button>"""
        for c in sorted((c for c in clusters if c.get("label") and c["label"]["status"] == "confirmado"
                         and c["label"]["jev"] == "utilidad_reimplementada"), key=lambda c: -c["owners"])),
}
r = data["run"]
n_lab = len(lab)
n_conf = int((lab.estado == "confirmado").sum())
n_util = sum(1 for c in clusters if c.get("label") and c["label"]["status"] == "confirmado"
             and c["label"]["jev"] == "utilidad_reimplementada")
libs_proposed = sum(len([x for x in str(nan_none(v) or "").split("; ") if x]) for v in lab.librerias_haiku)
libs_kept = sum(len([x for x in str(nan_none(v) or "").split("; ") if x]) for v in lab.librerias_aceptadas)
L8 = cfg["label"]
argparse = max((c for c in clusters if c["section"] == "generic" and "argparse" in c["terms"][:6]), key=lambda c: c["owners"])
steps = [
    ("Pick the projects", f"{r['repos']['llm']:,} LLM apps, {r['repos']['django']:,} Django apps and {r['repos']['control']:,} "
                          "regular Python projects from GitHub — apps, not libraries or tutorials, one project per owner."),
    ("Download the code", "Only the Python files, at a fixed version, so every link points to the exact code analyzed."),
    ("Cut it into functions", f"{r['functions']:,} functions of at least 10 lines, leaving out tests and generated code."),
    ("Merge copy-paste", "Near-identical copies count once: the goal is the same job written in different ways."),
    ("Group by meaning", f"A code-reading model places similar functions together; {r['clusters']:,} groups came out."),
    ("Compare and review", "Each group is checked against the regular projects; the top ones were reviewed by two AI models."),
]
limits = [
    f"The comparison group is small ({r['repos']['control']:,} projects). Something can be missing from it by chance, so small differences are not meaningful.",
    "The groups differ in popularity: regular projects come from a list of mostly well-starred repositories; LLM and Django apps include many small ones.",
    "One of the two AI reviewers scores each answer separately, so its scores don't add up to 100%; about a third of its reviews came out unsure.",
    "Two models agreeing is a lead, not proof. Every finding here deserves a human look at the examples.",
    "\"% use it\" counts projects that list the library as a direct dependency; a library pulled in indirectly is not counted.",
    "The code-reading model only sees the first part of long functions.",
    f"One snapshot of GitHub, taken in October 2026 (data generated {data['generated']}).",
]
static["method"] = f"""<section class="hero">
  <h2 class="title">How this was measured</h2>
  <p class="lead">The idea: if many unrelated projects write the same piece of code by hand, something may be missing — or something
    exists and is not being found. Nobody has to ask for the library; the code shows the need.</p>
</section>
<section class="block">
  <h2>Six steps</h2>
  <p class="sub">Everything ran on one laptop. The only paid part was the AI review at the end.</p>
  <ol class="flow">
{chr(10).join(f'    <li><b>{e(b)}</b><span>{e(t)}</span></li>' for b, t in steps)}
  </ol>
</section>
<section class="block">
  <h2>The control group</h2>
  <div class="prose">
    <p>Some code appears in almost every Python program: reading command-line options, setting up logs, loading a settings file.
      Counting only LLM and Django apps, that code looks specific to them just because they are most of the sample.</p>
    <p>So {r['repos']['control']:,} regular Python projects, with no Django and no AI libraries, go through the same steps. Every group
      is then measured as "share of these apps that have it" divided by "share of regular Python projects that have it". That is the
      × number in the table.</p>
  </div>
  <div class="compare">
    <div><h4>Command-line argument parsing</h4><p>{round(argparse['pct_domain'])}% of LLM apps write it, which made it look "LLM-specific"
      when compared only among LLM and Django apps. But {round(argparse['pct_control'])}% of regular Python projects write it too, so it
      is marked <em>common everywhere</em>.</p></div>
    <div><h4>Parsing JSON out of model replies</h4><p>{H_PCT}% of LLM apps, {H_CTRL}% of regular Python projects. Present in both, but
      {times(h)[1:]} times more common in LLM apps: <em>mostly in LLM apps</em>.</p></div>
  </div>
</section>
<section class="block">
  <h2>Checked by two AI models</h2>
  <div class="prose">
    <p>The top {n_lab} groups were shown to two models, each with six functions from different projects. <b>Jev 1.13</b> (TypeSafe)
      scored four statements — "calls an AI or web service", "framework boilerplate", "reimplemented utility", "other" — and picked
      the most likely; if its first choice beat the second by less than {L8['jev_ambiguous_margin']}, it counted as unsure.
      <b>Claude Haiku</b> answered the same question in its own words.</p>
    <p>A group is <em>confirmed</em> when both models agree and Jev is not unsure: {n_conf} of {n_lab}. Of those, {n_util} are
      reimplemented utilities, the cards at the top of the page.</p>
    <p>For libraries, Haiku proposed {libs_proposed} names. Each was checked to exist on PyPI and then scored by Jev on whether it
      directly solves the job; {libs_kept} scored at least {L8['jev_lib_min_prob']} and are shown. "No existing library passed our check"
      means none did.</p>
  </div>
</section>
<section class="block">
  <h2>Limits</h2>
  <ul class="limits">
{chr(10).join(f'    <li>{e(t)}</li>' for t in limits)}
  </ul>
</section>"""
static["footer"] = (f"Data from <span id=\"gen\">{data['generated']}</span>. Code examples belong to their authors; the explorer shows at "
                    "most five lines of each and links to the original file. "
                    "<a href=\"https://github.com/Harthor/clonemap\">Source and full method on GitHub</a> (MIT).")
page_path = ROOT / "site" / "index.html"
page = page_path.read_text()
for k, v in static.items():
    page, n = re.subn(rf"(<!-- static:{k}[^>]*-->\n).*?(<!-- /static:{k} -->)", lambda m: m.group(1) + v + "\n" + m.group(2),
                      page, flags=re.S)
    assert n == 1, f"marcador static:{k} no encontrado en index.html"
page_path.write_text(page)

dst = ROOT / "site" / "data.json"
dst.parent.mkdir(exist_ok=True)
dst.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
print(f"escrito {dst}: {len(clusters)} clusters, {dst.stat().st_size / 1024:.0f} KB; HTML estático en {page_path}")
