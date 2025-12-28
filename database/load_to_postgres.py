import json
from pathlib import Path

import pandas as pd
import psycopg2


def get_connection(
    host: str = "localhost",
    port: int = 5432,
    database: str = "places_db",
    user: str = "places_user",
    password: str = "places_password",
) -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=host, port=port, database=database, user=user, password=password
    )


def load_data_to_postgres(
    csv_file: str = "../data/places_cleaned.csv",
    host: str = "localhost",
    port: int = 5432,
    database: str = "places_db",
    user: str = "places_user",
    password: str = "places_password",
):
    # относительно database/
    script_dir = Path(__file__).parent
    csv_path = (
        script_dir / csv_file if not Path(csv_file).is_absolute() else Path(csv_file)
    )

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV файл не найден: {csv_path}")

    df = pd.read_csv(csv_path)
    print(f"Загружено {len(df)} записей")

    print(f"Подключение к PostgreSQL ({host}:{port}/{database})...")
    conn = get_connection(host, port, database, user, password)
    cursor = conn.cursor()

    try:
        print("Очистка существующих данных...")
        cursor.execute("DELETE FROM place_tags")
        cursor.execute("DELETE FROM tags")
        cursor.execute("DELETE FROM places")
        conn.commit()

        print("Загрузка мест в БД...")
        inserted_count = 0

        for _, row in df.iterrows():
            phone = row.get("phone") or row.get("mobile_phone")
            if pd.notna(phone):
                phone = str(phone).strip()
            else:
                phone = None

            lat = row.get("latitude")
            lon = row.get("longitude")

            if pd.notna(lat) and pd.notna(lon):
                cursor.execute(
                    """
                    INSERT INTO places (
                        id, name, city, district, address, rating, reviews_count, ratings_count,
                        working_hours, website, phone, location
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                    )
                """,
                    (
                        int(row["id"]),
                        row["name"],
                        row.get("city"),
                        row.get("district"),
                        row.get("address"),
                        float(row["rating"]) if pd.notna(row.get("rating")) else None,
                        (
                            int(row["reviews_count"])
                            if pd.notna(row.get("reviews_count"))
                            else None
                        ),
                        (
                            int(row["ratings_count"])
                            if pd.notna(row.get("ratings_count"))
                            else None
                        ),
                        row.get("working_hours"),
                        row.get("website"),
                        phone,
                        float(lon),
                        float(lat),
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO places (
                        id, name, city, district, address, rating, reviews_count, ratings_count,
                        working_hours, website, phone, location
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL
                    )
                """,
                    (
                        int(row["id"]),
                        row["name"],
                        row.get("city"),
                        row.get("district"),
                        row.get("address"),
                        float(row["rating"]) if pd.notna(row.get("rating")) else None,
                        (
                            int(row["reviews_count"])
                            if pd.notna(row.get("reviews_count"))
                            else None
                        ),
                        (
                            int(row["ratings_count"])
                            if pd.notna(row.get("ratings_count"))
                            else None
                        ),
                        row.get("working_hours"),
                        row.get("website"),
                        phone,
                    ),
                )

            inserted_count += 1

            if inserted_count % 100 == 0:
                conn.commit()

        conn.commit()
        print(f"Загружено {inserted_count} мест")

        print("Загрузка тегов и создание связей...")
        tag_map = {}  # словарь для маппинга имени тега к его ID

        for _, row in df.iterrows():
            place_id = int(row["id"])
            tags_json = row.get("tags_json")

            if pd.notna(tags_json) and tags_json:
                try:
                    for tag_name in json.loads(tags_json):
                        tag_name = tag_name.strip()
                        if not tag_name:
                            continue

                        if tag_name not in tag_map:
                            cursor.execute(
                                "INSERT INTO tags (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
                                (tag_name,),
                            )
                            result = cursor.fetchone()
                            if result:
                                tag_id = result[0]
                            else:
                                cursor.execute(
                                    "SELECT id FROM tags WHERE name = %s", (tag_name,)
                                )
                                tag_id = cursor.fetchone()[0]
                            tag_map[tag_name] = tag_id
                        else:
                            tag_id = tag_map[tag_name]

                        cursor.execute(
                            """
                            INSERT INTO place_tags (place_id, tag_id) 
                            VALUES (%s, %s)
                            ON CONFLICT (place_id, tag_id) DO NOTHING
                        """,
                            (place_id, tag_id),
                        )
                except json.JSONDecodeError:
                    print(f"Ошибка парсинга JSON для места ID {place_id}")

        conn.commit()
        print("Данные успешно загружены в БД!")

        cursor.execute("SELECT COUNT(*) FROM places")
        places_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM tags")
        tags_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM place_tags")
        links_count = cursor.fetchone()[0]

        print("\nСтатистика БД:")
        print(f"  Мест: {places_count}")
        print(f"  Тегов: {tags_count}")
        print(f"  Связей место-тег: {links_count}")

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при загрузке данных: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    import os
    import sys

    csv_file = sys.argv[1] if len(sys.argv) > 1 else "../data/places_cleaned.csv"
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", 5435))
    database = os.getenv("POSTGRES_DB", "places_db")
    user = os.getenv("POSTGRES_USER", "places_user")
    password = os.getenv("POSTGRES_PASSWORD", "places_password")

    load_data_to_postgres(csv_file, host, port, database, user, password)
