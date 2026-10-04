import io
import json
import unittest
import urllib.error

from exchange import CurrencyConversionError, UnknownCurrencyError, convert_to_sgd


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


if __name__ == "__main__":
    unittest.main()
