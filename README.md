# videos-guion

Editor para armar guiones de videos musicales. Se marcan las etapas de una canción (verso, estribillo…) y se escribe una escena por etapa, en función del tiempo que dura cada una.

- **Pistas subidas:** biblioteca de canciones (`biblioteca/`).
- **Proyectos:** cada proyecto es un guion sobre una canción (`proyectos/<id>.json` y su `.md`). De una misma pista se pueden hacer varios guiones.

## Uso

- **Local** (guarda en disco, permite cargar canciones): `python3 servidor.py`
- **Publicar** en GitHub Pages: `./publicar.sh`
- **Remoto** (https://zenebord.github.io/videos-guion/): muestra lo publicado; las ediciones se guardan en el navegador (*Exportar JSON* para llevarlas al repo). No permite cargar canciones nuevas.
