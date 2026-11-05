import io
import json
import unittest
import urllib.error
from decimal import Decimal
from unittest.mock import patch

import exchange
from exchange import CurrencyConversionError, NotNationalCurrencyError, UnknownCurrencyError, convert_to_sgd, rate


class ExchangeTest(unittest.TestCase):
    def test_converts_any_iso_currency_to_sgd(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return io.BytesIO(
                json.dumps(
                    {
                        "date": "2026-09-15",
                        "base": "CNY",
                        "quote": "SGD",
                        "rate": 0.18,
                    }
                ).encode()
            )

        result = convert_to_sgd(5_000, "cny", opener=opener)

        self.assertEqual(result["amount_sgd"], 900)
        self.assertEqual(result["rate_to_sgd"], "0.18")
        self.assertEqual(result["rate_date"], "2026-09-15")
        self.assertEqual(
            calls[0][0].full_url,
            "https://api.frankfurter.dev/v2/rate/cny/sgd",
        )
        self.assertEqual(
            calls[0][0].get_header("User-agent"),
            "singapore-rental-agent/0.1",
        )
        self.assertEqual(calls[0][1], 10)

    def test_rmb_is_sent_as_its_iso_code(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(json.dumps({"date": "2026-10-02", "rate": 0.18}).encode())

        result = convert_to_sgd(5_000, "RMB", opener=opener)

        self.assertEqual(calls, ["https://api.frankfurter.dev/v2/rate/cny/sgd"])
        self.assertEqual(result["original_currency"], "CNY")
        self.assertEqual(result["amount_sgd"], 900)

    def test_refused_codes_are_told_apart_from_outages(self):
        def failing(status):
            def opener(request, timeout):
                raise urllib.error.HTTPError(request.full_url, status, "error", {}, None)
            return opener

        with self.assertRaises(UnknownCurrencyError):
            convert_to_sgd(5_000, "NTD", opener=failing(404))
        for status in (429, 503):
            with self.subTest(status=status):
                with self.assertRaises(CurrencyConversionError) as caught:
                    convert_to_sgd(5_000, "CNY", opener=failing(status))
                self.assertNotIsInstance(caught.exception, UnknownCurrencyError)

    def test_reports_api_failure_without_guessing(self):
        def opener(request, timeout):
            raise urllib.error.URLError("offline")

        with self.assertRaises(CurrencyConversionError):
            convert_to_sgd(5_000, "CNY", opener=opener)

    def test_rates_between_any_two_national_currencies(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(json.dumps({"date": "2026-10-27", "rate": 5.3215}).encode())

        self.assertEqual(rate("sgd", "rmb", opener=opener), (Decimal("5.3215"), "2026-10-27"))
        self.assertEqual(calls, ["https://api.frankfurter.dev/v2/rate/sgd/cny"])
        # The same currency needs no rate.
        self.assertEqual(rate("SGD", "SGD", opener=opener)[0], 1)
        self.assertEqual(len(calls), 1)

    def test_crypto_currencies_and_metals_are_refused_without_a_call(self):
        def opener(request, timeout):
            raise AssertionError("no call expected")

        for code in ("BTC", "eth", "XAU", "XDR"):
            with self.subTest(code=code), self.assertRaises(NotNationalCurrencyError):
                convert_to_sgd(1, code, opener=opener)
        # Still an unknown currency to callers that only know that error.
        self.assertTrue(issubclass(NotNationalCurrencyError, UnknownCurrencyError))

    def test_the_service_is_asked_once_a_day_per_pair(self):
        calls = []

        def answer(request, timeout):
            calls.append(request.full_url)
            return io.BytesIO(json.dumps({"date": "2026-10-27", "rate": 5.3}).encode())

        exchange._rates.clear()
        self.addCleanup(exchange._rates.clear)
        with patch("exchange.urlopen", answer):
            first = exchange.rate("SGD", "CNY", opener=exchange.urlopen)
            second = exchange.rate("SGD", "CNY", opener=exchange.urlopen)
            exchange._rates[("SGD", "CNY")] = ("2000-01-01", Decimal("1"), "2000-01-01")
            third = exchange.rate("SGD", "CNY", opener=exchange.urlopen)

        self.assertEqual(first, second)
        self.assertEqual(third, (Decimal("5.3"), "2026-10-27"))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
