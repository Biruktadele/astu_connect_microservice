from ..domain.entities import Community, Membership, CommunityPost
from ..domain.repositories import (
    CommunityRepository, MembershipRepository, CommunityPostRepository, EventPublisher,
)


class CreateCommunityUseCase:
    def __init__(self, cr: CommunityRepository, mr: MembershipRepository, ep: EventPublisher):
        self.cr, self.mr, self.ep = cr, mr, ep

    def execute(self, owner_id, name, slug, description, visibility, avatar_url):
        if self.cr.find_by_slug(slug):
            raise ValueError("Slug already taken")
        c = Community(name=name, slug=slug, description=description,
                      avatar_url=avatar_url, visibility=visibility,
                      owner_id=owner_id, member_count=1)
        saved = self.cr.save(c)
        self.mr.save(Membership(community_id=saved.id, user_id=owner_id, role="owner"))
        self.ep.publish("community.created", "community.events", saved.id,
                        {"community_id": saved.id, "name": name, "owner_id": owner_id})
        return saved


class JoinCommunityUseCase:
    def __init__(self, cr: CommunityRepository, mr: MembershipRepository, ep: EventPublisher):
        self.cr, self.mr, self.ep = cr, mr, ep

    def execute(self, cid, uid):
        if not self.cr.find_by_id(cid):
            raise ValueError("Community not found")
        if self.mr.find(cid, uid):
            raise ValueError("Already a member")
        self.mr.save(Membership(community_id=cid, user_id=uid, role="member"))
        self.cr.increment_member_count(cid, 1)
        self.ep.publish("community.member.joined", "community.events", cid,
                        {"community_id": cid, "user_id": uid})


class LeaveCommunityUseCase:
    def __init__(self, cr: CommunityRepository, mr: MembershipRepository, ep: EventPublisher):
        self.cr, self.mr, self.ep = cr, mr, ep

    def execute(self, cid, uid):
        m = self.mr.find(cid, uid)
        if not m:
            raise ValueError("Not a member")
        if m.role == "owner":
            raise ValueError("Owner cannot leave")
        self.mr.delete(cid, uid)
        self.cr.increment_member_count(cid, -1)
        self.ep.publish("community.member.left", "community.events", cid,
                        {"community_id": cid, "user_id": uid})


class SetMemberRoleUseCase:
    def __init__(self, mr: MembershipRepository):
        self.mr = mr

    def execute(self, cid, requester_id, target_id, role):
        req = self.mr.find(cid, requester_id)
        if not req or req.role not in ("owner", "admin"):
            raise ValueError("Not authorized")
        if not self.mr.update_role(cid, target_id, role):
            raise ValueError("Target not a member")


class CreateCommunityPostUseCase:
    def __init__(self, pr: CommunityPostRepository, mr: MembershipRepository, ep: EventPublisher):
        self.pr, self.mr, self.ep = pr, mr, ep

    def execute(self, cid, author_id, title, body):
        if not self.mr.find(cid, author_id):
            raise ValueError("Not a member")
        p = CommunityPost(community_id=cid, author_id=author_id, title=title, body=body)
        saved = self.pr.save(p)
        self.ep.publish("community.post.created", "community.events", cid,
                        {"post_id": saved.id, "community_id": cid, "author_id": author_id,
                         "body_preview": body[:280], "created_at": saved.created_at.isoformat()})
        return saved


class ModeratePostUseCase:
    def __init__(self, pr: CommunityPostRepository, mr: MembershipRepository):
        self.pr, self.mr = pr, mr

    def delete_post(self, cid, pid, mod_id):
        m = self.mr.find(cid, mod_id)
        if not m or m.role not in ("owner", "admin", "moderator"):
            raise ValueError("Not authorized")
        if not self.pr.soft_delete(pid):
            raise ValueError("Post not found")

    def pin_post(self, cid, pid, mod_id, pinned):
        m = self.mr.find(cid, mod_id)
        if not m or m.role not in ("owner", "admin", "moderator"):
            raise ValueError("Not authorized")
        if not self.pr.pin(pid, pinned):
            raise ValueError("Post not found")
