import os
import unittest
from unittest.mock import patch

import config


class ConfigTest(unittest.TestCase):
    def test_env_falls_back_to_dotenv(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "_dotenv", return_value={"EXAMPLE": "from-file"}),
        ):
            self.assertEqual(config.env("EXAMPLE"), "from-file")


if __name__ == "__main__":
    unittest.main()
