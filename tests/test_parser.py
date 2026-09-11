import unittest
from unittest.mock import Mock

from models import SearchPreferences
from parser import parse_preferences


class ParserTest(unittest.TestCase):
    def test_structured_preference_parser(self):
        expected = SearchPreferences(
            max_price_sgd=1_300,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
            ranking_priority="mrt",
        )
        structured_model = Mock()
        structured_model.invoke.return_value = expected
        model = Mock()
        model.with_structured_output.return_value = structured_model

        result = parse_preferences(
            "预算1300，D05的common room，地铁10分钟内，只看认证房源，MTR近一点",
            model,
        )

        self.assertEqual(result, expected)
        model.with_structured_output.assert_called_once_with(SearchPreferences)
        messages = structured_model.invoke.call_args.args[0]
        self.assertEqual(messages[-1][0], "human")

        with self.assertRaises(ValueError):
            parse_preferences("   ", model)


if __name__ == "__main__":
    unittest.main()
