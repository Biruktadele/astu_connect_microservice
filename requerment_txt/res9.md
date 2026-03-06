════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — COMMUNITY ↔ FEED INTEGRATION CONTRACT
Event catalog, data shapes, error handling, delay semantics
════════════════════════════════════════════════════════════════════════════════

Builds on:  res1 §3.3/§3.5 (Feed & Community bounded contexts)
            res3 §7 (internal gRPC contracts) §8 (Kafka topics)
            res4 §2 (Avro envelope) §6 (partition keys) §7 (outbox)
            res6 §5 (hybrid fan-out)
            res8 §6.3 (community-scoped roles)

Audience:   Engineers on EITHER team implementing the integration.
            Both teams sign off on this contract before coding.

================================================================================
TABLE OF CONTENTS
================================================================================

  §1  Integration Map — Who Needs What From Whom
  §2  Async Channel: community.events → Feed
  §3  Sync Channel: Feed → Community gRPC (authz only)
  §4  Data Shapes — Every Payload, Fully Specified
  §5  Delay Semantics — What "Eventual" Means In Practice
  §6  Error Handling — Every Failure Mode
  §7  Ordering & Causality
  §8  Local Projection — Feed's Membership Cache
  §9  Testing Contract
  §10 Whole-Plan Summary

================================================================================
§1  INTEGRATION MAP — WHO NEEDS WHAT FROM WHOM
================================================================================

── 1.1  THE OWNERSHIP BOUNDARY ─────────────────────────────────────

  COMMUNITY SERVICE OWNS:
    • Which communities exist.
    • Who is a member of which community.
    • What role each member has (member / moderator / owner).
    • Posts created INSIDE a community (community_posts table).

  FEED SERVICE OWNS:
    • Personal posts (posts table, follower fan-out).
    • Every user's home timeline (Redis ZSET + PG fallback).
    • Comments & reactions on ALL posts (including community posts).

  THE INTEGRATION PROBLEM:
    A user's home timeline should include posts from communities
    they're a member of, interleaved with posts from people they
    follow. Feed Service builds the timeline — but Community
    Service owns community membership and community posts.

── 1.2  TWO CHANNELS, CLEAR RULES ──────────────────────────────────

  ┌───────────────────────────────────────────────────────────────┐
  │                                                               │
  │   ASYNC (Kafka events) — Community PRODUCES, Feed CONSUMES    │
  │   ─────────────────────────────────────────────────────────   │
  │                                                               │
  │   USE WHEN: Community's state CHANGED and Feed needs to       │
  │             REACT eventually. Feed can tolerate seconds of    │
  │             lag. No response needed.                          │
  │                                                               │
  │   EVENTS:   community.post.created                            │
  │             community.post.removed                            │
  │             community.member.joined                           │
  │             community.member.left                             │
  │             community.role.changed                            │
  │             community.created                                 │
  │             community.deleted                                 │
  │                                                               │
  │   TOPIC:    community.events (12 partitions, compacted,       │
  │             key = community_id, per res4 §6.2/§9.2)           │
  │                                                               │
  ├───────────────────────────────────────────────────────────────┤
  │                                                               │
  │   SYNC (gRPC) — Feed CALLS, Community RESPONDS                │
  │   ─────────────────────────────────────────────────────────   │
  │                                                               │
  │   USE WHEN: Feed needs an ANSWER RIGHT NOW to make an         │
  │             authorization decision. Blocking the user's       │
  │             request. Cannot tolerate staleness.               │
  │                                                               │
  │   CALLS:    IsMemberBatch     (authz: can user see/post?)     │
  │             GetCommunityMeta  (display: name, icon on render) │
  │                                                               │
  │   NOTE:     These are FALLBACKS. The preferred path is        │
  │             Feed's local membership cache (§8), populated     │
  │             from community.events. gRPC is for cache misses   │
  │             and cache-staleness paranoia on high-risk ops.    │
  │                                                               │
  └───────────────────────────────────────────────────────────────┘

── 1.3  DIRECTION MATRIX ───────────────────────────────────────────

  ┌──────────────────┬─────────────────────┬─────────────────────┐
  │                  │ Feed → Community    │ Community → Feed    │
  ├──────────────────┼─────────────────────┼─────────────────────┤
  │ Async (events)   │ NONE.               │ community.events    │
  │                  │ Feed's events       │ (7 event types,     │
  │                  │ (post.created etc.) │  see §2).           │
  │                  │ are consumed by     │                     │
  │                  │ Notification &      │                     │
  │                  │ Search, not by      │                     │
  │                  │ Community.          │                     │
  ├──────────────────┼─────────────────────┼─────────────────────┤
  │ Sync (gRPC)      │ IsMemberBatch       │ NONE.               │
  │                  │ GetCommunityMeta    │ Community never     │
  │                  │ GetMemberIds        │ needs a synchronous │
  │                  │ (streaming, for     │ answer from Feed.   │
  │                  │  backfill)          │                     │
  └──────────────────┴─────────────────────┴─────────────────────┘

  WHY Community never calls Feed:
    Community's operations (create community, approve join,
    promote moderator) don't depend on anything Feed owns.
    Community is upstream of Feed in the dependency graph.
    One-way dependency = no cycles = simpler reasoning.

================================================================================
§2  ASYNC CHANNEL: community.events → FEED
================================================================================

── 2.1  CONSUMER GROUP ─────────────────────────────────────────────

  Feed Service runs a Kafka consumer:

    group.id            = feed-community-consumer
    auto.offset.reset   = earliest  (on first deploy; else committed)
    enable.auto.commit  = false     (manual commit after processing)
    topics              = community.events

  Separate from feed-fanout-worker (which consumes feed.fanout.cmd)
  and feed-post-consumer (which consumes post.events). Each consumer
  group has ONE responsibility.

── 2.2  EVENT → ACTION TABLE ───────────────────────────────────────

  For each event type on community.events, what Feed does:

  ┌─────────────────────────────┬───────────────────────────────────┐
  │ Event                       │ Feed's reaction                   │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.post.created      │ Fan out to all community members' │
  │                             │ timelines. Emit N timeline.write  │
  │                             │ commands to feed.fanout.cmd       │
  │                             │ (one per member). Same machinery  │
  │                             │ as personal-post fan-out (res6),  │
  │                             │ but recipient list = community    │
  │                             │ members instead of followers.     │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.post.removed      │ Remove post from all members'     │
  │                             │ timelines. Emit N timeline.remove │
  │                             │ commands (ZREM).                  │
  │                             │ Also: soft-delete any comments/   │
  │                             │ reactions Feed holds for this     │
  │                             │ post_id (cascade).                │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.member.joined     │ TWO actions:                      │
  │                             │ (a) Upsert into Feed's local      │
  │                             │     membership cache (§8).        │
  │                             │ (b) Backfill: fetch last ~50      │
  │                             │     community posts, ZADD into    │
  │                             │     the new member's timeline.    │
  │                             │     (So they don't see an empty   │
  │                             │      community on join.)          │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.member.left       │ TWO actions:                      │
  │                             │ (a) Delete from Feed's local      │
  │                             │     membership cache.             │
  │                             │ (b) Purge: ZREM all posts from    │
  │                             │     this community out of the     │
  │                             │     ex-member's timeline.         │
  │                             │     (They no longer see posts     │
  │                             │      from a community they left.) │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.role.changed      │ Upsert into Feed's local          │
  │                             │ membership cache (role column).   │
  │                             │ No timeline change — role doesn't │
  │                             │ affect visibility, only authz.    │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.created           │ Insert into Feed's local          │
  │                             │ community_meta cache (name, icon, │
  │                             │ visibility). Used for rendering   │
  │                             │ community badges on posts.        │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.deleted           │ (a) Delete from community_meta.   │
  │                             │ (b) Purge all members' timelines  │
  │                             │     of this community's posts.    │
  │                             │ (c) Soft-delete comments/         │
  │                             │     reactions on those posts.     │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.join.requested    │ IGNORED. Feed doesn't care about  │
  │                             │ pending requests. (Notification   │
  │                             │ Service consumes this to ping     │
  │                             │ community moderators.)            │
  └─────────────────────────────┴───────────────────────────────────┘

── 2.3  THE FAN-OUT FLOW FOR A COMMUNITY POST ──────────────────────

  End-to-end, from user action to timeline:

  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │  t=0ms   User POST /v1/communities/{cid}/posts { body }         │
  │          → hits Community Service.                              │
  │                                                                 │
  │  t=5ms   Community Service validates:                           │
  │            • Is caller a member of {cid}? (local DB check)      │
  │            • Does caller have post permission?                  │
  │              (members can post unless community is              │
  │               moderator-post-only)                              │
  │                                                                 │
  │  t=10ms  BEGIN;                                                 │
  │            INSERT INTO community_posts (...);                   │
  │            INSERT INTO outbox                                   │
  │              (event_type='community.post.created',              │
  │               partition_key={cid}, payload=<avro>, ...);        │
  │          COMMIT;                                                │
  │          Return 201 to user.  ← USER-PERCEIVED LATENCY DONE.    │
  │                                                                 │
  │  t=60ms  Outbox relay polls, finds the row, publishes to        │
  │          community.events (key={cid}).                          │
  │                                                                 │
  │  t=100ms Feed's feed-community-consumer receives the event.     │
  │          Handler for community.post.created:                    │
  │                                                                 │
  │            1. Idempotency check (§6.1):                         │
  │                 SELECT 1 FROM processed_events                  │
  │                   WHERE event_id = envelope.event_id;           │
  │               Exists → ACK and skip. Doesn't exist → proceed.   │
  │                                                                 │
  │            2. Look up community members.                        │
  │               Preferred: Feed's local membership cache (§8).    │
  │                 SELECT user_id FROM community_members_cache     │
  │                   WHERE community_id = {cid};                   │
  │               Fallback (cache empty/cold):                      │
  │                 gRPC community.v1.GetMemberIds({cid}) streaming.│
  │                                                                 │
  │            3. For each member, emit timeline.write to           │
  │               feed.fanout.cmd (partitioned by target_user_id).  │
  │               Batch-produce (100 per Kafka batch).              │
  │                                                                 │
  │            4. INSERT INTO processed_events (event_id, NOW()).   │
  │               Commit Kafka offset.                              │
  │                                                                 │
  │  t=200ms Fan-out workers consume feed.fanout.cmd, ZADD into     │
  │          each member's Redis timeline. (Same workers that       │
  │          handle personal-post fan-out — they don't care if      │
  │          the source was a follow or a community.)               │
  │                                                                 │
  │  t=1–5s  All members see the post in their home feed.           │
  │          (res3 §3 NFR: p99 ≤ 5s feed freshness.)                │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

── 2.4  LARGE COMMUNITIES — THE CELEBRITY PROBLEM, AGAIN ───────────

  A community with 10,000 members has the same fan-out amplification
  as a user with 10,000 followers. The hybrid threshold (res6 §5)
  applies here too:

    CONFIG: COMMUNITY_CELEBRITY_THRESHOLD = 2,000 members

    IF community.member_count ≥ threshold:
      DO NOT emit timeline.write commands.
      Instead: mark the community as "pull-mode" in Feed's
               community_meta cache.

    At read time, the timeline merge query (res6 §1.3) includes:
      (a) ZREVRANGE timeline:{me}           ← push-built portion
      (b) SELECT from posts WHERE author_id IN (celebrity follows)
      (c) SELECT from community_posts WHERE community_id IN
          (my pull-mode communities) AND created_at > cursor
          ORDER BY created_at DESC LIMIT 50

    All three merged by timestamp, paginated.

  The threshold is higher for communities (2,000 vs 1,000 for
  users) because community posts are typically less frequent than
  prolific individual posters, so the write amplification per
  community is lower even at the same member count. Tunable.

================================================================================
§3  SYNC CHANNEL: FEED → COMMUNITY gRPC
================================================================================

── 3.1  WHEN FEED CALLS COMMUNITY SYNCHRONOUSLY ───────────────────

  Only when Feed needs an ANSWER to proceed with a user-facing
  request, AND the local cache can't be trusted for this decision.

  ┌────────────────────────────────────┬──────────────────────────┐
  │ Use case                           │ Why sync, not async      │
  ├────────────────────────────────────┼──────────────────────────┤
  │ User comments on a community post. │ Feed must verify "is     │
  │ Feed owns comments but needs to    │ this user a member?"     │
  │ know if the user is a member       │ before accepting the     │
  │ (private communities gate          │ comment. Can't use stale │
  │  commenting on membership).        │ cache — user might have  │
  │                                    │ been kicked 3 seconds    │
  │                                    │ ago. Accept the latency  │
  │                                    │ hit on a WRITE path.     │
  ├────────────────────────────────────┼──────────────────────────┤
  │ Rendering a post with a community  │ DISPLAY, not authz. Use  │
  │ badge (community name + icon).     │ local community_meta     │
  │                                    │ cache. Stale name for    │
  │                                    │ 5 seconds is fine.       │
  │                                    │ gRPC only on cache MISS  │
  │                                    │ (cold cache, new         │
  │                                    │  community Feed hasn't   │
  │                                    │  heard of yet).          │
  ├────────────────────────────────────┼──────────────────────────┤
  │ Backfill on member.joined (fetch   │ Feed needs the LIST of   │
  │ recent community posts for the new │ recent posts. Could read │
  │ member's timeline).                │ from its own cache if it │
  │                                    │ mirrored community_posts,│
  │                                    │ but that's data          │
  │                                    │ duplication. Simpler:    │
  │                                    │ ask Community directly.  │
  │                                    │ It's an ASYNC handler    │
  │                                    │ (consuming Kafka), so    │
  │                                    │ gRPC latency doesn't     │
  │                                    │ block any user.          │
  └────────────────────────────────────┴──────────────────────────┘

── 3.2  gRPC SERVICE DEFINITION ───────────────────────────────────

  community/v1/membership.proto:

    service MembershipService {
      // Batch check: is each user a member of the community?
      // Returns a map<user_id, MembershipStatus>.
      // Use for: authz decisions, cache validation.
      rpc IsMemberBatch(IsMemberBatchRequest)
          returns (IsMemberBatchResponse);

      // Stream all member IDs for a community.
      // Use for: fan-out (when local cache is cold).
      // Server streams in chunks of 500.
      rpc GetMemberIds(GetMemberIdsRequest)
          returns (stream MemberChunk);
    }

    message IsMemberBatchRequest {
      string community_id = 1;
      repeated string user_ids = 2;  // max 100 per call
    }

    message IsMemberBatchResponse {
      map<string, MembershipStatus> results = 1;
    }

    message MembershipStatus {
      bool is_member = 1;
      CommunityRole role = 2;        // MEMBER | MODERATOR | OWNER
      google.protobuf.Timestamp joined_at = 3;
    }

    message GetMemberIdsRequest {
      string community_id = 1;
    }

    message MemberChunk {
      repeated string user_ids = 1;  // up to 500 per chunk
      bool is_last = 2;
    }

  community/v1/meta.proto:

    service CommunityMetaService {
      // Fetch display metadata for a batch of communities.
      // Use for: rendering badges when local cache misses.
      rpc GetCommunityMetaBatch(GetMetaBatchRequest)
          returns (GetMetaBatchResponse);

      // Fetch recent posts for backfill.
      rpc GetRecentPosts(GetRecentPostsRequest)
          returns (GetRecentPostsResponse);
    }

    message CommunityMeta {
      string community_id = 1;
      string name = 2;
      string icon_url = 3;
      Visibility visibility = 4;     // PUBLIC | PRIVATE
      int32 member_count = 5;
      bool is_celebrity = 6;         // member_count ≥ threshold
    }

    message GetRecentPostsRequest {
      string community_id = 1;
      int32 limit = 2;               // max 100
      google.protobuf.Timestamp before = 3;  // pagination
    }

    message PostRef {
      string post_id = 1;
      string author_id = 2;
      google.protobuf.Timestamp created_at = 3;
    }

── 3.3  gRPC RESILIENCE ───────────────────────────────────────────

  All Feed→Community gRPC calls go through the standard resilience
  stack (res1 §4.1):

    • Timeout: 200ms for IsMemberBatch, 500ms for streaming.
    • Retry: 2 attempts with 50ms jitter backoff on UNAVAILABLE
      or DEADLINE_EXCEEDED. No retry on INVALID_ARGUMENT or
      NOT_FOUND.
    • Circuit breaker: open after 5 consecutive failures. Half-open
      probe every 30s.

  BEHAVIOR WHEN CIRCUIT IS OPEN:

    ┌─────────────────────────┬──────────────────────────────────┐
    │ Call                    │ Fallback                         │
    ├─────────────────────────┼──────────────────────────────────┤
    │ IsMemberBatch (authz)   │ Use local membership cache (§8). │
    │                         │ Cache hit → proceed (slightly    │
    │                         │ stale authz, acceptable).        │
    │                         │ Cache miss → FAIL CLOSED. Return │
    │                         │ 503 to the user with Retry-After.│
    │                         │ Better to reject a legitimate    │
    │                         │ comment than to let a kicked     │
    │                         │ member post.                     │
    ├─────────────────────────┼──────────────────────────────────┤
    │ GetCommunityMeta        │ Use local community_meta cache.  │
    │ (display)               │ Cache miss → render post WITHOUT │
    │                         │ the community badge. Degraded    │
    │                         │ UI, not an error. Log and move   │
    │                         │ on.                              │
    ├─────────────────────────┼──────────────────────────────────┤
    │ GetMemberIds            │ Skip fan-out for this event.     │
    │ (fan-out in async       │ Do NOT commit the Kafka offset.  │
    │  handler)               │ The consumer retries on next     │
    │                         │ poll. If circuit stays open >    │
    │                         │ 5 min, event goes to DLT         │
    │                         │ (reprocessed via RB-10 when      │
    │                         │  Community recovers).            │
    ├─────────────────────────┼──────────────────────────────────┤
    │ GetRecentPosts          │ Skip backfill. New member sees   │
    │ (backfill in async      │ an empty community until new     │
    │  handler)               │ posts arrive via normal fan-out. │
    │                         │ Acceptable degraded UX.          │
    │                         │ Commit offset (don't retry —     │
    │                         │ backfill is best-effort).        │
    └─────────────────────────┴──────────────────────────────────┘

================================================================================
§4  DATA SHAPES — EVERY PAYLOAD, FULLY SPECIFIED
================================================================================

All events use the EventEnvelope (res4 §2.1). Payloads are Avro,
registered in Schema Registry under subject
`community.events-com.astuconnect.events.community.<EventName>-value`.

── 4.1  community.post.created ────────────────────────────────────

  {
    "type": "record",
    "name": "CommunityPostCreatedV1",
    "namespace": "com.astuconnect.events.community",
    "fields": [
      { "name": "post_id",        "type": "string",
        "doc": "UUIDv7. Community Service's primary key." },

      { "name": "community_id",   "type": "string",
        "doc": "Which community. Also the Kafka partition key." },

      { "name": "author_id",      "type": "string",
        "doc": "Who posted. Feed uses this for attribution." },

      { "name": "body_preview",   "type": "string",
        "doc": "First 280 chars. Feed stores this in the timeline
                entry for fast rendering without a round-trip." },

      { "name": "has_media",      "type": "boolean",
        "doc": "Render hint. Feed shows a media placeholder." },

      { "name": "media_refs",     "type": { "type": "array",
                                    "items": "string" },
                                    "default": [],
        "doc": "Media Service IDs. Empty if has_media=false." },

      { "name": "visibility",     "type": {
          "type": "enum", "name": "PostVisibility",
          "symbols": ["PUBLIC", "MEMBERS_ONLY"] },
        "doc": "PUBLIC community posts visible to non-members via
                search. MEMBERS_ONLY only fan out to members." },

      { "name": "member_count_at_post",  "type": "int",
        "doc": "Snapshot of member count. Feed uses this to decide
                push vs pull (celebrity threshold) without a
                separate lookup. Approximate — computed at post
                time, may drift by a few during fan-out." },

      { "name": "created_at",     "type": { "type": "long",
                                    "logicalType": "timestamp-millis" },
        "doc": "When the user hit submit. Used as ZSET score." }
    ]
  }

  FEED'S CONTRACT ON RECEIPT:
    • MUST fan out to all current members IF
      member_count_at_post < COMMUNITY_CELEBRITY_THRESHOLD.
    • MUST mark community as pull-mode IF ≥ threshold.
    • MUST use created_at as the timeline ZSET score.
    • MAY cache body_preview for fast rendering.
    • MUST record event_id as processed (idempotency).

── 4.2  community.post.removed ────────────────────────────────────

  {
    "type": "record",
    "name": "CommunityPostRemovedV1",
    "namespace": "com.astuconnect.events.community",
    "fields": [
      { "name": "post_id",        "type": "string" },
      { "name": "community_id",   "type": "string" },
      { "name": "removed_by",     "type": "string",
        "doc": "user_id who removed. Author (self-delete) or
                moderator (moderation)." },
      { "name": "removal_reason", "type": {
          "type": "enum", "name": "RemovalReason",
          "symbols": ["AUTHOR_DELETED", "MODERATED",
                      "COMMUNITY_DELETED"] } },
      { "name": "removed_at",     "type": { "type": "long",
                                    "logicalType": "timestamp-millis" } }
    ]
  }

  FEED'S CONTRACT ON RECEIPT:
    • MUST emit timeline.remove commands for all members
      (ZREM post_id from their timelines).
    • MUST soft-delete comments/reactions Feed holds for post_id.
    • IF removal_reason = COMMUNITY_DELETED: expect a flood of
      these. Batch ZREM operations.

── 4.3  community.member.joined ───────────────────────────────────

  {
    "type": "record",
    "name": "CommunityMemberJoinedV1",
    "namespace": "com.astuconnect.events.community",
    "fields": [
      { "name": "community_id",   "type": "string" },
      { "name": "user_id",        "type": "string" },
      { "name": "role",           "type": {
          "type": "enum", "name": "CommunityRole",
          "symbols": ["MEMBER", "MODERATOR", "OWNER"] },
        "default": "MEMBER" },
      { "name": "joined_at",      "type": { "type": "long",
                                    "logicalType": "timestamp-millis" } },
      { "name": "join_method",    "type": {
          "type": "enum", "name": "JoinMethod",
          "symbols": ["DIRECT", "APPROVED", "INVITED"] },
        "doc": "DIRECT = public community, instant join.
                APPROVED = private, moderator approved request.
                INVITED = moderator invited the user." }
    ]
  }

  FEED'S CONTRACT ON RECEIPT:
    • MUST upsert (community_id, user_id, role, joined_at) into
      local community_members_cache.
    • SHOULD backfill: call GetRecentPosts({community_id},
      limit=50), ZADD each into user_id's timeline. Best-effort
      (skip on gRPC failure).

── 4.4  community.member.left ─────────────────────────────────────

  {
    "type": "record",
    "name": "CommunityMemberLeftV1",
    "namespace": "com.astuconnect.events.community",
    "fields": [
      { "name": "community_id",   "type": "string" },
      { "name": "user_id",        "type": "string" },
      { "name": "left_at",        "type": { "type": "long",
                                    "logicalType": "timestamp-millis" } },
      { "name": "leave_reason",   "type": {
          "type": "enum", "name": "LeaveReason",
          "symbols": ["VOLUNTARY", "KICKED", "COMMUNITY_DELETED"] } }
    ]
  }

  FEED'S CONTRACT ON RECEIPT:
    • MUST delete (community_id, user_id) from local cache.
    • MUST purge community's posts from user's timeline:
        For each post_id in timeline:{user} that belongs to this
        community → ZREM.
      (Requires knowing which posts are from which community.
       Feed stores this in a secondary index:
         community_posts_in_timeline:{user_id}:{community_id}
           → Set of post_ids
       Maintained on ZADD.)

── 4.5  community.role.changed ────────────────────────────────────

  {
    "type": "record",
    "name": "CommunityRoleChangedV1",
    "namespace": "com.astuconnect.events.community",
    "fields": [
      { "name": "community_id",   "type": "string" },
      { "name": "user_id",        "type": "string" },
      { "name": "old_role",       "type": "CommunityRole" },
      { "name": "new_role",       "type": "CommunityRole" },
      { "name": "changed_by",     "type": "string" },
      { "name": "changed_at",     "type": { "type": "long",
                                    "logicalType": "timestamp-millis" } }
    ]
  }

  FEED'S CONTRACT ON RECEIPT:
    • MUST update role in local community_members_cache.
    • No timeline changes (role affects authz, not visibility).

── 4.6  community.created / community.deleted ─────────────────────

  CommunityCreatedV1:
    { community_id, name, description, icon_url, visibility,
      created_by, created_at }

  CommunityDeletedV1:
    { community_id, deleted_by, deleted_at }

  FEED'S CONTRACT ON RECEIPT:
    created:
      • INSERT into community_meta cache.
    deleted:
      • DELETE from community_meta cache.
      • DELETE all rows from community_members_cache WHERE
        community_id = X.
      • Expect a flood of community.post.removed (Community
        emits one per post as part of deletion). Process
        normally — ZREMs are idempotent.

── 4.7  THE TIMELINE ENTRY FORMAT (what Feed actually stores) ──────

  Redis ZSET: timeline:{user_id}
    MEMBER = post reference (compact, fits in a ZSET member)
    SCORE  = created_at epoch millis (for reverse-chron ordering)

  Member encoding (pipe-separated, ~60 bytes):

    <source>|<post_id>|<origin_id>

  Where:
    source     = "p"  (personal — follower fan-out)
               | "c"  (community — membership fan-out)
    post_id    = the post's primary key (UUIDv7)
    origin_id  = author_id     (if source=p)
               | community_id  (if source=c)

  Example:
    "c|01HRXYZ-ABCD-...|comm_robotics_club"  →  score 1772457600000

  Why this encoding:
    • Feed's render path can tell "this is a community post" and
      fetch the community badge without a separate lookup table.
    • Purge-on-leave (§4.4) can ZSCAN timeline:{u} for members
      matching "c|*|{community_id}" and ZREM them.
    • Still fits comfortably in a ZSET member (Redis limit 512 MB
      per member; we use ~60 bytes).

  Secondary index for fast purge:

    community_posts_in_timeline:{user_id}:{community_id}
      → Redis SET of "c|<post_id>|<community_id>" strings

  On ZADD of a community post: also SADD to this index.
  On member.left: SMEMBERS this index → ZREM each from timeline
  → DEL the index. O(community posts in this user's timeline),
  not O(full timeline).

================================================================================
§5  DELAY SEMANTICS — WHAT "EVENTUAL" MEANS IN PRACTICE
================================================================================

── 5.1  LATENCY BUDGET PER EVENT TYPE ──────────────────────────────

  ┌─────────────────────────────┬───────────┬─────────────────────┐
  │ Event                       │ p50       │ p99 (SLO)           │
  │                             │ end-to-end│                     │
  ├─────────────────────────────┼───────────┼─────────────────────┤
  │ community.post.created      │ ~500 ms   │ ≤ 5 s               │
  │ → visible in member         │           │ (matches feed       │
  │   timelines                 │           │  freshness SLO,     │
  │                             │           │  res3 §3)           │
  ├─────────────────────────────┼───────────┼─────────────────────┤
  │ community.post.removed      │ ~500 ms   │ ≤ 10 s              │
  │ → gone from timelines       │           │ (less urgent than   │
  │                             │           │  creation)          │
  ├─────────────────────────────┼───────────┼─────────────────────┤
  │ community.member.joined     │ ~1 s      │ ≤ 30 s              │
  │ → new member's cache        │           │ (backfill is        │
  │   updated + backfill done   │           │  best-effort; cache │
  │                             │           │  update is the SLO) │
  ├─────────────────────────────┼───────────┼─────────────────────┤
  │ community.member.left       │ ~1 s      │ ≤ 30 s              │
  │ → ex-member's cache cleared │           │                     │
  │   + timeline purged         │           │                     │
  ├─────────────────────────────┼───────────┼─────────────────────┤
  │ community.role.changed      │ ~1 s      │ ≤ 30 s              │
  │ → Feed's cache reflects     │           │ (authz uses gRPC    │
  │   new role                  │           │  fallback if cache  │
  │                             │           │  is stale on a      │
  │                             │           │  write, so this     │
  │                             │           │  lag is display-    │
  │                             │           │  only)              │
  └─────────────────────────────┴───────────┴─────────────────────┘

── 5.2  WHERE THE TIME GOES ───────────────────────────────────────

  For community.post.created → timeline visibility:

    ┌────────────────────────────────┬────────────┬──────────────┐
    │ Stage                          │ p50        │ Contributes  │
    │                                │            │ to tail?     │
    ├────────────────────────────────┼────────────┼──────────────┤
    │ HTTP request → Community DB    │  10 ms     │ No (sync,    │
    │ commit (user sees 201 here)    │            │ bounded)     │
    │                                │            │              │
    │ Outbox relay poll cycle        │  25 ms     │ Yes — 50 ms  │
    │ (avg wait for next poll)       │ (0–50 ms)  │ worst-case   │
    │                                │            │              │
    │ Kafka produce + replicate      │   5 ms     │ Rarely       │
    │ (acks=all)                     │            │              │
    │                                │            │              │
    │ Feed consumer poll + process   │ 100 ms     │ Yes — batch  │
    │ (batch of events, enumerate    │            │ size &       │
    │  members, emit fanout cmds)    │            │ member count │
    │                                │            │              │
    │ feed.fanout.cmd queue wait     │  50 ms     │ Yes — worker │
    │ + worker ZADD                  │            │ lag under    │
    │                                │            │ burst        │
    │                                │            │              │
    │ Client refresh cycle (user     │ 0–varies   │ User-        │
    │ must actually open/refresh     │            │ dependent    │
    │ the feed to SEE it)            │            │              │
    ├────────────────────────────────┼────────────┼──────────────┤
    │ TOTAL (server-side)            │ ~190 ms    │ p99 dominated│
    │                                │            │ by fanout    │
    │                                │            │ worker lag   │
    └────────────────────────────────┴────────────┴──────────────┘

── 5.3  WHAT USERS EXPERIENCE DURING THE DELAY ─────────────────────

  ┌──────────────────────────────┬──────────────────────────────────┐
  │ Scenario                     │ User experience                  │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ User posts in a community,   │ Own post visible IMMEDIATELY     │
  │ then immediately refreshes   │ via optimistic UI (client        │
  │ their own feed.              │ inserts locally on 201).         │
  │                              │ Other members' feeds: ~500ms     │
  │                              │ later. Nobody notices.           │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ User joins a community,      │ Cache update: ~1s. During that   │
  │ then immediately views the   │ 1s, if they try to comment on a  │
  │ community page.              │ community post, Feed's authz     │
  │                              │ check falls through to gRPC      │
  │                              │ IsMemberBatch (cache miss) →     │
  │                              │ gets fresh answer → comment      │
  │                              │ succeeds. User never notices.    │
  │                              │                                  │
  │                              │ Backfill: ~30s (GetRecentPosts   │
  │                              │ + ZADD). During that window,     │
  │                              │ home feed doesn't show           │
  │                              │ community posts yet. But the     │
  │                              │ community PAGE (direct view,     │
  │                              │ served by Community Service)     │
  │                              │ shows posts immediately. User    │
  │                              │ is probably looking at the       │
  │                              │ community page anyway.           │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ Moderator kicks a user. User │ member.left event: ~1s to        │
  │ was viewing the community    │ propagate.                       │
  │ at the time.                 │                                  │
  │                              │ Timeline purge: ~30s.            │
  │                              │                                  │
  │                              │ Authz on WRITES: immediate       │
  │                              │ (Community Service owns the      │
  │                              │  membership table; a kicked      │
  │                              │  user's next post attempt hits   │
  │                              │  Community's own DB check →      │
  │                              │  403). ← This is the one that    │
  │                              │  matters for abuse.              │
  │                              │                                  │
  │                              │ Authz on READS (via Feed's       │
  │                              │ cache): ~1–30s stale. The kicked │
  │                              │ user might see community posts   │
  │                              │ in their home feed for up to     │
  │                              │ 30s. Cosmetic — they can't       │
  │                              │ interact (writes go through      │
  │                              │ Community's fresh check).        │
  └──────────────────────────────┴──────────────────────────────────┘

── 5.4  LAG MONITORING & ALERTING ─────────────────────────────────

  Prometheus metrics exported by feed-community-consumer:

    kafka_consumer_lag{group="feed-community-consumer",
                       topic="community.events",
                       partition="*"}
      → Gauge. Kafka-reported lag per partition.

    feed_community_event_processing_seconds{event_type="*"}
      → Histogram. Time from envelope.occurred_at to
        "processing complete + offset committed".

    feed_community_events_processed_total{event_type="*",result="*"}
      → Counter. result = ok | skipped_duplicate | error | dlt.

  Alerts:

    WARN  kafka_consumer_lag > 1,000 for > 2 min
          "Feed is falling behind on community events."

    CRIT  kafka_consumer_lag > 10,000 for > 5 min
          "Feed community consumer is stuck. Check DLT."

    WARN  p99(feed_community_event_processing_seconds) > 30s
          "Community event SLO at risk."

    CRIT  rate(feed_community_events_processed_total
               {result="dlt"}) > 1/min for > 5 min
          "Poison messages detected. Inspect DLT."

================================================================================
§6  ERROR HANDLING — EVERY FAILURE MODE
================================================================================

── 6.1  CONSUMER-SIDE IDEMPOTENCY ─────────────────────────────────

  The outbox pattern guarantees at-least-once (res4 §7.5). Feed
  MUST tolerate duplicate events.

  Mechanism:

    CREATE TABLE processed_events (
      event_id    TEXT PRIMARY KEY,
      processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    -- Partitioned by month, old partitions dropped after 60 days.

  On every event:

    BEGIN;
      INSERT INTO processed_events (event_id)
        VALUES (envelope.event_id)
        ON CONFLICT (event_id) DO NOTHING
        RETURNING event_id;

      IF no row returned:
        -- Duplicate. Skip processing. Commit tx (no-op).
        -- Commit Kafka offset. Continue.
      ELSE:
        -- New event. Process it. Commit tx. Commit Kafka offset.

  WHY a DB table and not Redis:
    • The membership cache updates are DB writes anyway. Wrapping
      the idempotency check in the same transaction means "process
      event" is atomic: either we process AND record, or neither.
    • Redis-only dedup risks processing twice if we crash between
      "update cache" and "SET dedup key".

  EXCEPTIONS — idempotent-by-nature operations:
    • ZADD (timeline write) is naturally idempotent. No dedup
      table entry needed for timeline.write commands.
    • Cache UPSERT is naturally idempotent. But we still use the
      dedup table for member.joined because of the backfill side
      effect (don't want to backfill twice).

── 6.2  EVENT PROCESSING FAILURES ─────────────────────────────────

  Retry ladder for a single event:

  ┌──────────────┬────────────────────────────────────────────────┐
  │ Attempt      │ Action                                         │
  ├──────────────┼────────────────────────────────────────────────┤
  │ 1 (inline)   │ Process. If exception: log, increment retry    │
  │              │ counter in consumer state, DO NOT commit       │
  │              │ offset, re-poll (Kafka redelivers same batch). │
  ├──────────────┼────────────────────────────────────────────────┤
  │ 2–5 (inline) │ Same. Exponential backoff between attempts     │
  │              │ (100ms, 200ms, 400ms, 800ms). Still don't      │
  │              │ commit offset.                                 │
  ├──────────────┼────────────────────────────────────────────────┤
  │ 6 (give up)  │ Produce the event (with error headers, per     │
  │              │ res4 §4.2 R4) to feed-community-consumer.dlt.  │
  │              │ COMMIT the offset (stop blocking the           │
  │              │ partition). Log ERROR. Alert if DLT rate > 0.  │
  └──────────────┴────────────────────────────────────────────────┘

  CRITICAL RULE: a failing event MUST NOT block other events on
  the same partition forever. After 5 retries (~1.5s total), DLT
  it and move on. Ops investigates the DLT (res5 RB-10).

── 6.3  FAILURE CLASSIFICATION ────────────────────────────────────

  The consumer distinguishes transient from permanent failures:

  ┌─────────────────────────────────┬──────────┬──────────────────┐
  │ Error                           │ Class    │ Action           │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Feed PG unreachable             │ TRANSIENT│ Inline retry.    │
  │ (cache upsert fails)            │          │ Don't commit.    │
  │                                 │          │ Partition stalls │
  │                                 │          │ until PG is back │
  │                                 │          │ — this is        │
  │                                 │          │ correct: we need │
  │                                 │          │ PG to proceed.   │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Redis unreachable               │ TRANSIENT│ Same. Stall.     │
  │ (ZADD for timeline fails)       │          │                  │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Community gRPC UNAVAILABLE      │ TRANSIENT│ Retry ladder.    │
  │ (GetMemberIds for fan-out)      │          │ DLT after 5.     │
  │                                 │          │ DLT reprocessing │
  │                                 │          │ works once       │
  │                                 │          │ Community is up. │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Community gRPC NOT_FOUND        │ PERMANENT│ Log warn. Skip   │
  │ (community_id doesn't exist)    │          │ (commit offset). │
  │                                 │          │ Likely: community│
  │                                 │          │ was deleted; the │
  │                                 │          │ post.created     │
  │                                 │          │ raced with       │
  │                                 │          │ community.deleted│
  │                                 │          │ See §7.2.        │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Avro deserialization failure    │ PERMANENT│ DLT immediately  │
  │ (malformed payload)             │          │ (no retry —      │
  │                                 │          │  retrying won't  │
  │                                 │          │  fix bad bytes). │
  │                                 │          │ Alert: producer  │
  │                                 │          │ has a bug.       │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Unknown event_type              │ PERMANENT│ Log info. Skip.  │
  │ (e.g., community.new_feature    │          │ Forward-compat:  │
  │  that Feed doesn't handle yet)  │          │ Community added  │
  │                                 │          │ a new event type,│
  │                                 │          │ Feed will handle │
  │                                 │          │ it in a future   │
  │                                 │          │ release. Don't   │
  │                                 │          │ error, don't     │
  │                                 │          │ DLT.             │
  ├─────────────────────────────────┼──────────┼──────────────────┤
  │ Schema Registry unreachable     │ TRANSIENT│ Retry. If SR is  │
  │ (can't fetch schema to          │          │ down > 5 min,    │
  │  deserialize)                   │          │ bigger problem.  │
  │                                 │          │ Schemas are      │
  │                                 │          │ cached after     │
  │                                 │          │ first fetch, so  │
  │                                 │          │ this only hits   │
  │                                 │          │ on NEW schema    │
  │                                 │          │ versions.        │
  └─────────────────────────────────┴──────────┴──────────────────┘

── 6.4  PARTIAL FAILURES (the hard case) ──────────────────────────

  community.post.created with 500 members. Feed emits 500
  timeline.write commands to feed.fanout.cmd. The Kafka producer
  fails after sending 300.

  WRONG approach: commit offset, lose 200 timeline writes.

  RIGHT approach:

    1. Emit all 500 in a Kafka producer transaction (Kafka's
       exactly-once semantics, transactional.id set).
       All-or-nothing: either all 500 land in feed.fanout.cmd,
       or none do.

    2. IF transaction commits → INSERT processed_events → commit
       consumer offset.
       IF transaction aborts → don't commit offset → retry on
       next poll.

  OR, simpler (chosen for initial build):

    1. Emit 500 as individual produces (no transaction).
    2. Await all ACKs.
    3. IF any fail → log which ones → don't commit offset → retry.
       Retry re-emits all 500 (duplicates for the 300 that
       succeeded). Fan-out worker ZADD is idempotent → duplicates
       are no-ops. Correct result.

  Idempotency downstream makes partial failures self-healing.
  We accept the redundant work (re-emitting 300 successful
  commands) in exchange for simplicity.

── 6.5  CONSUMER CRASH MID-BATCH ──────────────────────────────────

  Kafka consumer in a batch of 50 events. Processes events 1–30,
  crashes before committing offset.

  On restart:
    • Kafka redelivers the whole batch (offset not committed).
    • Events 1–30 hit the processed_events dedup → skipped.
    • Events 31–50 are processed fresh.

  Correct. No loss, no double-processing. The dedup table is the
  crash-safety net.

── 6.6  COMMUNITY SERVICE DOWN — SYNC PATH IMPACT ─────────────────

  Circuit breaker opens on Feed's gRPC client after 5 failures.

  IMPACT MATRIX:

  ┌─────────────────────┬────────────────────┬─────────────────────┐
  │ Operation           │ Community UP       │ Community DOWN      │
  ├─────────────────────┼────────────────────┼─────────────────────┤
  │ Read home timeline  │ Redis + PG merge.  │ Same. Community     │
  │ (no community       │ No Community call. │ badge might not     │
  │  interaction)       │                    │ render if           │
  │                     │                    │ community_meta      │
  │                     │                    │ cache is cold.      │
  │                     │                    │ Graceful.           │
  ├─────────────────────┼────────────────────┼─────────────────────┤
  │ Comment on a        │ IsMemberBatch      │ Local cache check.  │
  │ community post      │ gRPC (fresh).      │ Hit → proceed       │
  │ (private community) │                    │ (stale, acceptable).│
  │                     │                    │ Miss → 503          │
  │                     │                    │ Retry-After: 30.    │
  │                     │                    │ Fail closed.        │
  ├─────────────────────┼────────────────────┼─────────────────────┤
  │ Fan-out a new       │ Member list from   │ Member list from    │
  │ community post      │ local cache        │ local cache         │
  │ (async consumer)    │ (preferred).       │ (required — gRPC    │
  │                     │ gRPC fallback if   │ fallback fails).    │
  │                     │ cold.              │ Cold cache → DLT.   │
  │                     │                    │ Reprocess after     │
  │                     │                    │ Community recovers. │
  ├─────────────────────┼────────────────────┼─────────────────────┤
  │ Backfill on         │ GetRecentPosts     │ Skip backfill.      │
  │ member.joined       │ gRPC.              │ New member sees     │
  │                     │                    │ empty community in  │
  │                     │                    │ home feed until new │
  │                     │                    │ posts arrive. UX    │
  │                     │                    │ degraded, not       │
  │                     │                    │ broken.             │
  └─────────────────────┴────────────────────┴─────────────────────┘

  NET: Community outage degrades Feed's community features but
  never takes Feed DOWN. Personal posts, personal timeline,
  comments on personal posts — all unaffected. Bounded blast
  radius (res1 §3 principle).

================================================================================
§7  ORDERING & CAUSALITY
================================================================================

── 7.1  WHAT KAFKA GUARANTEES ─────────────────────────────────────

  community.events partition key = community_id (res4 §6.2).
  So: all events for ONE community arrive at Feed IN ORDER.

    community X: created → member.joined → post.created →
                 post.removed → member.left → deleted

  Feed never sees post.created before community.created (for the
  same community). Never sees member.left before member.joined.

── 7.2  CROSS-COMMUNITY ORDERING (not guaranteed, not needed) ──────

  Events for community X and community Y may interleave in any
  order. Feed processes them independently. No cross-community
  causality exists in the domain, so no problem.

── 7.3  THE ONE TRICKY CASE: JOINED THEN IMMEDIATELY LEFT ──────────

  User joins community X, changes their mind, leaves 2 seconds
  later.

  Kafka ordering guarantees Feed sees joined BEFORE left. But
  Feed's handlers might process them asynchronously (backfill is
  a slow operation):

    t=0   member.joined received. Handler starts backfill
          (GetRecentPosts gRPC, ZADD 50 posts).
    t=1   member.left received. Handler starts purge.
    t=2   Backfill STILL RUNNING (gRPC is slow today).
          Purge completes: timeline cleaned.
    t=3   Backfill completes: ZADDs 50 posts.

  Result: user's timeline has 50 community posts even though
  they left. Bug.

  FIX — state-check before side effects:

    Backfill handler, BEFORE each ZADD batch:
      SELECT 1 FROM community_members_cache
        WHERE community_id = X AND user_id = U;
      IF no row → abort backfill (user has since left).

    The cache update (DELETE on member.left) happens synchronously
    in the event handler's DB transaction. By the time backfill
    checks, the DELETE has committed.

  This is a read-your-own-writes pattern: the fast path (cache
  DELETE) happens before the slow path (backfill ZADD) checks
  its precondition.

── 7.4  OUT-OF-ORDER WITH RESPECT TO OTHER TOPICS ──────────────────

  Cross-topic ordering is NOT guaranteed (res4 §6.5). Example:

    Community deletes a post (community.post.removed on
    community.events). Simultaneously, a user comments on that
    post (Feed writes comment, emits comment.created on
    comment.events).

    Feed might process the comment before the removal. Comment is
    stored. THEN removal arrives. Feed's post.removed handler
    cascades: soft-delete all comments on post_id. The late
    comment is cleaned up.

  Eventual consistency. The end state is correct. The intermediate
  state (comment briefly exists on a deleted post) is acceptable —
  nobody will see it because the post itself is gone from
  timelines.

================================================================================
§8  LOCAL PROJECTION — FEED'S MEMBERSHIP CACHE
================================================================================

── 8.1  SCHEMA ─────────────────────────────────────────────────────

  In Feed Service's Postgres:

    CREATE TABLE community_members_cache (
      community_id  TEXT NOT NULL,
      user_id       TEXT NOT NULL,
      role          TEXT NOT NULL,     -- 'MEMBER'|'MODERATOR'|'OWNER'
      joined_at     TIMESTAMPTZ NOT NULL,
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (community_id, user_id)
    );

    CREATE INDEX idx_cmc_by_user
      ON community_members_cache (user_id);
    -- For "which communities is user U in?" (timeline merge query)

    CREATE TABLE community_meta_cache (
      community_id  TEXT PRIMARY KEY,
      name          TEXT NOT NULL,
      icon_url      TEXT,
      visibility    TEXT NOT NULL,     -- 'PUBLIC'|'PRIVATE'
      member_count  INT NOT NULL,
      is_celebrity  BOOLEAN NOT NULL,  -- member_count ≥ threshold
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

── 8.2  MAINTENANCE ────────────────────────────────────────────────

  ┌─────────────────────────────┬───────────────────────────────────┐
  │ Event                       │ Cache operation                   │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.member.joined     │ INSERT INTO community_members_    │
  │                             │ cache (...) ON CONFLICT           │
  │                             │ (community_id, user_id) DO UPDATE │
  │                             │ SET role=EXCLUDED.role, ...       │
  │                             │ (UPSERT — safe on replay)         │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.member.left       │ DELETE FROM community_members_    │
  │                             │ cache WHERE community_id=X        │
  │                             │ AND user_id=U;                    │
  │                             │ (idempotent — DELETE of missing   │
  │                             │  row is a no-op)                  │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.role.changed      │ UPDATE community_members_cache    │
  │                             │ SET role=new_role, updated_at=... │
  │                             │ WHERE community_id=X              │
  │                             │ AND user_id=U;                    │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.created           │ INSERT INTO community_meta_cache  │
  │                             │ (...) ON CONFLICT DO UPDATE ...   │
  ├─────────────────────────────┼───────────────────────────────────┤
  │ community.deleted           │ DELETE FROM community_meta_cache  │
  │                             │ WHERE community_id=X;             │
  │                             │ DELETE FROM community_members_    │
  │                             │ cache WHERE community_id=X;       │
  │                             │ (single tx)                       │
  └─────────────────────────────┴───────────────────────────────────┘

── 8.3  CACHE REBUILD (res5 RB-9 analog) ──────────────────────────

  If community_members_cache is corrupted or lost:

    1. community.events is LOG-COMPACTED (res4 §9.2). Reading
       from offset 0 gives the latest state for every
       (community_id, event_type) pair.
    2. Create temp consumer group
       feed-community-rebuild-<timestamp>.
    3. Read from earliest. Handlers upsert as normal.
    4. At lag=0, cache is fully rebuilt.
    5. Validate: count parity vs Community gRPC GetMemberCount
       for 20 random communities (per res5 RB-12.1).
    6. Delete temp group.

  ~1 minute at current scale (~1,000 communities, ~30k
  memberships).

── 8.4  CACHE STALENESS BOUNDS ─────────────────────────────────────

  The cache is eventually consistent with Community's source of
  truth. Staleness = consumer lag + processing time.

  Normal: < 1 second.
  Under consumer backlog: up to a few minutes.
  Hard bound: none — if the consumer is stopped, cache freezes.

  WHERE STALENESS IS ACCEPTABLE:
    • Fan-out (post.created): worst case, a very-recently-joined
      member misses one post. They'll see the next one.
    • Display (community badge): stale name for seconds. Cosmetic.

  WHERE STALENESS IS NOT ACCEPTABLE:
    • Authz on writes (can this user post/comment/react?).
      Here we use gRPC IsMemberBatch as the authoritative check
      (§3.3 fallback table). Cache is a hint, not authority.

================================================================================
§9  TESTING CONTRACT
================================================================================

── 9.1  CONTRACT TESTS (run in both services' CI) ──────────────────

  SCHEMA COMPATIBILITY:
    • Every PR to event-schemas that touches community.events.*
      runs Confluent SR compat check (BACKWARD_TRANSITIVE, res4
      §3.4).
    • Feed's CI fetches the latest community.events schemas,
      generates deserializers, runs unit tests. Schema break →
      Feed CI fails → PR author on Community team is pinged.

  PRODUCER CONTRACT TEST (in Community's CI):
    • Community's test suite includes
      "when I create a community post, I emit a
       CommunityPostCreatedV1 that validates against the
       registered schema AND has these required semantic
       properties: post_id is a UUIDv7, created_at ≤ NOW(),
       member_count_at_post ≥ 0, …"

  CONSUMER CONTRACT TEST (in Feed's CI):
    • Feed's test suite includes
      "when I receive a valid CommunityPostCreatedV1, I emit
       N timeline.write commands where N = len(members in cache)."
    • Uses fixture payloads checked into event-schemas repo
      (examples/ directory). Both teams update fixtures together.

── 9.2  INTEGRATION TEST (staging) ─────────────────────────────────

  Automated, runs nightly:

    1. Create a test community via Community API.
    2. Add 10 test users as members via Community API.
    3. Wait 5s (event propagation).
    4. Assert: Feed's community_members_cache has 10 rows for
       this community.
    5. Post in the community via Community API.
    6. Wait 5s.
    7. Assert: all 10 test users' Redis timelines contain the
       post_id.
    8. Remove 1 member via Community API.
    9. Wait 30s.
    10. Assert: that user's timeline no longer contains the post.
    11. Delete the community via Community API.
    12. Wait 30s.
    13. Assert: community_members_cache has 0 rows for this
        community. All 9 remaining users' timelines no longer
        contain the post.
    14. Cleanup test users/communities.

── 9.3  CHAOS TEST (staging, monthly) ─────────────────────────────

  • Run the integration test while killing the feed-community-
    consumer pod mid-flow. Assert: on restart, all assertions
    eventually pass (idempotency + offset resume).
  • Run the integration test while Community Service is down.
    Assert: steps 4, 7, 10, 13 eventually pass after Community
    recovers (events queued in Kafka, processed on recovery).

================================================================================
§10  WHOLE-PLAN SUMMARY
================================================================================

┌──────────────────────┬───────────────────────────────────────────────────┐
│ PRINCIPLE            │ Community is UPSTREAM of Feed. One-way async      │
│                      │ (Community → Feed events) + narrow sync fallback  │
│                      │ (Feed → Community gRPC for authz-critical checks).│
│                      │ Community never depends on Feed. No cycles.       │
├──────────────────────┼───────────────────────────────────────────────────┤
│ ASYNC CHANNEL        │ Topic: community.events (compacted,               │
│                      │ key=community_id, 12 partitions).                 │
│                      │ 7 event types. Each has a fully-specified Avro    │
│                      │ payload (§4). Feed runs a dedicated consumer      │
│                      │ group that upserts a local membership cache +     │
│                      │ drives timeline fan-out/purge/backfill.           │
├──────────────────────┼───────────────────────────────────────────────────┤
│ SYNC CHANNEL         │ Feed → Community gRPC: IsMemberBatch,             │
│                      │ GetMemberIds (streaming), GetCommunityMetaBatch,  │
│                      │ GetRecentPosts. Used ONLY for (a) write-path      │
│                      │ authz where cache staleness is unacceptable,      │
│                      │ (b) cache-miss fallback. Circuit-breakered.       │
│                      │ Community down → Feed degrades gracefully         │
│                      │ (writes fail closed, reads use stale cache).      │
├──────────────────────┼───────────────────────────────────────────────────┤
│ DATA SHAPE           │ All events wrapped in EventEnvelope (event_id,    │
│                      │ correlation_id, causation_id, occurred_at).       │
│                      │ Payloads carry ENOUGH for Feed to act without     │
│                      │ round-trips in the common case (body_preview,     │
│                      │ member_count_at_post for celebrity detection).    │
│                      │ Timeline entries encode source (c|p) + origin_id  │
│                      │ so purge-on-leave doesn't need a full scan.       │
├──────────────────────┼───────────────────────────────────────────────────┤
│ DELAY SEMANTICS      │ p99 end-to-end: 5s for post visibility, 30s for   │
│                      │ membership changes. User experience during the    │
│                      │ gap is either invisible (optimistic UI, gRPC      │
│                      │ fallback on cache miss) or cosmetic (stale badge).│
│                      │ Writes always go through Community's              │
│                      │ authoritative DB, so kicked users can't post      │
│                      │ even during Feed's cache lag.                     │
├──────────────────────┼───────────────────────────────────────────────────┤
│ ERROR HANDLING       │ Idempotency: processed_events table (PG, same tx  │
│                      │ as cache update) — crash-safe, replay-safe.       │
│                      │                                                   │
│                      │ Retry ladder: 5 inline attempts with exp backoff, │
│                      │ then DLT. Transient (PG/Redis/gRPC unavailable)   │
│                      │ → retry. Permanent (bad payload, unknown type)    │
│                      │ → skip or DLT immediately.                        │
│                      │                                                   │
│                      │ Partial failures: re-emit everything, rely on     │
│                      │ downstream idempotency (ZADD). Simple > clever.   │
│                      │                                                   │
│                      │ Community outage: Feed keeps serving personal     │
│                      │ feeds normally. Community features degrade        │
│                      │ (writes 503, reads stale). Bounded blast radius.  │
├──────────────────────┼───────────────────────────────────────────────────┤
│ ORDERING             │ Per-community ordering guaranteed (partition      │
│                      │ key = community_id). joined-before-left,          │
│                      │ created-before-deleted always hold.               │
│                      │ Cross-community: not guaranteed, not needed.      │
│                      │ Slow-handler race (backfill vs purge): fixed by   │
│                      │ precondition check before slow side effects.      │
├──────────────────────┼───────────────────────────────────────────────────┤
│ LOCAL CACHE          │ community_members_cache + community_meta_cache in │
│                      │ Feed PG. Event-maintained (UPSERT/DELETE).        │
│                      │ Rebuildable in ~1 min via compacted-topic replay. │
│                      │ Staleness < 1s normal, bounded only by consumer   │
│                      │ lag. Used as hint for reads, NOT as authority for │
│                      │ writes (gRPC fallback for write-path authz).      │
├──────────────────────┼───────────────────────────────────────────────────┤
│ TESTING              │ Schema compat in CI (both sides).                 │
│                      │ Fixture-based contract tests (shared examples/).  │
│                      │ Nightly integration test on staging (full flow).  │
│                      │ Monthly chaos test (consumer kill, Community      │
│                      │ kill — assert eventual correctness).              │
└──────────────────────┴───────────────────────────────────────────────────┘

  WHY THIS PLAN WORKS

    1. CLEAR OWNERSHIP — Community owns membership. Feed owns
       timelines. The integration is a one-way stream of facts
       ("this changed") that Feed reacts to. No shared mutable
       state, no split-brain.

    2. ASYNC BY DEFAULT — Community posts, joins, leaves all
       propagate via Kafka. Community's HTTP latency never waits
       on Feed. Feed's latency never waits on Community (except
       on the narrow authz path, where it's a deliberate trade).

    3. IDEMPOTENT EVERYWHERE — Every handler can be replayed.
       Every Redis write is naturally idempotent. The processed_
       events table closes the loop for handlers with non-
       idempotent side effects. Retry is always safe.

    4. BOUNDED BLAST RADIUS — Community outage degrades a FEATURE
       (community posts in feeds), not the PRODUCT (home feed
       still shows personal posts). Feed outage doesn't affect
       Community at all (one-way dependency).

    5. RECOVERABLE — Compacted topic means the membership cache
       can be rebuilt from scratch in ~1 minute. DLT captures
       poison messages for human inspection. No permanent
       divergence possible.

════════════════════════════════════════════════════════════════════════════════
END
════════════════════════════════════════════════════════════════════════════════
