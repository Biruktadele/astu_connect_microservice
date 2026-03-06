from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from ....infrastructure.elasticsearch_client import get_es_client
from ..deps import get_current_user_id

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    id: str
    type: str
    score: float
    data: dict


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    es = get_es_client()
    indices = []
    if type in ("user", "users"):
        indices = ["users"]
    elif type in ("post", "posts"):
        indices = ["posts"]
    elif type in ("community", "communities"):
        indices = ["communities"]
    else:
        indices = ["users", "posts", "communities"]

    body = {
        "query": {
            "multi_match": {
                "query": q,
                "fields": ["username^3", "display_name^2", "body", "name^3", "description", "department"],
                "type": "best_fields",
                "fuzziness": "AUTO",
            }
        },
        "from": offset,
        "size": limit,
    }

    resp = es.search(index=",".join(indices), body=body)
    hits = resp.get("hits", {})
    total = hits.get("total", {}).get("value", 0)

    results = []
    for hit in hits.get("hits", []):
        idx = hit["_index"]
        if idx == "users":
            result_type = "user"
        elif idx == "posts":
            result_type = "post"
        else:
            result_type = "community"

        results.append(SearchResult(
            id=hit["_id"],
            type=result_type,
            score=hit["_score"],
            data=hit["_source"],
        ))

    return SearchResponse(results=results, total=total)


@router.get("/users", response_model=SearchResponse)
def search_users(q: str = Query(..., min_length=1), limit: int = 20, user_id: str = Depends(get_current_user_id)):
    return search(q=q, type="users", limit=limit, user_id=user_id)


@router.get("/posts", response_model=SearchResponse)
def search_posts(q: str = Query(..., min_length=1), limit: int = 20, user_id: str = Depends(get_current_user_id)):
    return search(q=q, type="posts", limit=limit, user_id=user_id)


@router.get("/communities", response_model=SearchResponse)
def search_communities(q: str = Query(..., min_length=1), limit: int = 20, user_id: str = Depends(get_current_user_id)):
    return search(q=q, type="communities", limit=limit, user_id=user_id)
