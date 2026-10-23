#!/bin/zsh
# Corrida completa: etapas 1–7 en modo full, en orden, cortando ante el primer error.
# caffeinate -i evita que la Mac se duerma mientras corre. Logs en logs/full_<etapa>.log (los de intentos
# anteriores quedan como logs/full_<etapa>.<fecha>.log). Re-correrlo saltea las etapas ya terminadas.
cd "$(dirname "$0")/.."
for st in s1_select s2_download s3_parse s4_dedup s5_embed s6_cluster s6b_annotate s7_report; do
  # Un log anterior de esta etapa se renombra con su fecha en vez de pisarse
  [[ -f logs/full_$st.log ]] && mv logs/full_$st.log logs/full_$st.$(date -r logs/full_$st.log '+%Y%m%d-%H%M%S').log
  echo "$(date '+%F %T') inicio $st"
  PYTHONUNBUFFERED=1 caffeinate -i uv run scripts/$st.py --mode full > logs/full_$st.log 2>&1 || { echo "$(date '+%F %T') ERROR en $st (ver logs/full_$st.log)"; exit 1; }
  echo "$(date '+%F %T') fin $st"
done
echo "$(date '+%F %T') corrida completa terminada"
