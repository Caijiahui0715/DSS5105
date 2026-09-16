from dss5105.database.connection import get_connection


def main():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user;")
            result = cur.fetchone()

            print("Database connection successful.")
            print("Database:", result[0])
            print("User:", result[1])


if __name__ == "__main__":
    main()