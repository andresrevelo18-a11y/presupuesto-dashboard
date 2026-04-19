#!/usr/bin/env python3
"""
Agente de análisis presupuestario personal.

Uso:
    python3 scripts/budget_agent.py                         # Análisis completo
    python3 scripts/budget_agent.py --refresh               # Actualiza JSON desde Excel primero
    python3 scripts/budget_agent.py -q "¿Cuándo liquido PacifiCard?"
    python3 scripts/budget_agent.py --schedule              # Muestra cómo programar ejecución automática
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
JSON_FILE = DATA_DIR / "presupuesto.json"

MODEL = "claude-haiku-4-5-20251001"


def _load_api_key() -> str:
    """Carga ANTHROPIC_API_KEY desde el entorno o desde .env en la raíz del proyecto."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key

    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key

    raise SystemExit(
        "\n❌  Falta la API key de Anthropic.\n\n"
        "Opciones:\n"
        "  1. Variable de entorno:  export ANTHROPIC_API_KEY=sk-ant-...\n"
        f"  2. Archivo .env en {ROOT}:  ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "Obtén tu clave en: https://console.anthropic.com/settings/keys\n"
    )

# ─── Herramientas disponibles para el agente ────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_budget_data",
        "description": (
            "Obtiene todos los datos del presupuesto: resumen, flujo mensual, "
            "deudas, activos y distribución semanal."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "calculate_debt_payoff",
        "description": (
            "Calcula en cuántos meses se liquidará una deuda dado su saldo, "
            "pago mensual y cualquier pago extra disponible. "
            "Proyección lineal — menciona que no incluye intereses para deudas rotativas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "debt_name": {"type": "string", "description": "Nombre de la deuda"},
                "balance": {"type": "number", "description": "Saldo actual en USD"},
                "monthly_payment": {"type": "number", "description": "Pago mensual en USD"},
                "extra_monthly": {
                    "type": "number",
                    "description": "Pago extra mensual adicional (0 si ninguno)",
                    "default": 0,
                },
            },
            "required": ["debt_name", "balance", "monthly_payment"],
        },
    },
    {
        "name": "evaluate_cash_flow",
        "description": (
            "Evalúa el flujo de caja de un mes: calcula el margen libre, "
            "alerta si hay déficit y sugiere ajustes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Nombre del mes"},
                "income": {"type": "number", "description": "Ingresos del mes"},
                "fixed_expenses": {"type": "number", "description": "Gastos fijos del mes"},
                "cushion": {"type": "number", "description": "Colchón disponible para cubrir déficit"},
            },
            "required": ["month", "income", "fixed_expenses", "cushion"],
        },
    },
    {
        "name": "save_report",
        "description": "Guarda el reporte de análisis en un archivo Markdown con timestamp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Contenido completo del reporte en Markdown"},
            },
            "required": ["content"],
        },
    },
]

# ─── Implementación de herramientas ─────────────────────────────────────────

def _get_budget_data() -> dict:
    if not JSON_FILE.exists():
        raise FileNotFoundError(
            f"{JSON_FILE} no existe. Ejecuta con --refresh para generarlo."
        )
    with open(JSON_FILE, encoding="utf-8") as f:
        return json.load(f)


def _calculate_debt_payoff(
    debt_name: str,
    balance: float,
    monthly_payment: float,
    extra_monthly: float = 0,
) -> dict:
    effective = monthly_payment + extra_monthly
    if effective <= 0:
        return {"error": "El pago mensual debe ser > 0"}

    months = 0
    remaining = balance
    while remaining > 0 and months < 600:
        remaining -= effective
        months += 1

    today = date.today()
    total_months = today.month - 1 + months
    payoff_year = today.year + total_months // 12
    payoff_month = total_months % 12 + 1

    return {
        "deuda": debt_name,
        "saldo_actual": balance,
        "pago_mensual_efectivo": effective,
        "meses_para_liquidar": months,
        "fecha_estimada_liquidacion": f"{payoff_year}-{payoff_month:02d}",
        "nota": "Proyección lineal sin intereses — para deudas rotativas el plazo real es mayor",
    }


def _evaluate_cash_flow(
    month: str,
    income: float,
    fixed_expenses: float,
    cushion: float,
) -> dict:
    gross_margin = income - fixed_expenses
    status = "SUPERÁVIT" if gross_margin >= 0 else "DÉFICIT"
    after_cushion = cushion + gross_margin if gross_margin < 0 else cushion

    return {
        "mes": month,
        "ingresos": income,
        "gastos_fijos": fixed_expenses,
        "margen_bruto": round(gross_margin, 2),
        "estado": status,
        "colchon_resultante": round(after_cushion, 2),
        "alerta": "Déficit cubierto por colchón de abril" if gross_margin < 0 else None,
    }


def _save_report(content: str) -> dict:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = REPORTS_DIR / f"analisis_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return {"guardado_en": str(path.relative_to(ROOT)), "timestamp": ts}


def _dispatch(tool_name: str, tool_input: dict) -> str:
    """Despacha la llamada a la herramienta correcta y devuelve JSON string."""
    try:
        if tool_name == "get_budget_data":
            result = _get_budget_data()
        elif tool_name == "calculate_debt_payoff":
            result = _calculate_debt_payoff(**tool_input)
        elif tool_name == "evaluate_cash_flow":
            result = _evaluate_cash_flow(**tool_input)
        elif tool_name == "save_report":
            result = _save_report(**tool_input)
        else:
            result = {"error": f"Herramienta desconocida: {tool_name}"}
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)


# ─── Bucle agéntico ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Eres un agente experto en finanzas personales para Andrés, quien vive en Ecuador. \
Tu función es analizar su presupuesto, identificar riesgos y recomendar acciones concretas.

Estrategia de deuda: Avalancha (debt avalanche) — pagar mínimos en todas las deudas \
y aplicar cada peso extra a la de mayor interés. Orden de prioridad actual:
1. PacifiCard Rotativo (más costosa, interés alto)
2. Banco del Austro (93.8 % de utilización — riesgo crediticio)
3. Banco Guayaquil
4. Diners Club
5. Pichincha
6. Produbanco Préstamo (cuota fija, largo plazo)

Reglas que siempre debes respetar en tu análisis:
- El colchón de abril ($4,623.27) es INTOCABLE para el mes de mayo.
- El límite diario de gasto variable es $20/día (medido semanalmente).
- El ratio deuda/ingreso está en 81.9 % — zona de alerta roja.

Formato de salida: Markdown limpio con secciones, tablas y semáforos (🟢🟡🔴). \
Termina siempre con un TABLERO DE CONTROL que use semáforos por área.\
"""


def run_agent(question: str | None = None, verbose: bool = True) -> str:
    client = anthropic.Anthropic(api_key=_load_api_key())
    today = date.today().isoformat()

    if question:
        user_content = f"Hoy es {today}. {question}"
    else:
        user_content = f"""\
Hoy es {today}. Necesito mi análisis financiero completo de hoy.

Por favor:
1. Carga los datos del presupuesto.
2. Analiza el flujo de caja de abril y mayo.
3. Calcula la proyección de pago de cada deuda.
4. Revisa el presupuesto semanal y los límites de gasto.
5. Identifica los 3 principales riesgos y las 3 acciones prioritarias para esta semana.
6. Guarda el reporte completo.

Sé específico con números y fechas.\
"""

    messages: list[dict] = [{"role": "user", "content": user_content}]

    # Bucle agéntico con soporte a cache en el system prompt
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        if response.stop_reason != "tool_use":
            break

        # Procesa todas las llamadas a herramientas del turno
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"  ⚙  {block.name}({json.dumps(block.input, ensure_ascii=False)})", file=sys.stderr)
                result = _dispatch(block.name, block.input)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )

        messages.append({"role": "user", "content": tool_results})

    return ""


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _print_schedule_help() -> None:
    script = ROOT / "scripts" / "budget_agent.py"
    print(f"""
╔══════════════════════════════════════════════════════╗
║        Programar análisis automático (crontab)       ║
╚══════════════════════════════════════════════════════╝

Ejecuta `crontab -e` y agrega una de las siguientes líneas:

  # Cada lunes a las 7 AM
  0 7 * * 1  python3 {script} >> ~/analisis_presupuesto.log 2>&1

  # Todos los días a las 8 AM
  0 8 * * *  python3 {script} >> ~/analisis_presupuesto.log 2>&1

  # Cada inicio de mes con refresh desde Excel
  0 6 1 * *  python3 {script} --refresh >> ~/analisis_presupuesto.log 2>&1

Los reportes se guardan automáticamente en:
  {REPORTS_DIR}/analisis_YYYYMMDD_HHMM.md
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agente de análisis presupuestario con Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Regenera presupuesto.json desde el Excel antes de analizar",
    )
    parser.add_argument(
        "--question", "-q", type=str, metavar="PREGUNTA",
        help="Pregunta específica en lugar del análisis completo",
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="Muestra instrucciones para programar ejecución automática",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="No muestra herramientas en uso (solo output final)",
    )
    args = parser.parse_args()

    if args.schedule:
        _print_schedule_help()
        return

    if args.refresh:
        print("↻  Actualizando datos desde Excel...", file=sys.stderr)
        export_script = ROOT / "scripts" / "export_presupuesto_data.py"
        subprocess.run(["python3", str(export_script)], check=True)

    print("🤖 Agente presupuestario iniciando análisis...\n", file=sys.stderr)
    result = run_agent(question=args.question, verbose=not args.quiet)
    print(result)


if __name__ == "__main__":
    main()
