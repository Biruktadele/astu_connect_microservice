import logging
import time
from elasticsearch import Elasticsearch
from ..core.config import settings

logger = logging.getLogger(__name__)
_client = None

INDEX_MAPPINGS = {
    "users": {
        "properties": {
            "user_id": {"type": "keyword"},
            "username": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "display_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "department": {"type": "keyword"},
            "email": {"type": "keyword"},
            "avatar_url": {"type": "keyword", "index": False},
            "created_at": {"type": "date"},
        }
    },
    "posts": {
        "properties": {
            "post_id": {"type": "keyword"},
            "author_id": {"type": "keyword"},
            "community_id": {"type": "keyword"},
            "body": {"type": "text"},
            "has_media": {"type": "boolean"},
            "created_at": {"type": "date"},
        }
    },
    "communities": {
        "properties": {
            "community_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "description": {"type": "text"},
            "owner_id": {"type": "keyword"},
            "visibility": {"type": "keyword"},
        }
    },
}


def get_es_client() -> Elasticsearch:
    global _client
    if _client is None:
        _client = Elasticsearch(settings.ELASTICSEARCH_URL)
        for idx_name, mappings in INDEX_MAPPINGS.items():
            try:
                if not _client.indices.exists(index=idx_name):
                    _client.indices.create(index=idx_name, mappings=mappings)
                    logger.info("Created ES index: %s", idx_name)
            except Exception as e:
                logger.warning("Could not create index %s: %s", idx_name, e)
    return _client


def ensure_connected(max_retries: int = 30, delay: float = 2.0) -> Elasticsearch:
    """Wait for Elasticsearch to be reachable, then return client and ensure indices."""
    for attempt in range(max_retries):
        try:
            client = get_es_client()
            client.info()
            return client
        except Exception as e:
            logger.warning("Elasticsearch not ready (attempt %s/%s): %s", attempt + 1, max_retries, e)
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
    raise RuntimeError("Elasticsearch unavailable after retries")
