# Vista por dominio: antes y después (piloto, 2026-10-22)

`[util]` = cluster cuyos primeros términos incluyen argparse/argument/parser/logging/formatter/handlers/levelname/yaml.

| | Criterio | Clusters que pasan | django | llm |
|---|---|---|---|---|
| A | especificidad ≥80 %, ≥8 owners, orden por owners | 158 | 16 | 142 |
| B | enriquecimiento + q<0.05 (mismo clustering que A) | 73 | 17 | 56 |
| C | B + grupo control, sin genéricos (clustering nuevo) | 115 | 16 | 99 |
| C′ | marcados como genéricos por el control | 22 | 1 | 21 |

## Dónde quedan los clusters utilitarios

| | django | llm |
|---|---|---|
| A | 1 en el top 20 (#2); 1 en total | 4 en el top 20 (#1, #4, #6, #13); 8 en total |
| B | 1 en el top 20 (#13); 1 en total | 2 en el top 20 (#15, #16); 5 en total |
| C | 1 en el top 20 (#3); 1 en total | 0 en el top 20 (—); 2 en total |
| C′ genéricos | 0 en el top 20 (—); 0 en total | 3 en el top 20 (#8, #9, #12); 3 en total |

## django

### A · antes (top 20)

| # | owners | domain_share | términos |
|---|---|---|---|
| 1 | 31 | 100% | options, handle, command, stdout, style, objects |
| 2 | 22 | 86% | argument, help, arguments, parser, command, action **[util]** |
| 3 | 19 | 95% | profile, picture, instance, post, valid, render |
| 4 | 14 | 93% | validation, email, forms, cleaned, objects, serializers |
| 5 | 13 | 85% | alternatives, email, subject, send, alternative, mail |
| 6 | 13 | 92% | view, authenticated, form, context, distinct, annotate |
| 7 | 12 | 83% | email, activation, mail, resend, subject, send |
| 8 | 11 | 91% | authenticate, username, backend, email, does, consul |
| 9 | 11 | 100% | filterset, backends, urlencode, apiview, forms, nav |
| 10 | 10 | 100% | form, widget, attrs, fields, password, helper |
| 11 | 10 | 100% | cleaned, form, view, valid, redirect, objects |
| 12 | 10 | 80% | password, username, using, email, superuser, user |
| 13 | 9 | 100% | urls, urlpatterns, site, view, sitemap, admin |
| 14 | 9 | 100% | admin, queryset, changelist, deletion, redirect, site |
| 15 | 8 | 100% | custom, render, http404, request, server, denied |
| 16 | 8 | 100% | internal, representation, serializer, serializers, prep, instance |

### B · enriquecimiento + BH, sin control (top 20)

| # | owners | domain_share | enrichment | domain_q | términos |
|---|---|---|---|---|---|
| 1 | 31 | 100% | ×2.77 | 2e-12 | options, handle, command, stdout, style, objects |
| 2 | 11 | 100% | ×2.64 | 0.0005 | filterset, backends, urlencode, apiview, forms, nav |
| 3 | 10 | 100% | ×2.62 | 0.0007 | cleaned, form, view, valid, redirect, objects |
| 4 | 10 | 100% | ×2.62 | 0.0007 | form, widget, attrs, fields, password, helper |
| 5 | 9 | 100% | ×2.60 | 0.001 | urls, urlpatterns, site, view, sitemap, admin |
| 6 | 9 | 100% | ×2.60 | 0.001 | admin, queryset, changelist, deletion, redirect, site |
| 7 | 19 | 95% | ×2.59 | 8e-06 | profile, picture, instance, post, valid, render |
| 8 | 8 | 100% | ×2.57 | 0.003 | internal, representation, serializer, serializers, prep, instance |
| 9 | 8 | 100% | ×2.57 | 0.003 | custom, render, http404, request, server, denied |
| 10 | 14 | 93% | ×2.50 | 0.0005 | validation, email, forms, cleaned, objects, serializers |
| 11 | 13 | 92% | ×2.48 | 0.0007 | view, authenticated, form, context, distinct, annotate |
| 12 | 11 | 91% | ×2.42 | 0.003 | authenticate, username, backend, email, does, consul |
| 13 | 22 | 86% | ×2.38 | 7e-05 | argument, help, arguments, parser, command, action **[util]** |
| 14 | 13 | 85% | ×2.29 | 0.004 | alternatives, email, subject, send, alternative, mail |
| 15 | 12 | 83% | ×2.24 | 0.007 | email, activation, mail, resend, subject, send |
| 16 | 10 | 80% | ×2.14 | 0.02 | password, username, using, email, superuser, user |
| 17 | 13 | 69% | ×1.90 | 0.04 | login, redirect, password, username, form, authenticate |

### C · con control, sin genéricos (top 20)

| # | owners | owners_control | enrichment | domain_q | enr_vs_control | términos |
|---|---|---|---|---|---|---|
| 1 | 27 | 1 | ×6.44 | 4e-20 | ×58.53 | options, handle, command, objects, stdout, style |
| 2 | 16 | 0 | ×6.38 | 1e-12 | ×71.07 | redirect, permissions, permission, deletion, admin, denied |
| 3 | 12 | 0 | ×6.18 | 2e-09 | ×54.35 | arguments, argument, help, parser, command, action **[util]** |
| 4 | 11 | 0 | ×6.11 | 9e-09 | ×50.17 | username, handle, superuser, command, options, objects |
| 5 | 13 | 1 | ×5.87 | 2e-09 | ×29.26 | form, cleaned, valid, view, objects, redirect |
| 6 | 12 | 1 | ×5.79 | 1e-08 | ×27.17 | profile, picture, pic, user, objects, redirect |
| 7 | 13 | 2 | ×5.54 | 1e-08 | ×19.51 | form, widget, attrs, fields, forms, placeholder |
| 8 | 12 | 1 | ×5.35 | 3e-07 | ×25.08 | context, view, authenticated, objects, form, annotate |
| 9 | 8 | 1 | ×5.35 | 7e-06 | ×18.81 | representation, serializer, internal, serializers, validation, instance |
| 10 | 10 | 2 | ×5.23 | 1e-06 | ×15.33 | validation, email, form, cleaned, forms, objects |
| 11 | 13 | 2 | ×4.75 | 2e-06 | ×16.72 | redirect, form, register, login, render, password |
| 12 | 14 | 5 | ×4.21 | 6e-06 | ×9.06 | email, subject, alternatives, mail, send, attach |
| 13 | 8 | 4 | ×3.80 | 0.001 | ×6.69 | email, verification, send, confirmation, resend, verified |
| 14 | 13 | 5 | ×2.72 | 0.01 | ×5.57 | wraps, required, decorator, redirect, login, admin |
| 15 | 13 | 6 | ×2.59 | 0.02 | ×4.78 | handler, validation, exc, code, jsonresponse, errors |
| 16 | 29 | 6 | ×2.06 | 0.03 | ×6.57 | health, status, healthz, execute, connection, response |

### C′ · marcados como genéricos (top 20)

| # | owners | owners_control | enrichment | domain_q | enr_vs_control | términos |
|---|---|---|---|---|---|---|
| 1 | 13 | 9 | ×2.57 | 0.01 | ×3.76 | login, redirect, password, authenticate, username, samesite |

## llm

### A · antes (top 20)

| # | owners | domain_share | términos |
|---|---|---|---|
| 1 | 72 | 88% | main, argparse, argument, help, parser, sys **[util]** |
| 2 | 44 | 91% | dotall, jsondecode, loads, rfind, parse, group |
| 3 | 41 | 88% | vector, similarity, collection, retrieve, score, embedding |
| 4 | 33 | 94% | formatter, handlers, logging, datefmt, level, handler **[util]** |
| 5 | 31 | 84% | env, dotenv, vars, environ, startswith, splitlines |
| 6 | 30 | 93% | main, argparse, argument, help, parser, sys **[util]** |
| 7 | 27 | 93% | tool, arguments, call, tools, execute, mcpclient |
| 8 | 26 | 96% | corsmiddleware, fast, origins, methods, middleware, lifespan |
| 9 | 26 | 88% | llm, call, prompt, temperature, messages, choices |
| 10 | 25 | 88% | prompt, system, reflector, instruction, guidance, reflection |
| 11 | 25 | 84% | embed, texts, embedding, embeddings, encode, dtype |
| 12 | 24 | 88% | executescript, conn, commit, database, execute, connect |
| 13 | 24 | 96% | yaml, safe, load, config, open, overrides **[util]** |
| 14 | 23 | 91% | prompt, system, template, prompts, hints, build |
| 15 | 23 | 100% | chunks, words, overlap, chunk, sentences, split |
| 16 | 23 | 91% | stats, sum, metrics, total, performance, rate |
| 17 | 23 | 83% | extract, part, text, content, block, links |
| 18 | 23 | 96% | report, markdown, lines, render, color, reports |
| 19 | 23 | 91% | rate, limit, minute, usage, hour, daily |
| 20 | 22 | 95% | tavily, search, results, query, google, duckduckgo |

### B · enriquecimiento + BH, sin control (top 20)

| # | owners | domain_share | enrichment | domain_q | términos |
|---|---|---|---|---|---|
| 1 | 23 | 100% | ×1.48 | 0.001 | chunks, words, overlap, chunk, sentences, split |
| 2 | 20 | 100% | ×1.47 | 0.003 | httpx, transport, timeout, provider, httptransport, url |
| 3 | 18 | 100% | ×1.46 | 0.004 | queue, cancelled, worker, cancel, running, wait |
| 4 | 16 | 100% | ×1.45 | 0.007 | session, sessions, resume, oldest, expires, lock |
| 5 | 15 | 100% | ×1.45 | 0.01 | sqlite3, row, loads, created, tags, store |
| 6 | 15 | 100% | ×1.45 | 0.01 | read, unicode, decode, file, encoding, open |
| 7 | 14 | 100% | ×1.44 | 0.01 | chat, streaming, stream, media, mimetype, httpexception |
| 8 | 14 | 100% | ×1.44 | 0.01 | subprocess, stderr, returncode, shell, cwd, stdout |
| 9 | 13 | 100% | ×1.44 | 0.02 | opus, chat, provider, reasoner, models, cred |
| 10 | 13 | 100% | ×1.44 | 0.02 | api, bocha, client, openai, open, model |
| 11 | 13 | 100% | ×1.44 | 0.02 | validate, config, provider, api, bucket, warnings |
| 12 | 26 | 96% | ×1.43 | 0.003 | corsmiddleware, fast, origins, methods, middleware, lifespan |
| 13 | 12 | 100% | ×1.43 | 0.02 | event, audit, utc, lock, fileno, fsync |
| 14 | 12 | 100% | ×1.43 | 0.02 | conn, tables, commit, connect, execute, sqlite3 |
| 15 | 12 | 100% | ×1.43 | 0.02 | argparse, subparsers, argument, help, parser, dest **[util]** |
| 16 | 24 | 96% | ×1.42 | 0.004 | yaml, safe, load, config, open, overrides **[util]** |
| 17 | 11 | 100% | ×1.42 | 0.03 | commands, display, focus, ask, event, handle |
| 18 | 11 | 100% | ×1.42 | 0.03 | evaluate, eval, case, evaluation, cases, faithfulness |
| 19 | 11 | 100% | ×1.42 | 0.03 | estimate, chars, messages, total, tokens, calls |
| 20 | 11 | 100% | ×1.42 | 0.03 | provider, providers, questionary, effort, select, ask |

### C · con control, sin genéricos (top 20)

| # | owners | owners_control | enrichment | domain_q | enr_vs_control | términos |
|---|---|---|---|---|---|---|
| 1 | 11 | 0 | ×3.29 | 3e-06 | ×27.36 | answer, abstain, faithful, chunks, faithfulness, claim |
| 2 | 9 | 0 | ×3.20 | 2e-05 | ×22.80 | conditional, edges, graph, edge, workflow, compile |
| 3 | 9 | 0 | ×3.20 | 2e-05 | ×22.80 | temperature, chat, messages, tokens, tools, calls |
| 4 | 14 | 0 | ×3.16 | 2e-06 | ×31.92 | knowledge, top, vector, search, rerank, retrieve |
| 5 | 8 | 0 | ×3.14 | 7e-05 | ×20.52 | agent, tools, idle, intent, callable, router |
| 6 | 8 | 0 | ×3.14 | 7e-05 | ×20.52 | structured, temperature, schema, chat, complete, llmprovider |
| 7 | 8 | 0 | ×3.14 | 7e-05 | ×20.52 | api, genai, temperature, provider, tokens, gemini |
| 8 | 51 | 7 | ×3.02 | 3e-16 | ×13.68 | prompt, system, context, build, join, lines |
| 9 | 10 | 1 | ×3.02 | 5e-05 | ×12.54 | stdio, sse, mcp, servers, enter, initialize |
| 10 | 10 | 1 | ×3.02 | 5e-05 | ×12.54 | classify, query, words, keywords, domain, classifier |
| 11 | 19 | 1 | ×3.00 | 6e-07 | ×20.52 | vectors, vector, embeddings, chunks, embedding, documents |
| 12 | 13 | 2 | ×2.99 | 8e-06 | ×10.64 | decision, decisions, reason, decided, outcome, feedback |
| 13 | 13 | 2 | ×2.99 | 8e-06 | ×10.64 | chat, streaming, stream, media, httpexception, response |
| 14 | 41 | 5 | ×2.98 | 1e-12 | ×14.44 | jsondecode, loads, dotall, rfind, parse, json |
| 15 | 26 | 2 | ×2.97 | 1e-08 | ×18.24 | llm, prompt, temperature, messages, call, choices |
| 16 | 16 | 3 | ×2.97 | 2e-06 | ×9.69 | pdf, pages, page, pdfplumber, reader, extract |
| 17 | 20 | 3 | ×2.95 | 3e-07 | ×11.40 | llm, openai, temperature, chat, api, langchain |
| 18 | 9 | 1 | ×2.95 | 0.0001 | ×11.40 | git, pull, hub, branch, repo, github |
| 19 | 9 | 1 | ×2.95 | 0.0001 | ×11.40 | docs, sources, article, blocks, lines, markdown |
| 20 | 12 | 2 | ×2.94 | 2e-05 | ×9.88 | sse, event, rolled, executing, stream, iterator |

### C′ · marcados como genéricos (top 20)

| # | owners | owners_control | enrichment | domain_q | enr_vs_control | términos |
|---|---|---|---|---|---|---|
| 1 | 26 | 13 | ×2.38 | 4e-06 | ×4.23 | env, dotenv, environ, vars, splitlines, startswith |
| 2 | 39 | 23 | ×2.30 | 7e-08 | ×3.71 | report, markdown, summary, lines, results, render |
| 3 | 16 | 11 | ×2.05 | 0.002 | ×3.04 | read, unicode, encoding, file, iowrapper, decode |
| 4 | 21 | 14 | ×2.02 | 0.0008 | ×3.04 | conn, sqlite3, commit, executescript, execute, database |
| 5 | 22 | 19 | ×2.01 | 0.0004 | ×2.62 | corsmiddleware, fast, origins, middleware, methods, lifespan |
| 6 | 15 | 9 | ×1.99 | 0.005 | ×3.19 | fetch, headers, url, html, beautiful, jina |
| 7 | 17 | 11 | ×1.98 | 0.003 | ×3.04 | fromisoformat, expires, unknown, used, any, datetime |
| 8 | 28 | 22 | ×1.96 | 0.0002 | ×2.68 | main, argparse, argument, help, parser, sys **[util]** |
| 9 | 30 | 28 | ×1.89 | 0.0002 | ×2.36 | yaml, load, safe, config, open, exists **[util]** |
| 10 | 18 | 12 | ×1.86 | 0.007 | ×2.81 | clean, sub, replacements, strip, splitlines, text |
| 11 | 16 | 13 | ×1.80 | 0.01 | ×2.44 | validate, config, provider, asr, api, slack |
| 12 | 37 | 37 | ×1.79 | 0.0002 | ×2.16 | formatter, logging, handlers, level, handler, datefmt **[util]** |
| 13 | 10 | 9 | ×1.74 | 0.05 | ×2.28 | pretrained, model, transformer, device, load, transformers |
| 14 | 15 | 11 | ×1.72 | 0.03 | ×2.47 | lines, headings, line, blocks, sections, heading |
| 15 | 12 | 12 | ×1.71 | 0.04 | ×2.10 | resolved, resolve, relative, absolute, posix, root |
| 16 | 13 | 9 | ×1.69 | 0.05 | ×2.51 | migrations, migrate, migration, conn, schema, execute |
| 17 | 11 | 11 | ×1.69 | 0.05 | ×2.09 | banner, welcome, logo, console, style, display |
| 18 | 16 | 20 | ×1.67 | 0.02 | ×1.85 | subprocess, stderr, returncode, stdout, cwd, pipe |
| 19 | 33 | 19 | ×1.61 | 0.01 | ×2.62 | evidence, reason, expires, severity, started, score |
| 20 | 16 | 18 | ×1.56 | 0.05 | ×1.80 | daemon, stop, shutdown, threading, port, thread |
