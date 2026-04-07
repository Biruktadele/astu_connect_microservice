from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.repositories import (
    PgPostRepository, PgCommentRepository, PgReactionRepository,
    RedisTimelineRepository, PgAuthorSnapshotRepository, OutboxEventPublisher,
)
from ....application.use_cases import (
    CreatePostUseCase, DeletePostUseCase, CreateCommentUseCase,
    ReactToPostUseCase, FetchTimelineUseCase,
)
from ....application.dto import (
    CreatePostDTO, PostResponse, CreateCommentDTO, CommentResponse,
    SetReactionDTO, TimelineResponse,
)
from ..deps import get_current_user_id, get_optional_user_id

router = APIRouter(tags=["feed"])


@router.get("/feed/timeline", response_model=TimelineResponse)
def get_timeline(
    limit: int = 30, offset: int = 0,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = FetchTimelineUseCase(
        RedisTimelineRepository(), PgPostRepository(db),
        PgAuthorSnapshotRepository(db), PgReactionRepository(db),
    )
    posts = uc.execute(user_id, offset, limit, requester_id=user_id)
    return TimelineResponse(
        posts=[PostResponse(**p) for p in posts],
        next_cursor=str(offset + limit) if len(posts) == limit else None,
    )


@router.post("/feed/posts", response_model=PostResponse, status_code=201)
def create_post(
    dto: CreatePostDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = CreatePostUseCase(PgPostRepository(db), OutboxEventPublisher(db))
    post = uc.execute(user_id, dto.body, dto.media_refs, dto.community_id)
    db.commit()
    return PostResponse(**post.__dict__, author_name="", author_avatar="")


@router.get("/feed/posts/{post_id}", response_model=PostResponse)
def get_post(
    post_id: str,
    viewer: str = Depends(get_optional_user_id),
    db: Session = Depends(get_db),
):
    repo = PgPostRepository(db)
    post = repo.find_by_id(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    snap = PgAuthorSnapshotRepository(db).get(post.author_id)
    my_reaction = PgReactionRepository(db).get_user_reaction(post_id, viewer) if viewer else None
    return PostResponse(
        **post.__dict__,
        author_name=snap.display_name if snap else "",
        author_avatar=snap.avatar_url if snap else "",
        my_reaction=my_reaction,
    )


@router.delete("/feed/posts/{post_id}", status_code=204)
def delete_post(
    post_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = DeletePostUseCase(PgPostRepository(db), OutboxEventPublisher(db))
    try:
        uc.execute(post_id, user_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/feed/posts/{post_id}/comments", response_model=list[CommentResponse])
def get_comments(post_id: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    comments = PgCommentRepository(db).find_by_post(post_id, limit, offset)
    snapshots = PgAuthorSnapshotRepository(db).get_batch([c.author_id for c in comments])
    return [
        CommentResponse(
            **c.__dict__,
            author_name=snapshots.get(c.author_id, None) and snapshots[c.author_id].display_name or "",
            author_avatar=snapshots.get(c.author_id, None) and snapshots[c.author_id].avatar_url or ""
        )
        for c in comments
    ]


@router.post("/feed/posts/{post_id}/comments", response_model=CommentResponse, status_code=201)
def create_comment(
    post_id: str, dto: CreateCommentDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = CreateCommentUseCase(PgCommentRepository(db), PgPostRepository(db), OutboxEventPublisher(db))
    try:
        comment = uc.execute(post_id, user_id, dto.body)
        db.commit()
        return CommentResponse(**comment.__dict__, author_name="", author_avatar="")
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/feed/posts/{post_id}/reactions")
def set_reaction(
    post_id: str, dto: SetReactionDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = ReactToPostUseCase(PgReactionRepository(db), PgPostRepository(db), OutboxEventPublisher(db))
    try:
        counts = uc.execute(post_id, user_id, dto.type)
        db.commit()
        return {"post_id": post_id, "reaction_counts": counts}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/feed/posts/{post_id}/reactions", status_code=204)
def remove_reaction(
    post_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    PgReactionRepository(db).delete(post_id, user_id)
    counts = PgReactionRepository(db).get_counts(post_id)
    PgPostRepository(db).update_reaction_counts(post_id, counts)
    db.commit()


@router.get("/feed/users/{author_id}/posts", response_model=list[PostResponse])
def get_user_posts(author_id: str, limit: int = 30, offset: int = 0, db: Session = Depends(get_db)):
    posts = PgPostRepository(db).find_by_author(author_id, limit, offset)
    snapshots = PgAuthorSnapshotRepository(db).get_batch([author_id])
    snap = snapshots.get(author_id)
    return [
        PostResponse(**p.__dict__, author_name=snap.display_name if snap else "", author_avatar=snap.avatar_url if snap else "")
        for p in posts
    ]
