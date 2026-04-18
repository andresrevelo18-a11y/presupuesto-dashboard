# Fuente de datos del dashboard

El archivo `presupuesto.xlsx` es la fuente editable del dashboard.

Flujo recomendado:

1. Edita montos en `data/presupuesto.xlsx`.
2. Ejecuta:

   ```bash
   python3 scripts/export_presupuesto_data.py
   ```

3. Revisa y sube los cambios en:
   - `data/presupuesto.xlsx`
   - `data/presupuesto.json`
   - `data/presupuesto.js`
   - `index.html` si tambien cambias textos visibles.

GitHub Pages carga `data/presupuesto.js` para alimentar los graficos. Si el
archivo no carga, el dashboard mantiene valores de respaldo en `index.html`.
