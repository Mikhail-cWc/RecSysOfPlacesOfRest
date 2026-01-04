import logging
import os
import sys
from typing import Any

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


load_dotenv()


class EmbeddingGenerator:
    """
    Генератор embeddings для мест досуга.
    """

    def __init__(self):
        self.pg_conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DB", "places_db"),
            user=os.getenv("POSTGRES_USER", "places_user"),
            password=os.getenv("POSTGRES_PASSWORD", "places_password"),
        )

        self.openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

        self.qdrant_client = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"), port=int(os.getenv("QDRANT_PORT", "6333"))
        )

        self.collection_name = "places"
        self.embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-bge-m3")
        self.embedding_dim = os.getenv("OPENAI_EMBEDDING_DIM", 1024)

    def load_places(self) -> list[dict[str, Any]]:
        logger.info("Загрузка мест из PostgreSQL...")

        query = """
        SELECT 
            p.id,
            p.name,
            p.district,
            p.rating,
            p.reviews_count,
            p.address,
            COALESCE(pwt.tag_list, '') as tags
        FROM places p
        LEFT JOIN places_with_tags pwt ON p.id = pwt.id
        WHERE p.rating >= 4.0
        ORDER BY p.id;
        """

        with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query)
            places = cursor.fetchall()

        logger.info(f"Загружено {len(places)} мест")
        return [dict(place) for place in places]

    def create_description(self, place: dict[str, Any]) -> str:
        parts = [place["name"]]

        if place.get("tags"):
            parts.append(f"Категории: {place['tags']}")

        if place.get("district"):
            parts.append(f"Район: {place['district']}")

        if place.get("rating"):
            parts.append(f"Рейтинг: {place['rating']:.1f}")

        return ". ".join(parts)

    def create_embedding(self, text: str) -> list[float]:
        try:
            response = self.openai_client.embeddings.create(model=self.embedding_model, input=text)
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Ошибка создания embedding: {e}")
            raise

    def setup_qdrant_collection(self):
        try:
            self.qdrant_client.delete_collection(self.collection_name)
            logger.info(f"Удалена существующая коллекция {self.collection_name}")
        except Exception:
            pass

        self.qdrant_client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
        )
        logger.info(f"Создана коллекция {self.collection_name}")

    def upload_to_qdrant(
        self,
        places: list[dict[str, Any]],
        use_llm_descriptions: bool = False,
        batch_size: int = 100,
    ):
        logger.info("Генерация embeddings и загрузка в Qdrant...")

        points = []

        for place in tqdm(places, desc="Обработка мест"):
            try:
                description = self.create_description(place)

                vector = self.create_embedding(description)

                payload = {
                    "name": place["name"],
                    "description": description,
                    "tags": place.get("tags", ""),
                    "district": place.get("district", ""),
                    "rating": float(place.get("rating", 0)),
                    "reviews_count": int(place.get("reviews_count", 0)),
                }

                point = PointStruct(id=int(place["id"]), vector=vector, payload=payload)
                points.append(point)

                if len(points) >= batch_size:
                    self.qdrant_client.upsert(collection_name=self.collection_name, points=points)
                    points = []

            except Exception as e:
                logger.error(f"Ошибка обработки {place['name']}: {e}")
                continue

        if points:
            self.qdrant_client.upsert(collection_name=self.collection_name, points=points)

        logger.info("Загрузка в Qdrant завершена")

    def verify_collection(self):
        collection_info = self.qdrant_client.get_collection(self.collection_name)
        logger.info(f"Количество векторов в коллекции: {collection_info.points_count}")

        test_query = "уютное кафе с книгами"
        test_vector = self.create_embedding(test_query)

        results = self.qdrant_client.search(
            collection_name=self.collection_name, query_vector=test_vector, limit=5
        )

        logger.info(f"\nТестовый поиск: '{test_query}'")
        logger.info("Топ-5 результатов:")
        for i, result in enumerate(results, 1):
            logger.info(f"{i}. {result.payload['name']} (score: {result.score:.3f})")

    def run(self):
        try:
            places = self.load_places()

            if not places:
                logger.error("Нет мест для обработки")
                return

            self.setup_qdrant_collection()
            self.upload_to_qdrant(places)
            self.verify_collection()

            logger.info("Генерация embeddings завершена успешно")

        except Exception as e:
            logger.error(f"Ошибка: {e}", exc_info=True)
            raise
        finally:
            self.pg_conn.close()


def main():
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("Не установлен OPENAI_API_KEY")
        sys.exit(1)

    generator = EmbeddingGenerator()
    generator.run()


if __name__ == "__main__":
    main()
