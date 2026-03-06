================================================================================
ASTU CONNECT — BACKEND ARCHITECTURE PLAN
Microservices + Clean Architecture for Feed, Chat, and Community
================================================================================

Author: Backend Architecture Proposal
Scope:  Service decomposition, Clean Architecture layering, inter‑service
        communication, data storage, and scaling strategy for high student
        traffic. No code — design only.

--------------------------------------------------------------------------------
1. HIGH‑LEVEL SYSTEM TOPOLOGY
--------------------------------------------------------------------------------

                             ┌──────────────────────┐
   Mobile / Web Clients ───► │     API Gateway      │
                             │ (routing, authN,     │
                             │  rate‑limit, TLS)    │
                             └─────────┬────────────┘
                                       │  (HTTP/REST + WebSocket upgrade)
          ┌────────────────────────────┼────────────────────────────────┐
          ▼                            ▼                                ▼
 ┌──────────────────┐        ┌──────────────────┐            ┌──────────────────┐
 │  Feed Service    │        │  Chat Service    │            │ Community Service│
 │  (stateless)     │        │  (stateful WS)   │            │  (stateless)     │
 └────────┬─────────┘        └────────┬─────────┘            └────────┬─────────┘
          │                           │                               │
          │        ┌──────────────────┴───────────┐                   │
          │        │                              │                   │
          ▼        ▼                              ▼                   ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                        Message Broker (Kafka)                            │
 │   Topics: user.events, post.events, chat.events, community.events,       │
 │           notification.events, feed.fanout.commands                      │
 └──────────────────────────────────────────────────────────────────────────┘
          │                           │                               │
          ▼                           ▼                               ▼
 ┌──────────────────┐        ┌──────────────────┐            ┌──────────────────┐
 │ Feed DB (Postgres│        │ Chat DB          │            │ Community DB     │
 │ + Redis cache    │        │ (Cassandra/Scylla│            │ (Postgres        │
 │ + Redis timeline)│        │ + Redis presence)│            │ + Redis cache)   │
 └──────────────────┘        └──────────────────┘            └──────────────────┘

Supporting Cross‑Cutting Services (not owned by any one bounded context):
  • Identity / Auth Service  — issues JWTs, validates ASTU student accounts
  • Notification Service     — consumes *.events, pushes FCM / email
  • Media Service            — presigned uploads to object storage (S3/MinIO)
  • Search Service           — Elasticsearch, fed by Kafka event stream

Core principle: each service owns its data. No service reads another
service’s database directly. All cross‑boundary data flows through
either (a) synchronous API calls via the gateway / internal gRPC, or
(b) asynchronous domain events on Kafka.

--------------------------------------------------------------------------------
2. CLEAN ARCHITECTURE — APPLIED PER SERVICE
--------------------------------------------------------------------------------

Every service (Feed, Chat, Community) follows the same 4‑ring layout.
Dependencies always point inward. Outer rings depend on inner rings,
never the reverse.

  ┌─────────────────────────────────────────────────────────────────┐
  │  FRAMEWORKS & DRIVERS  (outermost)                              │
  │    • HTTP controllers / gRPC handlers / WebSocket handlers      │
  │    • Kafka consumers & producers (concrete clients)             │
  │    • Postgres / Cassandra / Redis repository implementations    │
  │    • Config, DI wiring, server bootstrap                        │
  │  ┌─────────────────────────────────────────────────────────┐    │
  │  │  INTERFACE ADAPTERS                                     │    │
  │  │    • Controllers → translate HTTP req → UseCase input   │    │
  │  │    • Presenters  → translate UseCase output → HTTP res  │    │
  │  │    • Repository adapters → implement domain ports using │    │
  │  │      concrete drivers from the outer layer              │    │
  │  │    • Event mappers → domain event ↔ Kafka message       │    │
  │  │  ┌───────────────────────────────────────────────────┐  │    │
  │  │  │  APPLICATION / USE CASES                          │  │    │
  │  │  │    • One class/function per user intent           │  │    │
  │  │  │      e.g. CreatePost, FetchTimeline, SendMessage, │  │    │
  │  │  │           JoinCommunity, ModeratePost             │  │    │
  │  │  │    • Orchestrates entities + ports                │  │    │
  │  │  │    • Emits domain events (via an abstract port)   │  │    │
  │  │  │    • Holds transaction boundaries                 │  │    │
  │  │  │  ┌─────────────────────────────────────────────┐  │  │    │
  │  │  │  │  DOMAIN / ENTITIES  (innermost)             │  │  │    │
  │  │  │  │    • Pure business objects: Post, Comment,  │  │  │    │
  │  │  │  │      Timeline, Conversation, Message,       │  │  │    │
  │  │  │  │      Community, Membership, Role            │  │  │    │
  │  │  │  │    • Invariants & validation rules          │  │  │    │
  │  │  │  │    • Zero knowledge of DB, HTTP, Kafka      │  │  │    │
  │  │  │  └─────────────────────────────────────────────┘  │  │    │
  │  │  └───────────────────────────────────────────────────┘  │    │
  │  └─────────────────────────────────────────────────────────┘    │
  └─────────────────────────────────────────────────────────────────┘

Key ports (interfaces) defined in the Application layer,
implemented in the Adapters/Drivers layers:

  • PostRepository, TimelineRepository, CommentRepository   (Feed)
  • ConversationRepository, MessageRepository, PresencePort (Chat)
  • CommunityRepository, MembershipRepository, RolePort     (Community)
  • EventPublisher  — abstracts Kafka
  • UserProfilePort — abstracts calls to Identity service
  • MediaPort       — abstracts calls to Media service

Because the domain + use‑case layers have no framework dependencies,
we can:
  – Unit‑test business rules without spinning up infrastructure.
  – Swap Postgres → CockroachDB, or Kafka → NATS, by rewriting only
    the outer adapter, leaving business logic untouched.
  – Run the same use‑cases from HTTP, gRPC, CLI, or a Kafka consumer.

--------------------------------------------------------------------------------
3. SERVICE RESPONSIBILITIES & BOUNDED CONTEXTS
--------------------------------------------------------------------------------

3.1 FEED SERVICE
    Owns:      Posts, Comments, Reactions, Timelines (home feed).
    Use cases: CreatePost, DeletePost, ReactToPost, CommentOnPost,
               FetchHomeTimeline, FetchUserProfileFeed.
    Emits:     post.created, post.deleted, post.reacted, comment.created
    Consumes:  user.followed, user.unfollowed, community.post.created
               (to ingest community posts into members’ timelines)

3.2 CHAT SERVICE
    Owns:      Conversations (1:1 and group), Messages, Delivery receipts,
               Typing indicators, Presence.
    Use cases: StartConversation, SendMessage, MarkAsRead,
               FetchConversationHistory, SubscribeToPresence.
    Emits:     message.sent, message.read, conversation.created
    Consumes:  user.blocked (to enforce messaging restrictions),
               community.member.joined (to auto‑add to community group chat)

3.3 COMMUNITY SERVICE
    Owns:      Communities (departments, clubs, dorm groups),
               Memberships, Roles (admin/mod/member), Community posts,
               Join requests, Moderation actions.
    Use cases: CreateCommunity, JoinCommunity, LeaveCommunity,
               PostInCommunity, ModeratePost, AssignRole.
    Emits:     community.created, community.member.joined,
               community.member.left, community.post.created,
               community.post.removed
    Consumes:  user.created (to auto‑enroll in department community)

3.4 IDENTITY SERVICE (supporting)
    Owns:      User accounts, ASTU student ID verification, JWT issuance,
               Follow graph (who follows whom).
    Emits:     user.created, user.followed, user.unfollowed, user.blocked

--------------------------------------------------------------------------------
4. INTER‑SERVICE COMMUNICATION
--------------------------------------------------------------------------------

We use a **hybrid model**: synchronous for user‑facing request paths
that need an immediate answer, asynchronous for everything that can be
eventually consistent.

4.1 SYNCHRONOUS (gRPC internally, REST at the edge)

    Client → API Gateway → Service (direct)
      • GET /feed/timeline          → Feed Service
      • POST /chat/messages         → Chat Service
      • GET /communities/{id}       → Community Service

    Service → Service (internal gRPC, only when strictly needed)
      • Feed → Identity: “give me display name + avatar for userIds[…]”
        (batched, cached heavily — see §6)
      • Community → Identity: validate that requester is an ASTU student
        before creating a community.

    Rules:
      – Sync calls are allowed ONLY for read‑side enrichment or
        authorization checks that must block the response.
      – Never chain more than one sync hop per user request
        (prevents cascading latency & failure).
      – Every sync call has a circuit breaker + timeout + fallback
        (e.g., if Identity is down, Feed returns posts with cached
        author snapshots instead of failing).

4.2 ASYNCHRONOUS (Kafka domain events)

    All state changes publish an immutable event to Kafka.
    Consumers subscribe and update their own local read models.

    Example flows:

    (a) Student creates a post
        Client → POST /feed/posts → Feed Service
        Feed Service:
          1. Validate via CreatePost use case
          2. Persist Post in Feed DB (Postgres)
          3. Publish post.created { postId, authorId, communityId?, ts }
        Downstream consumers of post.created:
          • Feed Fan‑out Worker → push postId into followers’ Redis
            timelines (see §6.2)
          • Notification Service → notify mentioned users
          • Search Service → index post content in Elasticsearch
          • Community Service (if communityId present) → increment
            community post counter in its own DB

    (b) Student joins a community
        Client → POST /communities/{id}/join → Community Service
        Community Service:
          1. JoinCommunity use case validates rules (capacity,
             department restriction, ban list)
          2. Persist Membership in Community DB
          3. Publish community.member.joined { userId, communityId }
        Downstream consumers:
          • Chat Service → add user to the community group conversation
          • Feed Service → backfill recent community posts into the
            user’s home timeline
          • Notification Service → notify community admins

    (c) Student sends a chat message
        Client (WebSocket) → Chat Service
        Chat Service:
          1. SendMessage use case validates membership + block list
          2. Persist Message in Cassandra
          3. Publish to Redis Pub/Sub channel conversation:{id} so all
             Chat Service replicas holding WS connections for that
             conversation push the message in real time
          4. Publish message.sent to Kafka for durable side effects
             (notifications to offline users, analytics)

4.3 EVENT CONTRACT DISCIPLINE

    • Events are versioned: post.created.v1, post.created.v2.
      Producers keep emitting the old version until all consumers
      migrate. Schema registry (e.g., Confluent Schema Registry or a
      simple JSON‑Schema repo) validates payloads at publish time.
    • Events carry IDs, not full objects. Consumers fetch extra data
      from the owning service (or their local cache) if needed. This
      keeps events small and avoids stale embedded data.
    • Every event has: eventId (UUID), occurredAt, producer service,
      and a correlationId propagated from the original HTTP request
      for distributed tracing.

--------------------------------------------------------------------------------
5. DATA STORAGE — POLYGLOT PERSISTENCE, ONE DB PER SERVICE
--------------------------------------------------------------------------------

Each service owns a private database. Cross‑service joins are forbidden;
data needed across boundaries is **replicated via events** into a local
read model.

5.1 FEED SERVICE STORAGE

    Primary store: PostgreSQL
      Tables (conceptual):
        posts(id, author_id, community_id NULL, body, media_refs[],
              created_at, deleted_at NULL, reaction_counts jsonb)
        comments(id, post_id, author_id, body, created_at)
        reactions(post_id, user_id, type, created_at)  PK(post_id,user_id)
        author_snapshots(user_id, display_name, avatar_url, updated_at)
          ← local cache of Identity data, refreshed by user.updated events

    Timeline store: Redis (Sorted Sets)
        Key:   timeline:{userId}
        Value: ZSET of (postId, score=createdAtEpoch)
        Capped to last ~800 entries per user. Older entries fall back
        to a Postgres query (pull model).

    Why Postgres + Redis:
        Posts/comments are relational, need transactions and
        secondary indexes (by author, by community). Timelines are
        write‑heavy, ordered, and read extremely frequently — Redis
        sorted sets are ideal and avoid hammering Postgres on every
        feed refresh.

5.2 CHAT SERVICE STORAGE

    Primary store: Cassandra (or ScyllaDB)
      Tables (conceptual, partition key in **bold**):
        messages_by_conversation(**conversation_id**, message_id TIMEUUID,
                                 sender_id, body, media_refs[], sent_at)
          CLUSTERING ORDER BY (message_id DESC)
        conversations_by_user(**user_id**, conversation_id,
                              last_message_at, unread_count)
        conversation_members(**conversation_id**, user_id, role,
                             joined_at)

    Presence / ephemeral state: Redis
        presence:{userId}        → online/away/offline, TTL 30s, heart‑beated
        typing:{conversationId}  → set of userIds currently typing, TTL 5s
        ws_route:{userId}        → which Chat replica holds this user’s
                                   WebSocket (for direct routing)

    Why Cassandra:
        Chat history is append‑only, time‑ordered, and must scale to
        billions of rows with predictable low‑latency reads by
        partition (conversation). Cassandra’s wide‑row model fits
        perfectly and scales horizontally by adding nodes. We don’t
        need cross‑partition transactions here.

5.3 COMMUNITY SERVICE STORAGE

    Primary store: PostgreSQL
      Tables (conceptual):
        communities(id, name, slug, description, type, department_code,
                    member_count, created_by, created_at)
        memberships(community_id, user_id, role, status, joined_at)
          PK(community_id, user_id)
        community_posts(id, community_id, author_id, body, pinned,
                        created_at, removed_at NULL)
        moderation_log(id, community_id, actor_id, action, target_type,
                       target_id, reason, created_at)
        join_requests(id, community_id, user_id, status, created_at)

    Cache: Redis
        community:{id}:meta       → hot community metadata
        community:{id}:members    → cached member set for fast
                                    “is user a member?” checks

    Why Postgres:
        Communities involve relational integrity (roles, join requests,
        moderation logs referencing users and posts), and moderate
        write volume. Postgres with proper indexes handles this well;
        we add read replicas before considering anything more exotic.

5.4 SHARED INFRASTRUCTURE (not service‑owned)

    • Object Storage (S3/MinIO) — all media. Services store only
      object keys, never binary blobs in their DBs.
    • Elasticsearch — global search across posts, communities, users.
      Fed entirely by Kafka consumers; no service writes to it
      directly from the request path.
    • Kafka — durable log, 7‑day retention minimum, partitioned by
      entity ID (postId, conversationId, communityId) so ordering is
      preserved per entity.

--------------------------------------------------------------------------------
6. HANDLING HIGH STUDENT VOLUME
--------------------------------------------------------------------------------

Assumed peak load (one large university, generous headroom):
  ~30,000 registered students
  ~12,000 concurrently online at peak (exam weeks, registration days)
  Feed reads:   ~2,000 req/s peak (timeline refreshes)
  Chat messages: ~500 msg/s peak, bursty
  Community writes: low (~50 req/s) but read‑heavy

6.1 STATELESS HORIZONTAL SCALING

    • Feed Service and Community Service are stateless HTTP services.
      Run N replicas behind the API Gateway; autoscale on CPU + p95
      latency. Because Clean Architecture keeps all state behind
      repository ports, any replica can serve any request.

    • Chat Service is *session‑stateful* (holds WebSockets). We still
      scale horizontally; a user may connect to any replica. The
      replica registers itself in Redis (ws_route:{userId}) so other
      replicas can forward messages. Redis Pub/Sub (or a dedicated
      Kafka topic) broadcasts messages to whichever replica holds the
      recipient’s socket.

6.2 FEED FAN‑OUT STRATEGY (the hardest scaling problem)

    Problem: when a popular student (e.g., Student Union president,
    5,000 followers) posts, we must update 5,000 timelines.

    We use a **hybrid push/pull model**:

      Push (fan‑out‑on‑write) — default path
        post.created → Feed Fan‑out Worker consumes → looks up
        follower list (cached) → for each follower with < THRESHOLD
        (e.g., 1,000) followers‑of‑the‑author, ZADD postId into
        timeline:{followerId} in Redis. Batched pipeline writes,
        ~10k ZADDs/sec per Redis node is trivial.

      Pull (fan‑out‑on‑read) — for “celebrity” authors
        Authors with follower_count > THRESHOLD are flagged. Their
        posts are NOT pushed. Instead, FetchHomeTimeline merges:
          (a) the user’s Redis sorted‑set (pushed posts), and
          (b) a small Postgres query: “latest posts from the
              celebrity accounts I follow”
        Merge happens in memory, sorted by timestamp, paginated.

      This caps fan‑out write amplification at THRESHOLD × post‑rate,
      keeping Redis and worker CPU bounded even if one account gains
      huge followership.

6.3 CACHING LAYERS

    • API Gateway caches GET /communities/{id} and
      GET /users/{id}/profile for 30s (public, stale‑while‑revalidate).
    • Each service maintains an in‑process LRU for ultra‑hot keys
      (e.g., “is user X a member of community Y?”) with a 5s TTL,
      backed by Redis, backed by Postgres. Three tiers: process →
      Redis → DB.
    • Author snapshots in Feed DB (see §5.1) mean FetchTimeline never
      calls Identity synchronously in the hot path — it reads local
      denormalized data kept fresh by user.updated events.

6.4 DATABASE SCALING

    Postgres (Feed, Community):
      Step 1: Read replicas. All GET queries go to replicas; writes
              go to primary. Clean Architecture’s repository port
              makes routing trivial (ReadRepository vs WriteRepository).
      Step 2: Connection pooling (PgBouncer) in front of each DB.
      Step 3 (if ever needed): partition posts table by month
              (declarative partitioning), so hot data stays small.

    Cassandra (Chat):
      Scales linearly — add nodes, rebalance. Partition key
      (conversation_id) ensures even distribution since conversations
      are numerous and roughly uniform in size. We set a tombstone
      GC grace tuned for chat deletion patterns.

    Redis:
      Start single‑node per service. Move to Redis Cluster if memory
      or throughput exceeds one node. Timeline keys shard naturally
      by userId.

6.5 BACKPRESSURE & RESILIENCE

    • Kafka decouples producers from consumers. If the Fan‑out Worker
      falls behind, posts still succeed (they’re in Postgres); feeds
      just update with a few seconds’ delay. Consumers track lag;
      autoscale workers on lag > threshold.
    • Every sync inter‑service call has:
        – timeout (≤ 200ms internal)
        – circuit breaker (open after N failures, half‑open probe)
        – fallback (serve cached/denormalized data, or degrade
          gracefully — e.g., show post without author avatar)
    • Rate limiting at the gateway: per‑user token bucket
      (e.g., 60 writes/min, 600 reads/min). Prevents a misbehaving
      client from overwhelming any single service.
    • Idempotency keys on all write endpoints (POST /feed/posts,
      POST /chat/messages) so client retries don’t create duplicates.
      Use‑case layer checks an idempotency store (Redis, 24h TTL)
      before executing.

6.6 OBSERVABILITY (required to operate at scale)

    • Distributed tracing: correlationId generated at gateway,
      propagated through HTTP headers, gRPC metadata, and Kafka
      message headers. OpenTelemetry exporters in every service.
    • Metrics: per‑use‑case latency histograms, Kafka consumer lag,
      Redis hit ratio, DB connection pool saturation.
    • Structured logs: JSON, tagged with service, useCase,
      correlationId. Centralized in Loki/ELK.

--------------------------------------------------------------------------------
7. DEPLOYMENT & EVOLUTION NOTES
--------------------------------------------------------------------------------

  • One repository per service (or a monorepo with strict module
    boundaries). Each service builds an independent container image.
  • Kubernetes (or any orchestrator) with:
      – HorizontalPodAutoscaler per service
      – PodDisruptionBudgets so rolling deploys don’t drop all
        WebSocket connections at once
      – Separate node pools for stateful (Cassandra/Redis/Kafka)
        vs stateless workloads.
  • Database migrations are owned by the service that owns the DB.
    Never run a migration from another service.
  • To add a new feature (e.g., “Events & RSVP”), create a new
    service with the same Clean Architecture skeleton, subscribe to
    the events it needs (user.created, community.member.joined),
    emit its own events. Existing services remain untouched.

--------------------------------------------------------------------------------
8. SUMMARY — WHY THIS DESIGN MEETS THE GOALS
--------------------------------------------------------------------------------

  Scalability
    – Stateless service replicas scale on demand.
    – Polyglot persistence: each workload gets the right storage engine.
    – Hybrid fan‑out bounds write amplification.
    – Kafka absorbs bursts; consumers scale independently of producers.

  Maintainability
    – Clean Architecture isolates business rules from infrastructure;
      swapping a DB or message broker touches one adapter, not the
      domain.
    – Event‑driven integration means services evolve independently;
      adding a consumer never requires changing the producer.
    – One DB per service eliminates hidden coupling via shared schemas.

  Reliability
    – Async by default → no cascading failures.
    – Circuit breakers + fallbacks on every sync call.
    – Idempotent writes + at‑least‑once event delivery = safe retries.

================================================================================
END OF PLAN
================================================================================
