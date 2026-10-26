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
from config import missing_db_settings, postgres_settings
from group_db import connect, ensure_database, open_database

ROOT = Path(__file__).parent
SCRIPT_FOLDER = ROOT / "src" / "dss5105" / "database"
DATA_FILES = [ROOT / "output-final-delivery" / name for name in ("rental_data_v1.json", "rental_data_v2.csv", "removed_listings.csv")]
_HAS_TABLE = "SELECT to_regclass(%s) IS NOT NULL"
_HAS_COLUMN = "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s AND column_name = %s)"
_MRT_NULLABLE = "SELECT is_nullable = 'YES' FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s AND column_name = %s"
# The pipeline's table scripts in the order they must run, each with what shows it has run.
TABLE_SCRIPTS = (
    ("schema.sql", _HAS_TABLE, ("public.listings",)),
    ("migration_v2.sql", _HAS_TABLE, ("public.listing_enrichment",)),
    ("migration_nus_destinations.sql", _HAS_TABLE, ("public.nus_destinations",)),
    ("migration_listing_commutes.sql", _HAS_TABLE, ("public.listing_commutes",)),
    ("migration_commute_benchmark.sql", _HAS_COLUMN, ("listing_commutes", "benchmark_date")),
    ("migration_lease_term.sql", _HAS_COLUMN, ("listings", "lease_term")),
    ("migration_mrt_nullable.sql", _MRT_NULLABLE, ("listings", "mrt_station")),
    ("migration_photos.sql", _HAS_COLUMN, ("listings", "photos")),
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
    if problem := missing_db_settings():
        raise SystemExit(problem)
    name = postgres_settings()["dbname"]
    missing = [path.name for path in DATA_FILES if not path.exists()]
    if missing:
        raise SystemExit(f"output-final-delivery is missing {', '.join(missing)}: put the final data files there and run again.")
    try:
        if ensure_database(name):
            print(f"Created the database {name}.")
    except psycopg.Error as error:
        raise SystemExit(
            f"Cannot connect to PostgreSQL or create the database {name}: {error}\n"
            "Check that the PostgreSQL service is running, the connection settings in .env, and that DB_USER may create "
            "databases (or create it by hand in pgAdmin first)."
        ) from error

    # The pipeline's own scripts, connecting the way the backend does.
    sys.path.insert(0, str(ROOT / "src"))
    from dss5105.data import load_data, sync_v2

    try:
        with closing(connect("public")) as pg:
            ran = run_table_scripts(pg)
        print(f"Tables: ran {', '.join(ran)}." if ran else "Tables: all exist already.")
        for script, module in (("load_data.py (V1)", load_data), ("sync_v2.py (V2)", sync_v2)):
            print(f"\n== {script} ==")
            module.get_connection = lambda: connect("public", autocommit=False)
            module.main()
        with closing(connect("public")) as pg:
            print(f"\nCommutes: wrote {import_commutes(pg)} rows of {COMMUTE_DATA.name} to the database.")
            # Statistics for the new data, so searches get good query plans right away.
            pg.execute("ANALYZE")
            active = {listing_id for (listing_id,) in pg.execute("SELECT listing_id FROM listings WHERE scrape_status = 'active'")}
    except psycopg.Error as error:
        raise SystemExit(f"Preparing the database failed: {error}") from error
    with DATA_FILES[1].open(encoding="utf-8-sig", newline="") as file:
        older = active - {row["listing_id"] for row in csv.DictReader(file)}
    if older:
        print(
            f"\nNote: {len(older)} active listings in the database are in neither {DATA_FILES[1].name} nor {DATA_FILES[2].name}. "
            "They are left from earlier data and are still recommended; to drop them, set their scrape_status to removed in the database."
        )

    with closing(open_database()) as database:
        counts = database.query(
            "SELECT count(*) AS listings, count(*) FILTER (WHERE commutes <> '{}'::jsonb) AS with_commutes FROM agent_listings"
        )[0]
    print(f"\nDone: {counts['listings']} usable listings, {counts['with_commutes']} of them with commute times. You can now run python server.py.")


if __name__ == "__main__":
    main()
