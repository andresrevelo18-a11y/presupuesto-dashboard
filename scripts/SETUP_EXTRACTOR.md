# Configuración del Extractor de Gastos del Correo

## 1. Instalar dependencias

```bash
pip install anthropic google-auth-oauthlib google-auth-httplib2 google-api-python-client openpyxl
```

## 2. Configurar Google Cloud (una sola vez)

1. Ve a https://console.cloud.google.com/
2. Crea un proyecto nuevo (o usa uno existente)
3. Busca "Gmail API" en la biblioteca de APIs → Habilitar
4. Ve a "Credenciales" → "Crear credenciales" → "ID de cliente OAuth 2.0"
5. Tipo de aplicación: **Aplicación de escritorio**
6. Descarga el JSON y guárdalo como `credentials.json` en la raíz del proyecto
7. En "Pantalla de consentimiento OAuth", agrega tu correo como usuario de prueba

## 3. Configurar clave de API de Anthropic

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## 4. Ejecutar el extractor

```bash
# Básico: últimos 60 días, máximo 100 correos
python scripts/email_expense_extractor.py

# Personalizado
python scripts/email_expense_extractor.py --days 30 --max-emails 200

# Con nombre de archivo específico
python scripts/email_expense_extractor.py --output mis_gastos.xlsx
```

La primera vez, el script abrirá el navegador para autorizar el acceso a Gmail.
Las credenciales se guardan en `token.json` para usos futuros.

## Resultado

Se genera un archivo Excel en `data/gastos_correo_FECHA.xlsx` con:
- **Hoja "Gastos del correo"**: tabla con fecha, monto, moneda, comercio, descripción, categoría
- **Hoja "Resumen por categoría"**: totales agrupados por categoría
