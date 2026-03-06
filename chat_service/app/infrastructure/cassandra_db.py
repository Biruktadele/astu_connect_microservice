"""Cassandra session management and schema creation."""

import logging
import time
from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy
from ..core.config import settings

logger = logging.getLogger(__name__)

_session = None


def get_cassandra_session():
    global _session
    if _session is not None:
        return _session

    hosts = settings.CHAT_CASSANDRA_HOSTS.split(",")
    cluster = Cluster(hosts, load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="datacenter1"))

    for attempt in range(15):
        try:
            raw = cluster.connect()
            raw.execute(f"""
                CREATE KEYSPACE IF NOT EXISTS {settings.CHAT_CASSANDRA_KEYSPACE}
                WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
            """)
            _session = cluster.connect(settings.CHAT_CASSANDRA_KEYSPACE)
            _create_tables(_session)
            logger.info("Connected to Cassandra")
            return _session
        except Exception:
            logger.warning("Cassandra not ready, retrying (%d/15)...", attempt + 1)
            time.sleep(3)

    raise RuntimeError("Failed to connect to Cassandra after 15 attempts")


def _create_tables(session):
    session.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id text PRIMARY KEY,
            type text,
            name text,
            participant_ids list<text>,
            created_at timestamp
        )
    """)
    session.execute("""
        CREATE TABLE IF NOT EXISTS user_conversations (
            user_id text,
            conversation_id text,
            joined_at timestamp,
            PRIMARY KEY (user_id, conversation_id)
        )
    """)
    session.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            conversation_id text,
            created_at timestamp,
            id text,
            sender_id text,
            body text,
            media_url text,
            client_msg_id text,
            PRIMARY KEY (conversation_id, created_at, id)
        ) WITH CLUSTERING ORDER BY (created_at DESC, id DESC)
    """)
    session.execute("""
        CREATE TABLE IF NOT EXISTS message_dedup (
            client_msg_id text PRIMARY KEY,
            message_id text
        )
    """)
