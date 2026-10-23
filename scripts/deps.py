"""Parseo de dependencias declaradas (requirements*.txt, Pipfile, pyproject.toml, setup.py, setup.cfg).
Lo usan la etapa 1 (clasificar dominio) y s9_deps_check.py (¿el repo ya tiene la librería?)."""
import re


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
