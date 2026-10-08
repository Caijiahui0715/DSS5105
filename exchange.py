import json
import re
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_BASE_URL = "https://api.frankfurter.dev/v2/rate"
# Everyday names that are not ISO 4217 codes; the rate service only knows the ISO code.
_ALIASES = {"RMB": "CNY"}


class CurrencyConversionError(RuntimeError):
    pass


class UnknownCurrencyError(CurrencyConversionError):
    """The rate service answered but does not know this currency code."""


def convert_to_sgd(
    amount: int,
    currency: str,
    *,
    opener=urlopen,
) -> dict[str, int | str]:
    """Convert one positive ISO-4217 budget to a whole-SGD search limit."""
    code = currency.strip().upper()
    code = _ALIASES.get(code, code)
    if amount <= 0 or not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError("amount must be positive and currency must be a 3-letter code")

    request = Request(
        f"{_BASE_URL}/{code.lower()}/sgd",
        headers={
            "Accept": "application/json",
            "User-Agent": "singapore-rental-agent/0.1",
        },
    )
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response, parse_float=Decimal)
    except HTTPError as error:
        # 4xx other than rate limiting means the code itself was refused; 429 and 5xx are outages.
        refused = 400 <= error.code < 500 and error.code != 429
        raise (UnknownCurrencyError if refused else CurrencyConversionError)(
            f"Exchange-rate service rejected {code} (HTTP {error.code})"
        ) from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise CurrencyConversionError("Exchange-rate service is unavailable") from error

    try:
        rate = Decimal(str(payload["rate"]))
        rate_date = str(payload["date"])
    except (KeyError, TypeError, InvalidOperation) as error:
        raise CurrencyConversionError("Exchange-rate service returned invalid data") from error
    if rate <= 0:
        raise CurrencyConversionError("Exchange-rate service returned an invalid rate")

    converted = int(
        (Decimal(amount) * rate).to_integral_value(rounding=ROUND_FLOOR)
    )
    if converted <= 0:
        raise CurrencyConversionError("Converted SGD budget is too small")
    return {
        "original_amount": amount,
        "original_currency": code,
        "rate_to_sgd": format(rate, "f"),
        "rate_date": rate_date,
        "amount_sgd": converted,
    }
