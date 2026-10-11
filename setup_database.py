"""Make or update the project's PostgreSQL in one go; safe to run again.

    python setup_database.py

Uses DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD from .env, in this order:

1. creates the database DB_NAME if the server does not have it;
2. runs the pipeline's table scripts in src/dss5105/database that it has not run yet;
3. load_data.py: V1 listings, districts, availability and review flags (rental_data_v1.json);
4. sync_v2.py: V2 listings and enrichment (rental_data_v2.csv), and marks removed_listings.csv;
5. build_commutes.py --import: the faculties and commute_faculty.csv;
6. the backend's link-check tables and the agent_listings view, as server.py does at start.

Steps 3-5 insert or update the listings in the files, and nothing else: accounts, conversations and
link checks in the agent schema are kept. A listing that a newer V2 file leaves out stays active
unless removed_listings.csv names it; the script reports such listings. The data files in
output-final-delivery are shared in the group, not in Git.
"""

import csv
import sys
from contextlib import closing
from pathlib import Path

import psycopg

from build_commutes import COMMUTE_DATA, import_commutes
from config import postgres_settings
from group_db import connect, ensure_database, open_database

ROOT = Path(__file__).parent
SCRIPT_FOLDER = ROOT / "src" / "dss5105" / "database"
DATA_FILES = [ROOT / "output-final-delivery" / name for name in ("rental_data_v1.json", "rental_data_v2.csv", "removed_listings.csv")]
_HAS_TABLE = "SELECT to_regclass(%s) IS NOT NULL"
_HAS_COLUMN = "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s AND column_name = %s)"
# The pipeline's table scripts in the order they must run, each with what shows it has run.
TABLE_SCRIPTS = (
    ("schema.sql", _HAS_TABLE, ("public.listings",)),
    ("migration_v2.sql", _HAS_TABLE, ("public.listing_enrichment",)),
    ("migration_nus_destinations.sql", _HAS_TABLE, ("public.nus_destinations",)),
    ("migration_listing_commutes.sql", _HAS_TABLE, ("public.listing_commutes",)),
    ("migration_commute_benchmark.sql", _HAS_COLUMN, ("listing_commutes", "benchmark_date")),
    ("migration_lease_term.sql", _HAS_COLUMN, ("listings", "lease_term")),
)


def run_table_scripts(pg) -> list[str]:
    """Run the table scripts this database has not run yet; returns their names."""
    ran = []
    for script, check, params in TABLE_SCRIPTS:
        if not pg.execute(check, params).fetchone()[0]:
            with pg.transaction():
                pg.execute((SCRIPT_FOLDER / script).read_text(encoding="utf-8"))
            ran.append(script)
    return ran


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    name = postgres_settings()["dbname"]
    if not name:
        raise SystemExit("在 .env 里填上 DB_HOST、DB_PORT、DB_NAME、DB_USER、DB_PASSWORD（见 .env.example）。")
    missing = [path.name for path in DATA_FILES if not path.exists()]
    if missing:
        raise SystemExit(f"output-final-delivery 里缺少 {', '.join(missing)}：这些是组里共享的最终数据（不在 Git 里），放进去再运行。")
    try:
        if ensure_database(name):
            print(f"已新建数据库 {name}。")
    except psycopg.Error as error:
        raise SystemExit(
            f"连不上 PostgreSQL 或建不了数据库 {name}：{error}\n"
            "检查 PostgreSQL 服务是否在运行、.env 里的连接设置，以及这个账号能否建库（也可以先在 pgAdmin 里手动建好）。"
        ) from error

    # The pipeline's own scripts, connecting the way the backend does.
    sys.path.insert(0, str(ROOT / "src"))
    from dss5105.data import load_data, sync_v2

    try:
        with closing(connect("public")) as pg:
            ran = run_table_scripts(pg)
        print(f"建表：运行了 {', '.join(ran)}。" if ran else "建表：表都已存在。")
        for script, module in (("load_data.py（V1）", load_data), ("sync_v2.py（V2）", sync_v2)):
            print(f"\n== {script} ==")
            module.get_connection = lambda: connect("public", autocommit=False)
            module.main()
        with closing(connect("public")) as pg:
            print(f"\n通勤：已把 {COMMUTE_DATA.name} 的 {import_commutes(pg)} 行写入数据库。")
            # Statistics for the new data, so searches get good query plans right away.
            pg.execute("ANALYZE")
            active = {listing_id for (listing_id,) in pg.execute("SELECT listing_id FROM listings WHERE scrape_status = 'active'")}
    except psycopg.Error as error:
        raise SystemExit(f"准备数据库时出错：{error}") from error
    with DATA_FILES[1].open(encoding="utf-8-sig", newline="") as file:
        older = active - {row["listing_id"] for row in csv.DictReader(file)}
    if older:
        print(
            f"\n注意：数据库里有 {len(older)} 套 active 房源不在 {DATA_FILES[1].name} 里，也不在 {DATA_FILES[2].name} 里，"
            "是以前的数据留下的，仍会被推荐。要去掉的话，在数据库里把它们的 scrape_status 改成 removed。"
        )

    with closing(open_database()) as database:
        counts = database.query(
            "SELECT count(*) AS listings, count(*) FILTER (WHERE commutes <> '{}'::jsonb) AS with_commutes FROM agent_listings"
        )[0]
    print(f"\n完成：{counts['listings']} 套可用房源，其中 {counts['with_commutes']} 套有通勤时间。现在可以运行 python server.py。")


if __name__ == "__main__":
    main()
