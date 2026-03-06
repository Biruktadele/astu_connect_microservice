from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.repositories import (
    PgCommunityRepository, PgMembershipRepository, PgCommunityPostRepository, OutboxEventPublisher,
)
from ....application.use_cases import (
    CreateCommunityUseCase, JoinCommunityUseCase, LeaveCommunityUseCase,
    SetMemberRoleUseCase, CreateCommunityPostUseCase, ModeratePostUseCase,
)
from ....application.dto import (
    CreateCommunityDTO, UpdateCommunityDTO, CommunityResponse,
    MembershipResponse, CreateCommunityPostDTO, CommunityPostResponse, SetRoleDTO,
)
from ..deps import get_current_user_id

router = APIRouter(prefix="/communities", tags=["communities"])


def _enrich(community, membership_repo, user_id):
    mem = membership_repo.find(community.id, user_id) if user_id else None
    return CommunityResponse(
        **community.__dict__, is_member=mem is not None,
        my_role=mem.role if mem else None,
    )


@router.get("", response_model=list[CommunityResponse])
def list_communities(
    q: str = "", limit: int = 20, offset: int = 0,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = PgCommunityRepository(db)
    m_repo = PgMembershipRepository(db)
    if q:
        communities = repo.search(q, limit, offset)
    else:
        communities = repo.list_all(limit, offset)
    return [_enrich(c, m_repo, user_id) for c in communities]


@router.post("", response_model=CommunityResponse, status_code=201)
def create_community(
    dto: CreateCommunityDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = CreateCommunityUseCase(PgCommunityRepository(db), PgMembershipRepository(db), OutboxEventPublisher(db))
    try:
        community = uc.execute(user_id, dto.name, dto.slug, dto.description, dto.visibility, dto.avatar_url)
        db.commit()
        return CommunityResponse(**community.__dict__, is_member=True, my_role="owner")
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{community_id}", response_model=CommunityResponse)
def get_community(community_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    repo = PgCommunityRepository(db)
    community = repo.find_by_id(community_id)
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")
    return _enrich(community, PgMembershipRepository(db), user_id)


@router.patch("/{community_id}", response_model=CommunityResponse)
def update_community(
    community_id: str, dto: UpdateCommunityDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = PgCommunityRepository(db)
    m_repo = PgMembershipRepository(db)
    membership = m_repo.find(community_id, user_id)
    if not membership or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")

    community = repo.find_by_id(community_id)
    for k, v in dto.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(community, k, v)
    updated = repo.update(community)
    db.commit()
    return _enrich(updated, m_repo, user_id)


@router.post("/{community_id}/join", status_code=201)
def join_community(community_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    uc = JoinCommunityUseCase(PgCommunityRepository(db), PgMembershipRepository(db), OutboxEventPublisher(db))
    try:
        uc.execute(community_id, user_id)
        db.commit()
        return {"status": "joined"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{community_id}/leave", status_code=204)
def leave_community(community_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    uc = LeaveCommunityUseCase(PgCommunityRepository(db), PgMembershipRepository(db), OutboxEventPublisher(db))
    try:
        uc.execute(community_id, user_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{community_id}/members", response_model=list[MembershipResponse])
def list_members(community_id: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    members = PgMembershipRepository(db).get_members(community_id, limit, offset)
    return [MembershipResponse(user_id=m.user_id, role=m.role, joined_at=m.joined_at) for m in members]


@router.put("/{community_id}/members/{target_id}/role")
def set_member_role(
    community_id: str, target_id: str, dto: SetRoleDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = SetMemberRoleUseCase(PgMembershipRepository(db))
    try:
        uc.execute(community_id, user_id, target_id, dto.role)
        db.commit()
        return {"status": "role_updated"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ── Community Posts ──

@router.get("/{community_id}/posts", response_model=list[CommunityPostResponse])
def list_posts(community_id: str, limit: int = 30, offset: int = 0, db: Session = Depends(get_db)):
    posts = PgCommunityPostRepository(db).find_by_community(community_id, limit, offset)
    return [CommunityPostResponse(**p.__dict__) for p in posts]


@router.post("/{community_id}/posts", response_model=CommunityPostResponse, status_code=201)
def create_post(
    community_id: str, dto: CreateCommunityPostDTO,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = CreateCommunityPostUseCase(PgCommunityPostRepository(db), PgMembershipRepository(db), OutboxEventPublisher(db))
    try:
        post = uc.execute(community_id, user_id, dto.title, dto.body)
        db.commit()
        return CommunityPostResponse(**post.__dict__)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{community_id}/posts/{post_id}", status_code=204)
def delete_post(
    community_id: str, post_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = ModeratePostUseCase(PgCommunityPostRepository(db), PgMembershipRepository(db))
    try:
        uc.delete_post(community_id, post_id, user_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{community_id}/posts/{post_id}/pin")
def toggle_pin(
    community_id: str, post_id: str, pinned: bool = True,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uc = ModeratePostUseCase(PgCommunityPostRepository(db), PgMembershipRepository(db))
    try:
        uc.pin_post(community_id, post_id, user_id, pinned)
        db.commit()
        return {"status": "pinned" if pinned else "unpinned"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
