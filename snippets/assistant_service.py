import calendar
import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from google import genai
from google.genai import errors, types

from app.core.config import settings
from app.core.exceptions import AssistantError
from app.services.assistant_knowledge import ASSISTANT_SYSTEM_PROMPT
from app.services.billing_service import BillingService

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 700
# One tool round-trip is enough for earnings lookups and keeps cost/latency bounded.
MAX_TOOL_ROUNDS = 1

EARNINGS_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_earnings_summary",
            description=(
                "Zwraca rzeczywiste rozliczenia tygodniowe zalogowanego kierowcy z "
                "ostatnich N miesięcy (zarobek końcowy, status, tygodnie). Użyj tego "
                "narzędzia zawsze, gdy kierowca pyta o swoje zarobki, wypłaty lub "
                "rozliczenia za konkretny okres — nie zgaduj kwot samodzielnie."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "months_back": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 24,
                        "description": (
                            "Liczba miesięcy wstecz od dziś, np. 3 dla "
                            '"ostatnie 3 miesiące".'
                        ),
                    },
                },
                "required": ["months_back"],
            },
        )
    ]
)


def _months_ago(today: date, months: int) -> date:
    """Subtract calendar months from a date, clamping the day to month length."""
    total_months = today.month - 1 - months
    year = today.year + total_months // 12
    month = total_months % 12 + 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class AssistantService:
    """Driver-facing LLM assistant: FAQ chat grounded in real earnings data.

    Uses Gemini function calling so the model never invents payout figures —
    when a question needs numbers, it calls `get_earnings_summary`, which we
    execute against BillingService scoped to the caller's own driver_id.
    """

    def __init__(self, billing_service: BillingService):
        self.billing_service = billing_service
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def chat(self, driver_id: UUID, message: str) -> str:
        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part.from_text(text=message)])
        ]
        config = types.GenerateContentConfig(
            system_instruction=ASSISTANT_SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[EARNINGS_TOOL],
        )

        try:
            response = self._client.models.generate_content(
                model=settings.GEMINI_MODEL, contents=contents, config=config
            )

            rounds = 0
            while response.function_calls and rounds < MAX_TOOL_ROUNDS:
                rounds += 1
                contents.append(response.candidates[0].content)
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=call.name,
                                response=self._run_tool(call, driver_id),
                            )
                            for call in response.function_calls
                        ],
                    )
                )

                response = self._client.models.generate_content(
                    model=settings.GEMINI_MODEL, contents=contents, config=config
                )
        except errors.APIError as e:
            logger.exception("Gemini API call failed")
            raise AssistantError("assistant.unavailable") from e

        return (response.text or "").strip()

    def _run_tool(self, call: types.FunctionCall, driver_id: UUID) -> dict[str, Any]:
        if call.name == "get_earnings_summary":
            months_back = (call.args or {}).get("months_back", 3)
            return self._get_earnings_summary(driver_id, months_back)
        return {"error": f"unknown_tool:{call.name}"}

    def _get_earnings_summary(
        self, driver_id: UUID, months_back: int
    ) -> dict[str, Any]:
        months_back = max(1, min(int(months_back), 24))
        today = date.today()
        date_from = _months_ago(today, months_back)

        payouts = self.billing_service.get_driver_payouts_in_range(
            driver_id, date_from, today
        )
        total = sum((p.final_payout_amount for p in payouts), Decimal("0"))

        return {
            "period_from": date_from.isoformat(),
            "period_to": today.isoformat(),
            "weeks_count": len(payouts),
            "total_final_payout": str(total),
            "currency": "PLN",
            "weeks": [
                {
                    "year": p.year,
                    "week_number": p.week_number,
                    "status": p.status.value,
                    "final_payout_amount": str(p.final_payout_amount),
                }
                for p in payouts
            ],
        }
