from typing import Optional
from sqlalchemy.orm import Session
import json, uuid
from datetime import datetime

from ..domain.entities import Community, Membership, CommunityPost
from ..domain.repositories import (
    CommunityRepository, MembershipRepository,
    CommunityPostRepository, EventPublisher,
)
from .models import CommunityModel, MembershipModel, CommunityPostModel, OutboxModel


def _to_community(m):
    return Community(id=m.id, name=m.name, slug=m.slug, description=m.description,
                     avatar_url=m.avatar_url, visibility=m.visibility, owner_id=m.owner_id,
                     member_count=m.member_count, is_archived=m.is_archived, created_at=m.created_at)


class PgCommunityRepository(CommunityRepository):
    def __init__(self, db: Session): self.db = db

    def save(self, c):
        m = CommunityModel(id=c.id, name=c.name, slug=c.slug, description=c.description,
                           avatar_url=c.avatar_url, visibility=c.visibility, owner_id=c.owner_id,
                           member_count=c.member_count)
        self.db.add(m); self.db.flush(); return _to_community(m)

    def find_by_id(self, cid):
        m = self.db.query(CommunityModel).filter(CommunityModel.id == cid).first()
        return _to_community(m) if m else None

    def find_by_slug(self, slug):
        m = self.db.query(CommunityModel).filter(CommunityModel.slug == slug).first()
        return _to_community(m) if m else None

    def search(self, q, limit=20, offset=0):
        rows = self.db.query(CommunityModel).filter(
            CommunityModel.name.ilike(f"%{q}%"), CommunityModel.is_archived == False
        ).limit(limit).offset(offset).all()
        return [_to_community(r) for r in rows]

    def list_all(self, limit=20, offset=0):
        rows = self.db.query(CommunityModel).filter(
            CommunityModel.is_archived == False
        ).order_by(CommunityModel.created_at.desc()).limit(limit).offset(offset).all()
        return [_to_community(r) for r in rows]

    def update(self, c):
        m = self.db.query(CommunityModel).filter(CommunityModel.id == c.id).first()
        if not m: raise ValueError("Not found")
        m.name, m.description, m.avatar_url, m.visibility = c.name, c.description, c.avatar_url, c.visibility
        self.db.flush(); return _to_community(m)

    def increment_member_count(self, cid, delta):
        self.db.query(CommunityModel).filter(CommunityModel.id == cid).update(
            {CommunityModel.member_count: CommunityModel.member_count + delta})
        self.db.flush()


class PgMembershipRepository(MembershipRepository):
    def __init__(self, db: Session): self.db = db

    def save(self, m):
        self.db.add(MembershipModel(id=m.id, community_id=m.community_id, user_id=m.user_id, role=m.role))
        self.db.flush(); return m

    def find(self, cid, uid):
        m = self.db.query(MembershipModel).filter(
            MembershipModel.community_id == cid, MembershipModel.user_id == uid).first()
        return Membership(id=m.id, community_id=m.community_id, user_id=m.user_id,
                          role=m.role, joined_at=m.joined_at) if m else None

    def delete(self, cid, uid):
        m = self.db.query(MembershipModel).filter(
            MembershipModel.community_id == cid, MembershipModel.user_id == uid).first()
        if m: self.db.delete(m); self.db.flush(); return True
        return False

    def get_members(self, cid, limit=50, offset=0):
        rows = self.db.query(MembershipModel).filter(MembershipModel.community_id == cid
                                                      ).order_by(MembershipModel.joined_at).limit(limit).offset(offset).all()
        return [Membership(id=r.id, community_id=r.community_id, user_id=r.user_id,
                           role=r.role, joined_at=r.joined_at) for r in rows]

    def get_user_communities(self, uid):
        return [r[0] for r in self.db.query(MembershipModel.community_id
                                             ).filter(MembershipModel.user_id == uid).all()]

    def update_role(self, cid, uid, role):
        m = self.db.query(MembershipModel).filter(
            MembershipModel.community_id == cid, MembershipModel.user_id == uid).first()
        if m: m.role = role; self.db.flush(); return True
        return False


class PgCommunityPostRepository(CommunityPostRepository):
    def __init__(self, db: Session): self.db = db

    def save(self, p):
        self.db.add(CommunityPostModel(id=p.id, community_id=p.community_id,
                                        author_id=p.author_id, title=p.title, body=p.body))
        self.db.flush(); return p

    def find_by_id(self, pid):
        m = self.db.query(CommunityPostModel).filter(
            CommunityPostModel.id == pid, CommunityPostModel.is_deleted == False).first()
        return CommunityPost(id=m.id, community_id=m.community_id, author_id=m.author_id,
                             title=m.title, body=m.body, is_pinned=m.is_pinned,
                             created_at=m.created_at) if m else None

    def find_by_community(self, cid, limit=30, offset=0):
        rows = self.db.query(CommunityPostModel).filter(
            CommunityPostModel.community_id == cid, CommunityPostModel.is_deleted == False
        ).order_by(CommunityPostModel.is_pinned.desc(), CommunityPostModel.created_at.desc()
                   ).limit(limit).offset(offset).all()
        return [CommunityPost(id=r.id, community_id=r.community_id, author_id=r.author_id,
                              title=r.title, body=r.body, is_pinned=r.is_pinned,
                              created_at=r.created_at) for r in rows]

    def soft_delete(self, pid):
        m = self.db.query(CommunityPostModel).filter(CommunityPostModel.id == pid).first()
        if m: m.is_deleted = True; self.db.flush(); return True
        return False

    def pin(self, pid, pinned):
        m = self.db.query(CommunityPostModel).filter(CommunityPostModel.id == pid).first()
        if m: m.is_pinned = pinned; self.db.flush(); return True
        return False


class OutboxEventPublisher(EventPublisher):
    def __init__(self, db: Session): self.db = db

    def publish(self, event_type, topic, key, payload):
        self.db.add(OutboxModel(id=str(uuid.uuid4()), event_type=event_type, topic=topic,
                                partition_key=key, payload=json.dumps(payload)))
        self.db.flush()
