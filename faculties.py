"""NUS faculties and schools, from facultyaddress.docx, so the agent can locate them by name.

Coordinates are OneMap's for each address, looked up on 2026-10-06. Several NUS buildings share
one postcode (ten use 21 Lower Kent Ridge Road, 119077), so where OneMap lists more than one
building the coordinates are the named building's. Recorded places need no OneMap lookup, which
also avoids its "more than one place matches" refusal for names such as School of Computing.
"""

import re

FACULTIES = (
    {
        "name": "NUS Business School",
        "building": "Mochtar Riady Building (BIZ1)",
        "address": "15 Kent Ridge Drive, Singapore 119245",
        "campus": "Kent Ridge",
        "latitude": 1.292522,
        "longitude": 103.774133,
        "zh": "商学院",
        "aliases": ("BIZ",),
    },
    {
        "name": "School of Computing",
        "building": "Computing 1 (COM1)",
        "address": "13 Computing Drive, Singapore 117417",
        "campus": "Kent Ridge",
        "latitude": 1.294990,
        "longitude": 103.773912,
        "zh": "计算机学院",
        "aliases": ("电脑学院", "Computing", "SoC", "COM1"),
    },
    {
        "name": "College of Design and Engineering",
        # OneMap's point for 117575 is LT7A at the same address.
        "building": "Engineering Block EA",
        "address": "9 Engineering Drive 1, Singapore 117575",
        "campus": "Kent Ridge",
        "latitude": 1.299549,
        "longitude": 103.770669,
        "zh": "设计与工程学院",
        "aliases": ("工程学院", "CDE", "Engineering", "Faculty of Engineering"),
    },
    {
        "name": "Faculty of Arts and Social Sciences",
        "building": "Shaw Foundation Building (AS7)",
        "address": "5 Arts Link, Singapore 117570",
        "campus": "Kent Ridge",
        "latitude": 1.294491,
        "longitude": 103.770991,
        "zh": "人文与社会科学院",
        "aliases": ("文学暨社会科学院", "文学院", "FASS", "Arts and Social Sciences"),
    },
    {
        "name": "Faculty of Science",
        "building": "Block S16",
        "address": "6 Science Drive 2, Singapore 117546",
        "campus": "Kent Ridge",
        "latitude": 1.296366,
        "longitude": 103.779677,
        "zh": "理学院",
        "aliases": ("Science", "FoS"),
    },
    {
        "name": "Yong Loo Lin School of Medicine",
        "building": "NUS Medicine (MD11)",
        "address": "10 Medical Drive, Singapore 117597",
        "campus": "Kent Ridge / NUH",
        "latitude": 1.295989,
        "longitude": 103.781784,
        "zh": "杨潞龄医学院",
        "aliases": ("医学院", "Medicine", "School of Medicine"),
    },
    {
        "name": "Faculty of Dentistry",
        "building": "National University Centre for Oral Health Singapore",
        "address": "9 Lower Kent Ridge Road, Singapore 119085",
        "campus": "Kent Ridge / NUH",
        "latitude": 1.295843,
        "longitude": 103.783325,
        "zh": "牙医学院",
        "aliases": ("牙科学院", "Dentistry"),
    },
    {
        "name": "Saw Swee Hock School of Public Health",
        "building": "Tahir Foundation Building (MD1)",
        # The document suggests 12 Service Drive 2; OneMap records 117549 as 12 Science Drive 2.
        "address": "12 Science Drive 2, Singapore 117549",
        "campus": "Kent Ridge / NUH",
        "latitude": 1.295387,
        "longitude": 103.780510,
        "zh": "苏瑞福公共卫生学院",
        "aliases": ("公共卫生学院", "Public Health", "SSHSPH"),
    },
    {
        "name": "Yong Siew Toh Conservatory of Music",
        "building": "YST Conservatory",
        "address": "3 Conservatory Drive, Singapore 117376",
        "campus": "Kent Ridge",
        "latitude": 1.302172,
        "longitude": 103.772947,
        "zh": "杨秀桃音乐学院",
        "aliases": ("音乐学院", "Conservatory", "YST"),
    },
    {
        "name": "Faculty of Law",
        # As the document gives it; OneMap names this postcode NUS College, about 100 m away.
        "building": "New NUS Law campus",
        "address": "20 College Avenue West, Singapore 138529",
        "campus": "University Town",
        "latitude": 1.307057,
        "longitude": 103.772530,
        "zh": "法学院",
        "aliases": ("Law",),
    },
    {
        "name": "Lee Kuan Yew School of Public Policy",
        "building": "Oei Tiong Ham Building",
        "address": "469C Bukit Timah Road, Singapore 259772",
        "campus": "Bukit Timah",
        "latitude": 1.319340,
        "longitude": 103.817997,
        "zh": "李光耀公共政策学院",
        "aliases": ("公共政策学院", "LKYSPP", "LKY School"),
    },
    {
        "name": "Duke-NUS Medical School",
        "building": "Duke-NUS Medical School",
        "address": "8 College Road, Singapore 169857",
        "campus": "Outram",
        "latitude": 1.281218,
        "longitude": 103.834145,
        "zh": "杜克-国大医学研究生院",
        "aliases": ("杜克国大医学院", "杜克国大", "Duke-NUS"),
    },
    {
        "name": "NUS College",
        "building": "NUS College",
        "address": "16 College Avenue West, Singapore 138527",
        "campus": "University Town",
        "latitude": 1.306423,
        "longitude": 103.771795,
        "zh": "NUS College",
        "aliases": (),
    },
    {
        "name": "NUS Graduate School",
        "building": "University Hall, Tan Chin Tuan Wing",
        "address": "21 Lower Kent Ridge Road, Singapore 119077",
        "campus": "Kent Ridge",
        "latitude": 1.297142,
        "longitude": 103.777544,
        "zh": "研究生院",
        "aliases": ("ISEP",),
    },
    {
        "name": "School of Continuing and Lifelong Education",
        "building": "AS8",
        "address": "10 Kent Ridge Crescent, Singapore 119260",
        "campus": "Kent Ridge",
        "latitude": 1.296087,
        "longitude": 103.772348,
        "zh": "继续与终身教育学院",
        "aliases": ("SCALE",),
    },
    {
        "name": "NUS Institute of Systems Science",
        "building": "NUS-ISS",
        "address": "25 Heng Mui Keng Terrace, Singapore 119615",
        "campus": "Kent Ridge",
        "latitude": 1.292149,
        "longitude": 103.776551,
        "zh": "系统科学院",
        "aliases": ("ISS",),
    },
)


def _key(text: str) -> str:
    # NUS School of Computing, 国大计算机学院 and school of computing name the same place, so an
    # alias needs no NUS / 国大 prefix of its own.
    text = re.sub(r"[\s\-–—_.,·()（）]", "", text.casefold())
    return re.sub(r"^(nationaluniversityofsingapore|新加坡国立大学|国大|nus)", "", text) or text


_BY_NAME = {
    _key(name): faculty for faculty in FACULTIES for name in (faculty["name"], faculty["zh"], *faculty["aliases"])
}


def find_faculty(place: str) -> dict | None:
    """The faculty a place name refers to: its English name, Chinese name or abbreviation."""
    return _BY_NAME.get(_key(place))


def faculty_label(name: str | None, language: str = "zh") -> str:
    """How replies name a recorded faculty: its Chinese name in Chinese replies."""
    faculty = find_faculty(name or "")
    return (faculty["zh"] if language == "zh" else faculty["name"]) if faculty else name or ""
