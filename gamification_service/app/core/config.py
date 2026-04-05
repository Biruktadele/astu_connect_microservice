from pydantic_settings import BaseSettings, SettingsConfigDict


LEVEL_THRESHOLDS = [
    (1, "Beginner", 0),
    (2, "Contributor", 50),
    (3, "Active", 200),
    (4, "Influencer", 500),
    (5, "Star Creator", 1500),
]

BADGE_DEFINITIONS = {
    "first_post":          {"label": "First Post",           "description": "Created your first post"},
    "prolific_poster":     {"label": "Prolific Poster",      "description": "Created 50 posts"},
    "commentator":         {"label": "Commentator",          "description": "Left 20 comments"},
    "top_commenter":       {"label": "Top Commenter",        "description": "Left 100 comments"},
    "popular":             {"label": "Popular",              "description": "Reached 100 followers"},
    "influencer":          {"label": "Influencer",           "description": "Reached 500 followers"},
    "community_joiner":    {"label": "Community Joiner",     "description": "Joined 5 communities"},
    "point_milestone_100": {"label": "Century",              "description": "Earned 100 points"},
    "point_milestone_1000":{"label": "Grand",                "description": "Earned 1000 points"},
}


class Settings(BaseSettings):
    PROJECT_NAME: str = "ASTU Connect Gamification Service"
    API_V1_STR: str = "/api/v1"

    GAMIFICATION_DATABASE_URL: str = "postgresql://gamification_user:gamification_pass@localhost:5436/gamification_db"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    FEED_REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"

    POINTS_POST: int = 10
    POINTS_COMMENT: int = 5
    POINTS_REACTION_RECEIVED: int = 2
    POINTS_FOLLOW: int = 3
    POINTS_GET_FOLLOWED: int = 5
    POINTS_JOIN_COMMUNITY: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def compute_level(total_points: int) -> tuple[int, str]:
    level_num, level_name = 1, "Beginner"
    for num, name, threshold in LEVEL_THRESHOLDS:
        if total_points >= threshold:
            level_num, level_name = num, name
    return level_num, level_name
