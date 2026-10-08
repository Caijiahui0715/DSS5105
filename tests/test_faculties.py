import re
import unittest

from faculties import FACULTIES, _key, find_faculty


class FacultiesTest(unittest.TestCase):
    def test_every_faculty_from_the_document_is_recorded_once(self):
        self.assertEqual(len(FACULTIES), 16)
        # No name or abbreviation can point at two places.
        owners = {}
        for faculty in FACULTIES:
            for key in {_key(name) for name in (faculty["name"], faculty["zh"], *faculty["aliases"])}:
                self.assertNotIn(key, owners, faculty["name"])
                owners[key] = faculty["name"]
        for faculty in FACULTIES:
            self.assertRegex(faculty["address"], r", Singapore \d{6}$")
            self.assertTrue(1.2 < faculty["latitude"] < 1.5 and 103.6 < faculty["longitude"] < 104.1, faculty["name"])

    def test_faculties_are_found_by_english_name_chinese_name_or_abbreviation(self):
        cases = {
            "School of Computing": "School of Computing",
            "NUS School of Computing": "School of Computing",
            "国大计算机学院": "School of Computing",
            " soc ": "School of Computing",
            "商学院": "NUS Business School",
            "新加坡国立大学法学院": "Faculty of Law",
            "Duke-NUS": "Duke-NUS Medical School",
            "NUS-ISS": "NUS Institute of Systems Science",
        }
        for place, name in cases.items():
            self.assertEqual(find_faculty(place)["name"], name, place)
        # Generic words and other places are left to OneMap.
        for place in ("学院", "NUS", "Clementi Mall"):
            self.assertIsNone(find_faculty(place), place)


if __name__ == "__main__":
    unittest.main()
