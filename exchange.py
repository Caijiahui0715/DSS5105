import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_BASE_URL = "https://api.frankfurter.dev/v2/rate"
# Everyday names that are not ISO 4217 codes; the rate service only knows the ISO code.
_ALIASES = {"RMB": "CNY"}
# The rate service also quotes crypto-currencies, precious metals and the IMF's unit of account;
# budgets and rents are in national currencies only.
NOT_NATIONAL = frozenset({"BTC", "ETH", "LTC", "BCH", "XRP", "XAU", "XAG", "XPT", "XPD", "XDR"})
# Today's rates from the service, by (base, quote): it publishes once a working day.
_rates: dict[tuple[str, str], tuple[str, Decimal, str]] = {}


class CurrencyConversionError(RuntimeError):
    pass


class UnknownCurrencyError(CurrencyConversionError):
    """The rate service answered but does not know this currency code."""


class NotNationalCurrencyError(UnknownCurrencyError):
    """A crypto-currency, a precious metal or the IMF's unit of account."""


def currency_code(currency: str) -> str:
    """The ISO 4217 code of a national currency, from a code or RMB."""
    code = currency.strip().upper()
    code = _ALIASES.get(code, code)
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError("currency must be a 3-letter code")
    if code in NOT_NATIONAL:
        raise NotNationalCurrencyError(f"{code} is not a national currency")
    return code


def rate(base: str, quote: str, *, opener=urlopen) -> tuple[Decimal, str]:
    """How much of quote one unit of base buys, and the rate's date. Rates from the service are
    kept until the end of the day."""
    base, quote = currency_code(base), currency_code(quote)
    today = date.today().isoformat()
    if base == quote:
        return Decimal(1), today
    kept = _rates.get((base, quote)) if opener is urlopen else None
    if kept and kept[0] == today:
        return kept[1], kept[2]

    request = Request(
        f"{_BASE_URL}/{base.lower()}/{quote.lower()}",
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
            f"Exchange-rate service rejected {base if quote == 'SGD' else f'{base}/{quote}'} (HTTP {error.code})"
        ) from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise CurrencyConversionError("Exchange-rate service is unavailable") from error

    try:
        value = Decimal(str(payload["rate"]))
        rate_date = str(payload["date"])
    except (KeyError, TypeError, InvalidOperation) as error:
        raise CurrencyConversionError("Exchange-rate service returned invalid data") from error
    if value <= 0:
        raise CurrencyConversionError("Exchange-rate service returned an invalid rate")
    if opener is urlopen:
        _rates[(base, quote)] = (today, value, rate_date)
    return value, rate_date


def convert_to_sgd(
    amount: int,
    currency: str,
    *,
    opener=urlopen,
) -> dict[str, int | str]:
    """Convert one positive ISO-4217 budget to a whole-SGD search limit."""
    code = currency_code(currency)
    if amount <= 0:
        raise ValueError("amount must be positive and currency must be a 3-letter code")
    value, rate_date = rate(code, "SGD", opener=opener)
    converted = int(
        (Decimal(amount) * value).to_integral_value(rounding=ROUND_FLOOR)
    )
    if converted <= 0:
        raise CurrencyConversionError("Converted SGD budget is too small")
    return {
        "original_amount": amount,
        "original_currency": code,
        "rate_to_sgd": format(value, "f"),
        "rate_date": rate_date,
        "amount_sgd": converted,
    }
