# Etapa 0 — Reconocimiento (21-oct-2026)

Reproducible con `uv run scripts/s0_recon.py` (→ `data/s0_recon.json`). gapfinder se abrió solo en lectura (`?mode=ro`).

## 1. Qué hay en el corpus de gapfinder

`data/corpus.db`, tabla `items`: 488.231 repos de GitHub y 209.000 Show HN. Columnas por repo de GitHub:

| Campo | Estado | Notas |
|---|---|---|
| owner / repo | ✅ 100 % | sale del `id` (`github:owner/repo`) |
| title, description (+ topics) | ✅ | los topics vienen pegados en `description` como `Topics: ...` |
| README | ⚠️ 97 % | **truncado a 2.000 caracteres**; alcanza para filtrar didácticos, no para ver dependencias |
| created_at, pushed_at (`last_activity_at`) | ✅ 100 % | snapshot de sep-2026 |
| stars, archived | ✅ 100 % | casi todo ≥100 estrellas (solo 2.565 repos Python tienen menos) |
| lenguaje principal | ✅ | en `extra.language` (JSON) |
| forks | ✅ conteo | **no hay flag `fork`**, pero la ingesta usó la Search API, que excluye forks por defecto → en la práctica no hay forks |
| tamaño / líneas de Python | ❌ | falta |
| dependencias (requirements, pyproject, manage.py, Dockerfile) | ❌ | falta |
| publica en PyPI | ❌ | falta |
| embeddings | ✅ | MiniLM, e5 y bge (768-d, float16) de título+texto, en `data/cache/emb/<modelo>/corpus/*.npy` + `ids.json` (689k ids) |

Universo útil: **50.304 repos Python, no archivados, con push desde el 21-oct-2024**, de 35.536 owners distintos.

Coincidencias por keyword (título + descripción + README truncado), antes de filtrar librerías y didácticos:

| Dominio | Hits | Lectura |
|---|---|---|
| LLM (creados 2024+) | 9.730 | sobra para la meta de 1.500–2.000 |
| Django | 1.254 | **no alcanza**: 541 se llaman `django-*`/`drf-*` (casi todas librerías) y muchas otras son paquetes; quedan unas ~400–500 apps |
| ETL / pipelines | 431 | **no alcanza** |

## 2. Máquina

- Apple M2, 8 núcleos (4 de rendimiento + 4 de eficiencia), **8 GB de RAM**, MPS disponible (torch 2.14 en el venv de gapfinder), sin CUDA.
- Disco libre: **68 GB**.
- uv 0.11.1, git 2.50, Python 3.12/3.13.
- GitHub con token: 5.000 req/h core, 30 req/min search. La PyPI JSON API responde bien (200 si existe el paquete, 404 si no).

**El límite que manda son los 8 GB de RAM**, no el disco ni la CPU.

## 3. Choques con el plan (para decidir antes de seguir)

1. **Django y ETL no llegan a 1.500 desde el corpus.** El corpus está sesgado a ≥100 estrellas, y ahí lo que abunda en Django son librerías. Propuesta: completar con la GitHub Search API (`django language:Python pushed:>2024-10-21 stars:>=3` da ~6.500 repos antes de filtrar; con `stars:>=10`, ~3.000). Para ETL, búsquedas como `etl OR airflow OR dagster stars:>=10` devuelven solo ~570, así que ETL quedaría en ~300–600 o se descarta (era opcional).
2. **Dependencias, tamaño y PyPI no están en el corpus.** Propuesta: una consulta GraphQL de GitHub por cada ~50–100 repos trae `isFork`, `pushedAt`, bytes de Python (`languages`, para estimar líneas ≈ bytes/35) y el texto de `requirements.txt`, `pyproject.toml`, `setup.py`/`setup.cfg`, más si existen `manage.py` y `Dockerfile` en la raíz. Con eso se clasifica por dominio usando dependencias, **sin clonar**, y se saca el nombre real del paquete para chequearlo en PyPI (el nombre del repo no sirve: por ejemplo `pgsync` está en PyPI y `revel-backend` no).
3. **RAM para clustering.** Con 5.000 repos estimo ~1–1,5 M funciones antes de deduplicar. UMAP sobre 1 M de puntos en 8 GB queda muy justo. Propuesta (a confirmar con los números del piloto): usar un modelo de 256 dimensiones y, si hace falta, un **prefiltro kNN** (FAISS) que solo pase a BERTopic las funciones con vecinos cercanos de al menos ~3 owners distintos. Las que no tienen vecinos de otros owners nunca podrían llegar a un cluster de 8 owners, así que el prefiltro no cambia el resultado buscado. Alternativa: ajustar UMAP sobre una muestra de ~200k y hacer `transform` con el resto.

## 4. Plan concreto por etapa

Cada etapa es `scripts/sN_*.py`, lee `config.yaml`, escribe en `data/sN_*.parquet` y se saltea lo ya cacheado. Seed 42.

| Etapa | Cómo | Tiempo piloto (200) | Tiempo 5k | Disco 5k |
|---|---|---|---|---|
| 1 Selección | corpus → keywords + filtro didáctico; completar con Search API; GraphQL para metadata + archivos de dependencias; PyPI JSON; un repo por owner; dominio por deps (+ similitud bge contra centroides semilla como desempate) | ~2 min | ~15–25 min (GraphQL ~100 llamadas; PyPI ~5k GET; búsqueda limitada a 30/min) | <50 MB |
| 2 Descarga | `git clone --depth 1 --filter=blob:none --sparse` + `sparse-checkout` sin cono `*.py`; 6 en paralelo; errores a log y sigue | ~3–5 min | ~1–1,5 h | ~10–15 GB (borrables después del parseo) |
| 3 Parseo | tree-sitter-python; funciones y métodos con owner/repo/path/líneas/URL `blob/<sha>/path#Lx-Ly`; excluye vendor/site-packages/migrations/tests/fixtures/`_pb2`/clientes OpenAPI y funciones con <6 líneas no vacías; los archivos con hash idéntico en ≥5 repos se marcan como template | ~1 min | ~15–30 min (multiproceso) | ~1 GB parquet |
| 4 Copias | MinHash (64 permutaciones, shingles de 5 tokens) + LSH (umbral 0,8); se colapsa a un representante con `n_copias` y `owners_copias` | <1 min | ~15–30 min | ~0,3 GB |
| 5 Embeddings | **codet5p-110m-embedding** en MPS fp16, truncado a 512 tokens | ~3–5 min | ~1,5–3 h (≈1 M de funciones a ~100–200/s) | ~0,5 GB (256-d fp16) |
| 6 Clustering | BERTopic con UMAP (5-d) + HDBSCAN; c-TF-IDF sobre identificadores separados (snake/camel); por cluster: n funciones, owners, repos, dominios | <1 min | ~30–90 min (depende del prefiltro) | <0,5 GB |
| 7 Reporte | HTML estático; top 50 por owners distintos (≥8); 3–5 funciones de owners distintos, las más cercanas al centroide; resumen de conteos por etapa | segundos | segundos | ~10–30 MB |

**Total estimado para 5k repos:** ~4–7 h de reloj (casi todo descarga y embeddings, que pueden correr de noche) y ~15–18 GB de disco con los clones (~3 GB sin ellos).

**Por qué codet5p-110m-embedding:** está entrenado de forma contrastiva justo para recuperar código (texto↔código y código↔código), así que su espacio agrupa por intención y no por forma. Tiene 110 M de parámetros (entra cómodo en 8 GB con MPS) y saca vectores de **256 dimensiones**, 3× más livianos que los de 768 de UniXcoder o jina-v2-base-code; eso es lo que hace viable UMAP con esta RAM. jina-v2-base-code admite contextos más largos (8k), pero es más lento y pesado; UniXcoder no es un modelo de embeddings de oraciones de fábrica. Si el piloto muestra clusters flojos, comparo con jina sobre una muestra.

**El piloto (200 repos):** ~70 Django, ~100 LLM, ~30 ETL. Con 200 repos casi no va a haber clusters de ≥8 owners (sirve para medir tiempos y disco, no para validar la hipótesis); para el reporte del piloto bajaría `min_owners` a ~3 y lo marcaría como tal.

## 5. Preguntas para la usuaria

1. ¿Completo Django con la GitHub Search API, por fuera del corpus (stars ≥3 o ≥10)?
2. ¿ETL queda con lo que haya (~300–600) o se saca?
3. ¿Ok con el prefiltro kNN por owners distintos si la RAM no da para UMAP sobre todo?
