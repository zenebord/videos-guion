#!/bin/sh
# Publica canciones y guiones en GitHub (y por lo tanto en GitHub Pages).
# OJO: el repo es público, así que todo lo que haya en biblioteca/ y proyectos/ queda a la vista.
cd "$(dirname "$0")" || exit 1
git add -A
if git diff --cached --quiet; then echo "Nada para publicar."; exit 0; fi
git commit -q -m "Actualiza canciones y guiones" && git push && echo "Publicado: https://zenebord.github.io/videos-guion/ (tarda ~1 minuto en actualizarse)"
