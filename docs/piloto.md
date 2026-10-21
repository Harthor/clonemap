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
