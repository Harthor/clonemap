# Piloto (200 repos), 21-oct-2026

Reporte HTML: `data/pilot/report.html` (top 50 clusters, mínimo 3 owners porque con 200 repos casi no hay 8).
Re-correr cualquier etapa: `uv run scripts/sN_*.py --mode pilot [--force]`.

## Tiempo y disco por etapa

| Etapa | Tiempo | Disco | Entra → sale |
|---|---|---|---|
| 1 Selección | 35,6 min | <1 MB (+96 MB de caché de APIs) | pool 19.838 → 1.744 evaluados → **200** (70 Django, 100 LLM, 30 ETL) |
| 2 Descarga | 1,1 min | 189 MB | 200 → 200 (0 errores) |
| 3 Parseo | 6 s | 20 MB | 16.838 archivos .py → 41.436 funciones de ≥6 líneas |
| 4 Copias | 7 s | 27 MB | 41.436 → 39.643 representantes (1.793 copias colapsadas) |
| 5 Embeddings | **25 min** | 20 MB | 39.643 × 256-d (26 fn/s en MPS) |
| 6 Clustering | 42 s | 1 MB | 1.958 clusters; 28.127 funciones en clusters, 11.516 ruido |
| 7 Reporte | segundos | 1 MB | 236 clusters con ≥8 owners, 50 con ≥15 |

Embudo de la Etapa 1 (repos evaluados con GraphQL): tamaño fuera de 2k–50k líneas 920 · publica en PyPI 260 ·
sin dependencia del dominio 210 · sin archivos de dependencias 84 · didáctico por README 31 · owner repetido 19 · otros 20 · **ok 200**.
Antes de GraphQL se descartaron 2.375 repos del pool por keywords didácticas en el nombre o la descripción.
Etapa 3: se excluyeron 4.479 archivos en directorios excluidos, 439 de tests, 263 autogenerados y 18 modelos de HF copiados;
también 17.733 funciones de menos de 6 líneas y 2.624 funciones anidadas.

## Lo que cambié durante el piloto

- **Dominio solo por dependencias reales.** La primera versión clasificaba por keyword cuando no había archivos de dependencias en la raíz (94 de 200 repos). Eso metía código de papers. Ahora se buscan dependencias también un nivel abajo (`backend/requirements.txt`, `requirements/base.txt`): así se clasificaron 39 de los 200. Si no aparece ninguna, el repo se descarta.
- **Exclusiones nuevas en la Etapa 3:** `manage.py`, `wsgi.py` y `asgi.py` (los genera `startproject`; el `main()` de `manage.py` aparecía copiado en 33 owners) y los `modeling_*.py` y similares copiados de HF transformers.
- **Embeddings:** bajé a 256 tokens y lotes de 16 (medido: con 512 tokens da 13 fn/s; con 256 tokens, 20–40). El 39 % de las funciones se trunca a 256 tokens; la firma, el docstring y el comienzo del cuerpo quedan adentro.
- **Bug corregido en la Etapa 6:** las estadísticas por cluster usaban índices del subconjunto sin ruido sobre el dataframe completo, así que los conteos de owners estaban cruzados entre clusters.
- **Términos:** el c-TF-IDF de BERTopic quedaba dominado por el owner con más funciones del cluster. Ahora los términos se ponderan por owners distintos × idf entre clusters; el c-TF-IDF original se guarda en `terms_ctfidf`.

## Qué se ve (sin interpretar)

Cohesión de los clusters del top: 0,67–0,82 (entre dos funciones al azar, ~0,23). Ejemplos de lo que aparece arriba:
armado de prompts, CLIs con argparse, parseo de fechas a UTC, carga de configs YAML, carga de JSONL, conexión a base de datos,
retry con backoff, deep merge de dicts, "humanizar" duraciones, wrappers de clientes LLM (varios clusters), conteo de tokens de uso,
registros de tools para agentes y handlers de excepciones de Django.

## Extrapolación

**Primero: 5.000 repos no se alcanzan con los filtros actuales.** Pool después del filtro didáctico × rendimiento medido en el piloto:

| Dominio | Pool | Rendimiento | Repos esperables |
|---|---|---|---|
| Django | 5.947 | 19 % | ~1.100 |
| LLM | 9.003 | 15 % | ~1.350 (≈780 si se excluye el código de papers) |
| ETL | 2.666 | 5 % | ~140 |
| **Total** | | | **~2.600** (≈2.000 sin papers) |

La mayor pérdida está en el tamaño: el 53 % de los repos evaluados tiene menos de 2k líneas de Python según la estimación por bytes.

Tiempos de la corrida completa (~198 funciones por repo):

| Etapa | ~2.600 repos | 5.000 repos (hipotético) |
|---|---|---|
| 1 Selección (evaluar todo el pool, ~17.600) | ~2 h con la optimización de abajo (~6 h sin ella) | igual |
| 2 Descarga | ~15 min · 2,5 GB | ~30 min · 4,7 GB |
| 3 + 4 | ~5 min · 0,6 GB | ~10 min · 1,2 GB |
| 5 Embeddings | **~5,5 h** (515k funciones) | **~10,5 h** (990k) |
| 6 Clustering (con prefiltro kNN arriba de 300k) | ~30–45 min | ~1 h |
| **Total** | **~8–9 h · ~3,5 GB** | **~14 h · ~6,5 GB** |

Notas:
- **Los embeddings son el cuello de botella** (26 fn/s). Mi estimación de la Etapa 0 (100–200 fn/s) estaba mal: con 110 M de parámetros y 256 tokens, la GPU del M2 no da para más. La máquina además tenía ~8 GB de swap en uso por otras apps, y eso empeora los tiempos. Si se cerraran Chrome y el resto, iría algo más rápido.
- **Optimización planificada para la Etapa 1:** pedir el árbol de un nivel solo para los repos sin dependencias en la raíz. La consulta anidada para todos genera muchos 502 de GitHub, y eso explica los 36 min del piloto.

## Decisiones pendientes

1. **Volumen:** ¿aceptamos ~2.600 repos, o ampliamos LLM con la Search API (stars ≥3, como Django) y/o bajamos el mínimo de 2k a ~1k líneas?
2. **Código de papers en LLM:** el 42 % de los repos LLM del piloto tiene arXiv o BibTeX en el README (benchmarks, implementaciones de papers). No son "apps que usan LLMs". ¿Los excluyo con esos marcadores?
3. **Embeddings:** ¿corre de noche con 256 tokens, o subo el mínimo a 10 líneas no vacías (−25 % de funciones, −25 % de tiempo)?

---

# Cambios del 22-oct y piloto regenerado

Pedidos aplicados:
1. **Especificidad de dominio por cluster** (`domain_share`): fracción de sus owners en el dominio mayoritario. Para cada cluster se guarda también la base (fracción de ese dominio entre todos los owners) y un p binomial unilateral. Hay una segunda vista, `data/pilot/report_dominio.html`, con los clusters de especificidad ≥80 % y ≥8 owners, agrupados por dominio y ordenados por owners. Las dos vistas se linkean entre sí; la vista por owners (`report.html`) no cambió.
2. **Mínimo de 10 líneas no vacías** por función (antes 6).
3. **Repos de papers excluidos** (arXiv, BibTeX, "official implementation", "accepted at <conferencia>" en el README), en todos los dominios. **LLM ampliado con la Search API** (estrellas ≥3, creados desde 2024), igual que Django.
4. **ETL fuera.**
5. Se mantiene el mínimo de 2k líneas por repo; no se busca llegar a 5k.
6. **Etapa 1:** el árbol de carpetas se pide solo para los repos sin dependencias en la raíz.

Ajustes técnicos que hice para no re-embeddear ni re-buscar:
- **Caché de embeddings por contenido** (sha1 del código) en `data/cache/emb/codet5p-110m-embedding-256/`, compartida entre el piloto y la corrida completa. Migré los 39.643 vectores del piloto anterior.
- **En el piloto, los repos ya seleccionados antes se evalúan primero:** se reusaron 122 de 200, con sus clones y embeddings.
- **Fecha de corte fija** de la búsqueda (`snapshot_date: 2026-10-21`): al cambiar de día se había invalidado la caché de búsqueda. Además, la pausa entre requests ahora descuenta la latencia de la respuesta.

## Piloto regenerado

| Etapa | Tiempo | Notas |
|---|---|---|
| 1 Selección | 63 min | casi todo es la búsqueda LLM (~850 páginas), que corre una sola vez y queda cacheada; pool 71.362 → 840 evaluados → 200 (70 Django, 130 LLM); 92 descartados por paper |
| 2 Descarga | 0,5 min | 122 clones reusados, 78 nuevos; 181 MB |
| 3 Parseo | 6 s | 30.457 funciones de ≥10 líneas (148 por repo) |
| 4 Copias | 6 s | 29.653 representantes |
| 5 Embeddings | 6,8 min | 18.268 de la caché, 11.385 nuevos (28 fn/s) |
| 6 Clustering | 35 s | 1.480 clusters; 214 con ≥8 owners; específicos con ≥8 owners: 16 de Django y 142 de LLM |

## Ojo con la vista por dominio

**El umbral fijo del 80 % favorece a LLM**, que es el 65 % de los owners. Los clusters "específicos de LLM" de arriba incluyen utilidades genéricas, como `main()` con argparse, setup de logging o carga de YAML: superan el 80 % porque la mayoría de los repos son LLM, no por algo propio del dominio. El p binomial las distingue en parte (algunas dan p≈0,03–0,05), pero no del todo. Los 16 de Django sí son propios del dominio: management commands, activación por email, backends de autenticación, forms y vistas de error. Opciones, si querés:
(a) ordenar o filtrar esa vista por p (por ejemplo, p<0,01) o por lift (especificidad/base) en vez de por especificidad cruda;
(b) equilibrar la corrida completa con la misma cuota para los dos dominios.

## Extrapolación de la corrida completa

- **Django:** pool ~5.900 × 19 % de rendimiento (el del primer piloto; el de este está inflado porque se evaluaron primero los repos previos) ≈ **1.100**.
- **LLM:** pool ~55.000; sobra para la cuota de **1.750**.
- **Total ≈ 2.850 repos × 148 funciones ≈ 420k funciones.** Se activa el prefiltro kNN (está configurado para más de 300k).

| Etapa | Estimación |
|---|---|
| 1 Selección (~15.500 evaluaciones; la búsqueda ya está cacheada) | ~2,5 h |
| 2 Descarga | ~20 min · ~2,6 GB |
| 3 + 4 | ~5 min · ~0,4 GB |
| 5 Embeddings (~390k nuevas a ~27 fn/s) | **~4 h** |
| 6 Clustering con prefiltro kNN | ~30–45 min |
| **Total** | **~7,5–8 h · ~3,5 GB** |

---

# Vista por dominio con enriquecimiento, BH y grupo control (22-oct)

- **Enriquecimiento** = fracción suavizada con Laplace (α=1) de los owners del cluster en el dominio ÷ base del dominio (incluye al control en la base). La vista por dominio se ordena por esto.
- **q** = p binomial corregido por Benjamini-Hochberg sobre los clusters con ≥8 owners de dominio. La vista filtra q<0,05 y ≥8 owners.
- **Grupo control:** 300 repos Python del corpus de gapfinder, sin keyword de dominio y con los mismos filtros de app. Se verificó que no tuvieran Django ni LLM en las dependencias (22 descartados por eso). Pasan por las etapas 2–6 junto con los de dominio.
- **"Genérico"** = el cluster aparece en ≥3 % de los repos de control (`generic_min_ctrl_prev`). Mi primera regla (cociente dominio/control <2) no marcaba argparse, logging ni YAML, porque en LLM aparecen 2,2–2,7 veces más que en el control. Los genéricos se listan aparte, no se borran.
- **Comparación** del top 20 por dominio con los criterios A (antes), B (enriquecimiento + BH sin control) y C (con control): `docs/comparacion_dominio.md` (se genera con `scripts/compare_domain_view.py`).

**Sesgos a tener en cuenta:**
- **Estrellas:** el control sale del corpus (mediana de 258 estrellas); los repos de dominio vienen mayormente de la Search API (≥3 estrellas).
- **Base de LLM:** al sumar el control, baja del 65 % al 26 %, así que pasan más clusters LLM (120 vs 56 sin control). El filtro de genéricos compensa en parte.

**Costo extra del control en la corrida completa:** ~25 min en la Etapa 1 y ~30 min de embeddings (unas 45 mil funciones, que ya quedaron cacheadas del piloto si se reusa el mismo control).
