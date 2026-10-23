"""Marca de "idiomático del framework": métodos de clases que heredan de clases base de Django / DRF / Channels.

Por AST (tree-sitter) sobre los clones: para cada método se busca la clase más interna que contiene su
primera línea y se leen sus bases directas (`class X(forms.ModelForm, Mixin)` -> ModelForm, Mixin; se
ignoran keyword args como metaclass=). Se compara el último componente del nombre contra FRAMEWORK_BASES.
Solo herencia directa: una clase que hereda de otra clase propia que a su vez hereda de ModelForm no cuenta.
Solo en repos con Django en las dependencias (en otros, `Form` o `View` pueden ser de otra librería).
"""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import tree_sitter_python as tsp
from tree_sitter import Language, Parser

FRAMEWORK_BASES = {
    # Django
    "BaseCommand", "ModelForm", "Form", "Widget", "ModelAdmin", "MiddlewareMixin", "AppConfig",
    # vistas genéricas de Django
    "View", "TemplateView", "RedirectView", "ListView", "DetailView", "CreateView", "UpdateView",
    "DeleteView", "FormView", "ArchiveIndexView", "YearArchiveView", "MonthArchiveView", "DayArchiveView",
    # DRF
    "Serializer", "ModelSerializer", "HyperlinkedModelSerializer", "ListSerializer",
    "APIView", "GenericAPIView", "ListAPIView", "CreateAPIView", "RetrieveAPIView", "UpdateAPIView",
    "DestroyAPIView", "ListCreateAPIView", "RetrieveUpdateAPIView", "RetrieveDestroyAPIView",
    "RetrieveUpdateDestroyAPIView", "ViewSet", "GenericViewSet", "ModelViewSet", "ReadOnlyModelViewSet",
    # Channels
    "AsyncWebsocketConsumer", "WebsocketConsumer", "AsyncJsonWebsocketConsumer", "JsonWebsocketConsumer",
}


def _bases(cls_node) -> list[str]:
    sup = cls_node.child_by_field_name("superclasses")
    if sup is None:
        return []
    out = []
    for ch in sup.named_children:
        if ch.type in ("identifier", "attribute"):
            out.append(ch.text.decode().split(".")[-1])
        elif ch.type == "subscript":  # Generic[T], ModelSerializer[...] poco común pero posible
            out.append(ch.child_by_field_name("value").text.decode().split(".")[-1])
    return out


def _file_job(job: tuple[str, list[int]]) -> dict[int, list[str]]:
    """(ruta, líneas de inicio 1-based) -> {línea: bases de la clase más interna que la contiene}."""
    path, starts = job
    try:
        tree = Parser(Language(tsp.language())).parse(Path(path).read_bytes())
    except OSError:
        return {}
    classes = []
    stack = [tree.root_node]
    while stack:
        n = stack.pop()
        if n.type == "class_definition":
            classes.append((n.start_point[0] + 1, n.end_point[0] + 1, n))
        stack.extend(n.children)
    out = {}
    for s in starts:
        inner = [c for c in classes if c[0] < s <= c[1]]
        if inner:
            out[s] = _bases(max(inner, key=lambda c: c[0])[2])
    return out


def framework_methods(fn: pd.DataFrame, clones: Path, django_repos: set[str], workers: int = 6) -> pd.Series:
    """fn: columnas fid, repo, path, start, is_method. Devuelve Series fid -> bool."""
    cand = fn[fn.is_method & fn.repo.isin(django_repos)]
    jobs, keys = [], []
    for (repo, path), g in cand.groupby(["repo", "path"]):
        jobs.append((str(clones / repo.replace("/", "__") / path), sorted(set(g.start))))
        keys.append((repo, path))
    bases = {}
    with ProcessPoolExecutor(workers) as ex:
        for key, res in zip(keys, ex.map(_file_job, jobs, chunksize=64)):
            for s, b in res.items():
                bases[(*key, s)] = b
    flag = [any(b in FRAMEWORK_BASES for b in bases.get((r, p, s), []))
            for r, p, s in zip(fn.repo, fn.path, fn.start)]
    return pd.Series(flag, index=fn.fid.values)
