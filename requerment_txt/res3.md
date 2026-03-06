════════════════════════════════════════════════════════════════════════════════
EPIC: ASTU-CONNECT-ARCH-001
TITLE: ASTU Connect Microservices Platform — Architecture & Delivery Spec
TYPE:  Architecture Epic
STATUS: Draft for review
════════════════════════════════════════════════════════════════════════════════

──────────────────────────────────────────────────────────────────────────────
§0  EPIC SUMMARY
──────────────────────────────────────────────────────────────────────────────

GOAL
  Deliver a horizontally scalable, event-driven backend for ASTU Connect
  composed of three core bounded-context services (Feed, Chat, Community)
  built on Clean Architecture, communicating via REST/gRPC (sync) and
  Kafka (async), each owning its datastore, behind a shared API Gateway.

BUSINESS OUTCOME
  • Serve the full ASTU student body (~30k) with a social platform that
    stays responsive at peak academic-calendar traffic.
  • Enable independent team ownership and independent deployment per
    service.
  • Keep the cost of change low: infrastructure swaps and new features
    must not ripple across service boundaries.

IN SCOPE
  • Service decomposition, API contracts, event contracts, data models.
  • Non-functional targets (latency, availability, durability, capacity).
  • Caching, fan-out, resilience, observability.
  • Rollout phases, risks, mitigations, acceptance criteria.

OUT OF SCOPE
  • Mobile/web client implementation.
  • ASTU SSO integration details (separate epic).
  • Analytics pipeline and ML ranking (future epic).

──────────────────────────────────────────────────────────────────────────────
§1  C4 — LEVEL 1 — SYSTEM CONTEXT DIAGRAM
──────────────────────────────────────────────────────────────────────────────

Shows ASTU Connect as a single system box, its users, and external systems.

  ┌──────────────────────────────────────────────────────────────────────────┐
  │                                                                          │
  │    ┌─────────────┐                                  ┌─────────────────┐  │
  │    │   Student   │  uses web/mobile app to post,    │  ASTU Registrar │  │
  │    │  (Person)   │  chat, join communities          │  System (Ext)   │  │
  │    └──────┬──────┘                                  └────────┬────────┘  │
  │           │ HTTPS / WSS                                      │           │
  │           ▼                                                  │           │
  │  ┌──────────────────────────────────────────────────────┐    │ verifies  │
  │  │                                                      │◄───┘ student   │
  │  │              ASTU CONNECT PLATFORM                   │      IDs       │
  │  │     (Software System — this epic)                    │                │
  │  │                                                      │                │
  │  │   Feed · Chat · Community · Identity · Notification  │                │
  │  │   Media · Search                                     │                │
  │  │                                                      │────┐ sends     │
  │  └──────────────────────────────────────────────────────┘    │ push      │
  │           ▲                             │                    ▼           │
  │           │ moderates content           │          ┌──────────────────┐  │
  │    ┌──────┴──────┐                      │          │ Firebase Cloud   │  │
  │    │  Moderator  │                      │          │ Messaging (Ext)  │  │
  │    │  (Person)   │                      │          └──────────────────┘  │
  │    └─────────────┘               stores │                                │
  │                                  media  ▼                                │
  │                          ┌──────────────────────┐                        │
  │                          │  Object Storage      │                        │
  │                          │  S3 / MinIO (Ext)    │                        │
  │                          └──────────────────────┘                        │
  │                                                                          │
  └──────────────────────────────────────────────────────────────────────────┘

  ACTORS
    Student     — primary user; reads feed, sends messages, joins communities.
    Moderator   — student with elevated role in one or more communities.

  EXTERNAL SYSTEMS
    ASTU Registrar   — authoritative source for student enrolment;
                       queried at signup to verify student ID.
    FCM              — push notification delivery to mobile devices.
    Object Storage   — durable blob store for photos/videos.

──────────────────────────────────────────────────────────────────────────────
§2  C4 — LEVEL 2 — CONTAINER DIAGRAM
──────────────────────────────────────────────────────────────────────────────

Zooms into the ASTU Connect Platform box. Each box is a separately
deployable unit (container image / process). Arrows show primary
runtime dependencies.

  LEGEND:   ──►  sync (HTTP/gRPC)     ──▷  async (Kafka produce/consume)
            ═══  WebSocket            [DB] datastore owned by container

┌────────────────────────────────────────────────────────────────────────────────┐
│ ASTU CONNECT PLATFORM                                                          │
│                                                                                │
│   ┌───────────────┐                                                            │
│   │  Web / Mobile │                                                            │
│   │    Clients    │                                                            │
│   └───────┬───────┘                                                            │
│     HTTPS │ WSS                                                                │
│           ▼                                                                    │
│   ┌───────────────────────────┐                                                │
│   │   API GATEWAY             │  • TLS termination                             │
│   │   (Kong / Envoy)          │  • JWT validation                              │
│   │                           │  • Rate limiting (token bucket per user)       │
│   │                           │  • Request routing                             │
│   │                           │  • Response caching (public GETs)              │
│   └──┬─────────┬─────────┬────┘                                                │
│      │         │         │                                                     │
│ REST │    WSS  │═══╗ REST│                                                     │
│      ▼         ▼   ║     ▼                                                     │
│ ┌──────────┐ ┌──────────┐ ┌──────────────┐    ┌──────────────┐                 │
│ │  FEED    │ │  CHAT    │ │  COMMUNITY   │    │  IDENTITY    │                 │
│ │  SERVICE │ │  SERVICE │ │  SERVICE     │    │  SERVICE     │                 │
│ │          │ │          │ │              │    │              │                 │
│ │ Clean    │ │ Clean    │ │ Clean Arch   │    │ Clean Arch   │                 │
│ │ Arch     │ │ Arch     │ │              │    │              │                 │
│ └─┬──┬──┬──┘ └─┬──┬──┬──┘ └──┬──┬──┬─────┘    └──┬──┬──┬─────┘                 │
│   │  │  │      │  │  │       │  │  │             │  │  │                       │
│   │  │  │ gRPC │  │  │  gRPC │  │  │             │  │  │                       │
│   │  │  └──────┼──┼──┼───────┼──┼──┼─────────────┘  │  │                       │
│   │  │         │  │  │       │  │  │ (GetUserBatch, │  │                       │
│   │  │         │  │  │       │  │  │  VerifyStudent)│  │                       │
│   │  │         │  │  │       │  │  │                │  │                       │
│   │  │ ──▷     │  │──▷       │  │──▷               │──▷                        │
│   │  ▼         │  ▼          │  ▼                  ▼                           │
│   │ ┌────────────────────────────────────────────────────────────────────┐     │
│   │ │                       KAFKA CLUSTER                                │     │
│   │ │  Topics: user.events · post.events · comment.events ·              │     │
│   │ │          message.events · community.events · feed.fanout.cmd       │     │
│   │ │  • 3 brokers, RF=3, min.insync.replicas=2, 7-day retention         │     │
│   │ └────────────────────────────────────────────────────────────────────┘     │
│   │    ▲──▷          ▲──▷          ▲──▷              ▲──▷                      │
│   │    │             │             │                 │                         │
│   │ ┌──┴────────┐ ┌──┴─────────┐ ┌─┴────────────┐ ┌──┴─────────┐               │
│   │ │ FEED      │ │ NOTIFICA-  │ │ SEARCH       │ │ MEDIA      │               │
│   │ │ FAN-OUT   │ │ TION       │ │ INDEXER      │ │ SERVICE    │               │
│   │ │ WORKER    │ │ SERVICE    │ │              │ │            │               │
│   │ │           │ │            │ │              │ │ (presigned │               │
│   │ │ consumes  │ │ consumes   │ │ consumes     │ │  URL       │               │
│   │ │ post.*    │ │ all *.evts │ │ post.*,      │ │  issuer)   │               │
│   │ │ writes    │ │ → FCM      │ │ community.*  │ │            │               │
│   │ │ Redis TL  │ │            │ │ → ES         │ │            │               │
│   │ └───────────┘ └────────────┘ └──────────────┘ └────────────┘               │
│   │                                                                            │
│   │  DATASTORES (each owned by exactly one service)                            │
│   ▼                                                                            │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│ │ [Feed DB]    │ │ [Chat DB]    │ │ [Community   │ │ [Identity    │            │
│ │ PostgreSQL   │ │ Cassandra    │ │  DB]         │ │  DB]         │            │
│ │ + 2 read     │ │ 3-node       │ │ PostgreSQL   │ │ PostgreSQL   │            │
│ │ replicas     │ │ cluster      │ │ + 1 replica  │ │              │            │
│ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘            │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                             │
│ │ [Feed Cache] │ │ [Chat State] │ │ [Search      │                             │
│ │ Redis        │ │ Redis        │ │  Index]      │                             │
│ │ • timelines  │ │ • presence   │ │ Elastic-     │                             │
│ │ • hot posts  │ │ • typing     │ │ search       │                             │
│ │              │ │ • WS routes  │ │ 3-node       │                             │
│ └──────────────┘ └──────────────┘ └──────────────┘                             │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘

  CONTAINER INVENTORY

  ┌────────────────────┬──────────────┬────────────────────────────────────────┐
  │ Container          │ Tech         │ Responsibility                         │
  ├────────────────────┼──────────────┼────────────────────────────────────────┤
  │ API Gateway        │ Kong/Envoy   │ Edge: TLS, JWT verify, rate-limit,     │
  │                    │              │ route, cache public GETs               │
  │ Feed Service       │ App runtime  │ Posts, comments, reactions, timeline   │
  │                    │ (stateless)  │ reads. REST (edge) + gRPC (internal).  │
  │ Feed Fan-out Worker│ App runtime  │ Consumes post.events → writes Redis    │
  │                    │ (stateless)  │ timelines. Horizontally scaled.        │
  │ Chat Service       │ App runtime  │ WS gateway + message persistence +     │
  │                    │ (WS stateful)│ presence. Routes via Redis.            │
  │ Community Service  │ App runtime  │ Communities, memberships, roles,       │
  │                    │ (stateless)  │ moderation.                            │
  │ Identity Service   │ App runtime  │ Auth, JWT issuance, follow graph,      │
  │                    │ (stateless)  │ ASTU student verification.             │
  │ Notification Svc   │ App runtime  │ Consumes all events → FCM / email.     │
  │ Media Service      │ App runtime  │ Issues presigned upload URLs;          │
  │                    │ (stateless)  │ validates media metadata.              │
  │ Search Indexer     │ App runtime  │ Consumes events → writes Elasticsearch │
  │ Kafka Cluster      │ Kafka 3.x    │ Durable event log, 3 brokers, RF=3     │
  │ Feed DB            │ PostgreSQL   │ Posts, comments, reactions, author     │
  │                    │              │ snapshots. Primary + 2 read replicas.  │
  │ Feed Cache         │ Redis        │ Timeline ZSETs, hot-post cache.        │
  │ Chat DB            │ Cassandra    │ Messages (partition=conversation_id).  │
  │ Chat State         │ Redis        │ Presence, typing, WS routing table.    │
  │ Community DB       │ PostgreSQL   │ Communities, memberships, mod log.     │
  │ Identity DB        │ PostgreSQL   │ Users, credentials, follow edges.      │
  │ Search Index       │ Elasticsearch│ Full-text search across posts/comm/    │
  │                    │              │ users.                                 │
  │ Object Storage     │ S3 / MinIO   │ Media blobs (external system).         │
  └────────────────────┴──────────────┴────────────────────────────────────────┘

──────────────────────────────────────────────────────────────────────────────
§3  NON-FUNCTIONAL REQUIREMENTS
──────────────────────────────────────────────────────────────────────────────

All latencies measured at the API Gateway (end-to-end, excluding client
network). All percentiles computed over rolling 5-minute windows.

  ┌───────────────────────────┬─────────┬─────────┬─────────┬───────────────┐
  │ Operation                 │   p50   │   p95   │   p99   │   Max (hard)  │
  ├───────────────────────────┼─────────┼─────────┼─────────┼───────────────┤
  │ GET /feed/timeline        │  40 ms  │ 120 ms  │ 250 ms  │   1000 ms     │
  │ POST /feed/posts          │  60 ms  │ 180 ms  │ 350 ms  │   2000 ms     │
  │ POST /feed/posts/:id/     │  30 ms  │  90 ms  │ 200 ms  │   1000 ms     │
  │      reactions            │         │         │         │               │
  │ GET /feed/posts/:id/      │  35 ms  │ 100 ms  │ 220 ms  │   1000 ms     │
  │      comments             │         │         │         │               │
  │ WS message send→receive   │  50 ms  │ 150 ms  │ 300 ms  │   1000 ms     │
  │   (same DC, both online)  │         │         │         │               │
  │ GET /chat/conversations   │  45 ms  │ 130 ms  │ 280 ms  │   1000 ms     │
  │ GET /chat/conversations/  │  50 ms  │ 140 ms  │ 300 ms  │   1500 ms     │
  │      :id/messages         │         │         │         │               │
  │ GET /communities/:id      │  25 ms  │  80 ms  │ 180 ms  │   1000 ms     │
  │ POST /communities/:id/    │  70 ms  │ 200 ms  │ 400 ms  │   2000 ms     │
  │      join                 │         │         │         │               │
  │ GET /search?q=…           │  80 ms  │ 250 ms  │ 500 ms  │   2000 ms     │
  │ Feed fan-out end-to-end   │   —     │  2 s    │  5 s    │   30 s        │
  │   (post → visible in      │         │         │         │               │
  │    follower timeline)     │         │         │         │               │
  └───────────────────────────┴─────────┴─────────┴─────────┴───────────────┘

  AVAILABILITY TARGETS (monthly, per service, measured at gateway)

  ┌────────────────────┬─────────────┬───────────────────────┬──────────────┐
  │ Service            │   Target    │  Allowed downtime /mo │  Degraded    │
  │                    │             │                       │  mode allowed│
  ├────────────────────┼─────────────┼───────────────────────┼──────────────┤
  │ Identity / Auth    │   99.95 %   │       ~22 min         │  No — hard   │
  │                    │             │                       │  dependency  │
  │ Feed (read)        │   99.9  %   │       ~43 min         │  Yes: serve  │
  │                    │             │                       │  stale cache │
  │ Feed (write)       │   99.5  %   │       ~3.6 h          │  No          │
  │ Chat (send/recv)   │   99.9  %   │       ~43 min         │  Yes: queue  │
  │                    │             │                       │  locally,    │
  │                    │             │                       │  retry       │
  │ Community          │   99.5  %   │       ~3.6 h          │  Yes: cached │
  │                    │             │                       │  reads       │
  │ Search             │   99.0  %   │       ~7.2 h          │  Yes: hide   │
  │                    │             │                       │  search bar  │
  │ Notification       │   99.0  %   │       ~7.2 h          │  Yes: best-  │
  │                    │             │                       │  effort      │
  └────────────────────┴─────────────┴───────────────────────┴──────────────┘

  DURABILITY
    • No acknowledged write may be lost.
      – Postgres: synchronous replication to at least one standby
        before ACK (synchronous_commit=on, 1 sync replica).
      – Cassandra: writes at QUORUM (2 of 3 nodes).
      – Kafka: acks=all, min.insync.replicas=2, RF=3.
      – Redis timeline data is REBUILDABLE from Postgres; treated as
        a cache, not a source of truth. Loss = cold-start penalty,
        not data loss.

  CONSISTENCY MODEL
    • Within a service: strong consistency on primary writes.
    • Across services: eventual consistency via events.
      Target propagation lag: p99 ≤ 5 s (measured as Kafka consumer
      lag + processing time).

  SECURITY
    • All external traffic TLS 1.2+.
    • JWT (RS256) issued by Identity, validated at Gateway AND
      re-validated at each service (defense in depth).
    • Internal service-to-service traffic over mTLS.
    • Rate limits: 60 writes/min/user, 600 reads/min/user at gateway.
    • Media uploads via presigned URLs only; no proxy-through.

──────────────────────────────────────────────────────────────────────────────
§4  CAPACITY ASSUMPTIONS & SIZING
──────────────────────────────────────────────────────────────────────────────

  USER BASE
    Total registered students             30,000
    Peak concurrent (exam/registration)   12,000  (40%)
    Typical concurrent (weekday daytime)   6,000  (20%)
    Off-peak concurrent                    1,500  ( 5%)

  TRAFFIC — PEAK HOUR
    ┌──────────────────────────────────┬──────────┬────────────────────┐
    │ Operation                        │  req/s   │  Derivation        │
    ├──────────────────────────────────┼──────────┼────────────────────┤
    │ Timeline refresh (GET)           │  2,000   │ 12k users × 1      │
    │                                  │          │ refresh / 6s avg   │
    │ Post create (POST)               │     15   │ 12k × 0.3 posts/h  │
    │                                  │          │ / 3600 × 1.5 burst │
    │ Reaction (POST)                  │    100   │ 12k × 30 reacts/h  │
    │ Comment (POST)                   │     25   │ 12k × 7.5 cmnts/h  │
    │ Chat message send                │    500   │ 12k × 2.5 msg/min  │
    │                                  │          │ (incl. group chats)│
    │ Chat history page (GET)          │    200   │ 12k × 1 scroll/min │
    │ Presence heartbeat               │  1,200   │ 12k × 1/10s        │
    │ Community read (GET)             │    300   │                    │
    │ Community write (POST)           │     10   │                    │
    │ Search query (GET)               │     50   │                    │
    └──────────────────────────────────┴──────────┴────────────────────┘

    Peak total edge RPS:      ~4,400 req/s
    Design headroom:  ×3  →  ~13,000 req/s   (target capacity)

  KAFKA THROUGHPUT — PEAK
    ┌──────────────────────────┬──────────┬──────────┬─────────────────┐
    │ Topic                    │  msgs/s  │ avg size │  bytes/s        │
    ├──────────────────────────┼──────────┼──────────┼─────────────────┤
    │ post.events              │     15   │  500 B   │     7.5 KB/s    │
    │ comment.events           │     25   │  400 B   │    10   KB/s    │
    │ reaction.events          │    100   │  200 B   │    20   KB/s    │
    │ message.events           │    500   │  300 B   │   150   KB/s    │
    │ community.events         │     12   │  350 B   │     4   KB/s    │
    │ user.events              │      5   │  300 B   │     1.5 KB/s    │
    │ feed.fanout.cmd          │  3,000   │  150 B   │   450   KB/s    │
    │ (15 posts/s × avg 200    │          │          │                 │
    │  followers = 3000 cmds)  │          │          │                 │
    ├──────────────────────────┼──────────┼──────────┼─────────────────┤
    │ TOTAL                    │ ~3,660   │          │  ~640 KB/s      │
    └──────────────────────────┴──────────┴──────────┴─────────────────┘
    Trivial for a 3-broker Kafka cluster. Bottleneck is NOT Kafka.

  STORAGE — 1-YEAR PROJECTION
    ┌──────────────────────────┬─────────────────────────┬──────────────┐
    │ Store                    │  Growth calc            │  1-yr size   │
    ├──────────────────────────┼─────────────────────────┼──────────────┤
    │ Feed Postgres            │  15 posts/s × 600 B ×   │  ~280 GB     │
    │  (posts+comments+        │  avg-load-factor 0.3 ×  │  (incl.      │
    │   reactions, incl. idx)  │  86400 × 365 + comments │   indexes)   │
    │                          │  + reactions + indexes  │              │
    │ Chat Cassandra           │  500 msg/s × 400 B ×    │  ~1.9 TB     │
    │  (messages, RF=3         │  load-factor 0.3 ×      │  raw → ~5.7  │
    │   inflates on-disk)      │  86400 × 365            │  TB on disk  │
    │ Community Postgres       │  Low volume             │  ~15 GB      │
    │ Identity Postgres        │  30k users + follow     │  ~5 GB       │
    │                          │  edges (~200/user)      │              │
    │ Redis (Feed timelines)   │  30k users × 800        │  ~3 GB RAM   │
    │                          │  entries × 128 B        │              │
    │ Redis (Chat state)       │  Ephemeral, bounded     │  ~1 GB RAM   │
    │ Elasticsearch            │  ~Feed size × 1.5       │  ~420 GB     │
    │ Object Storage (media)   │  Depends on usage;      │  1–3 TB      │
    │                          │  assume 10% posts have  │              │
    │                          │  1 MB image             │              │
    └──────────────────────────┴─────────────────────────┴──────────────┘

  INITIAL COMPUTE SIZING (Kubernetes, subject to load-test tuning)
    ┌──────────────────────┬─────────┬─────────┬─────────┬────────────────┐
    │ Deployment           │ min rep │ max rep │ CPU/pod │  RAM/pod       │
    ├──────────────────────┼─────────┼─────────┼─────────┼────────────────┤
    │ api-gateway          │    3    │    10   │  1 core │   1 GB         │
    │ feed-service         │    3    │    20   │  1 core │   1 GB         │
    │ feed-fanout-worker   │    2    │    20   │  1 core │   512 MB       │
    │ chat-service         │    3    │    30   │  1 core │   1 GB         │
    │ community-service    │    2    │    10   │  1 core │   1 GB         │
    │ identity-service     │    3    │    10   │  1 core │   1 GB         │
    │ notification-service │    2    │     8   │  500m   │   512 MB       │
    │ media-service        │    2    │     6   │  500m   │   512 MB       │
    │ search-indexer       │    2    │     6   │  500m   │   512 MB       │
    └──────────────────────┴─────────┴─────────┴─────────┴────────────────┘

──────────────────────────────────────────────────────────────────────────────
§5  DATA OWNERSHIP MATRIX
──────────────────────────────────────────────────────────────────────────────

Each aggregate has EXACTLY ONE owner. Everyone else gets a read-only
replica (via events) or calls the owner synchronously.

  ┌────────────────────────┬─────────────┬──────────────┬───────────────────┐
  │ Data / Aggregate       │  OWNER      │ Read replica │ Sync readers      │
  │                        │  (writes)   │ held by      │ (gRPC)            │
  ├────────────────────────┼─────────────┼──────────────┼───────────────────┤
  │ User account,          │  Identity   │ Feed (author │ Community (verify │
  │ credentials, profile   │             │ _snapshots), │ student), Chat    │
  │                        │             │ Community    │ (block check)     │
  │                        │             │ (member      │                   │
  │                        │             │ _snapshots)  │                   │
  │ Follow graph           │  Identity   │ Feed (fan-   │ — (event-only)    │
  │ (who follows whom)     │             │ out worker   │                   │
  │                        │             │ caches)      │                   │
  │ Block list             │  Identity   │ Chat (local  │ —                 │
  │                        │             │ copy)        │                   │
  │ Post                   │  Feed       │ Search       │ Community (count  │
  │                        │             │ (index)      │ only, via event)  │
  │ Comment                │  Feed       │ Search       │ —                 │
  │ Reaction               │  Feed       │ —            │ —                 │
  │ Home timeline          │  Feed       │ —            │ —                 │
  │ (Redis ZSET)           │             │              │                   │
  │ Conversation           │  Chat       │ —            │ —                 │
  │ Message                │  Chat       │ —            │ —                 │
  │ Presence / typing      │  Chat       │ —            │ —                 │
  │ Community              │  Community  │ Search       │ —                 │
  │                        │             │ (index)      │                   │
  │ Membership + role      │  Community  │ Chat (group  │ Feed (is-member   │
  │                        │             │ chat member  │ check, via event  │
  │                        │             │ list)        │ only)             │
  │ Community post         │  Community  │ Feed (fan-   │ —                 │
  │                        │             │ out into     │                   │
  │                        │             │ timelines),  │                   │
  │                        │             │ Search       │                   │
  │ Moderation log         │  Community  │ —            │ —                 │
  │ Media object metadata  │  Media      │ —            │ Feed, Chat,       │
  │                        │             │              │ Community         │
  │                        │             │              │ (validate ref)    │
  │ Search index           │  Search     │ —            │ —                 │
  └────────────────────────┴─────────────┴──────────────┴───────────────────┘

  REPLICATION RULES
    • Replicas are projections built from Kafka events. They may lag
      by up to NFR §3 propagation target (p99 ≤ 5s).
    • Replica schemas are optimised for the consumer's queries, NOT a
      copy of the owner's schema.
    • If a replica is lost, it can be rebuilt by replaying the Kafka
      topic from the beginning (hence 7-day retention minimum; for
      full rebuild we snapshot + replay from snapshot LSN).

──────────────────────────────────────────────────────────────────────────────
§6  API CONTRACTS — REST (Edge, client-facing)
──────────────────────────────────────────────────────────────────────────────

All REST endpoints:
  • Versioned via path prefix /v1/.
  • Auth via Bearer JWT (Authorization header). Gateway validates.
  • Cursor-based pagination: ?limit=<n>&cursor=<opaque>. Response
    includes { "next_cursor": "<opaque>" | null }.
  • Idempotency on all non-GET: header Idempotency-Key: <uuid>.
    Server stores (key → response) in Redis, TTL 24h; replays
    response on duplicate key.
  • Errors: RFC 7807 (application/problem+json).
  • ETag + If-None-Match on GETs that benefit.

────────────── 6.1  FEED SERVICE — REST ──────────────

  GET  /v1/feed/timeline
         Query: limit (default 30, max 100), cursor
         Resp : 200 { posts: [PostView], next_cursor }
                PostView { id, author: AuthorSnapshot, body,
                           media: [MediaRef], community_ref?,
                           reaction_counts: { like, love, … },
                           my_reaction?, comment_count, created_at }
         Cache: private, no-store (per-user). Served from Redis TL.

  POST /v1/feed/posts
         Body : { body, media_refs?: [string], community_id?: string }
         Resp : 201 { id, created_at }
         Side : emits post.created.v1

  GET  /v1/feed/posts/{postId}
         Resp : 200 PostView   |  404
         Cache: public, max-age=10, stale-while-revalidate=30

  DELETE /v1/feed/posts/{postId}
         Resp : 204
         Auth : author OR moderator of post's community
         Side : soft-delete; emits post.deleted.v1

  GET  /v1/feed/posts/{postId}/comments
         Query: limit, cursor
         Resp : 200 { comments: [CommentView], next_cursor }

  POST /v1/feed/posts/{postId}/comments
         Body : { body }
         Resp : 201 { id, created_at }
         Side : emits comment.created.v1

  PUT  /v1/feed/posts/{postId}/reactions
         Body : { type: "like"|"love"|"laugh"|"sad"|"angry" }
         Resp : 200 { post_id, reaction_counts }
         Side : upsert; emits reaction.set.v1

  DELETE /v1/feed/posts/{postId}/reactions
         Resp : 204
         Side : emits reaction.removed.v1

  GET  /v1/feed/users/{userId}/posts
         Query: limit, cursor
         Resp : 200 { posts: [PostView], next_cursor }
         Auth : public (respects block list)

────────────── 6.2  CHAT SERVICE — REST + WebSocket ──────────────

  REST (setup & history)

  GET  /v1/chat/conversations
         Query: limit, cursor
         Resp : 200 { conversations: [ConvSummary], next_cursor }
                ConvSummary { id, type: "direct"|"group", title?,
                              last_message_preview, unread_count,
                              last_activity_at }

  POST /v1/chat/conversations
         Body : { type: "direct", peer_id: string }
              | { type: "group",  member_ids: [string], title }
         Resp : 201 { id }      (or 200 if direct conv already exists)
         Side : emits conversation.created.v1

  GET  /v1/chat/conversations/{convId}/messages
         Query: limit (default 50, max 200), before_cursor
         Resp : 200 { messages: [MessageView], next_cursor }
                MessageView { id, sender_id, body, media_refs?,
                              sent_at, read_by?: [userId] }

  POST /v1/chat/conversations/{convId}/messages
         Body : { body, media_refs?: [string], client_msg_id: uuid }
         Resp : 201 { id, sent_at }
         Side : emits message.sent.v1; real-time delivery via WS

  POST /v1/chat/conversations/{convId}/read
         Body : { up_to_message_id }
         Resp : 204
         Side : emits message.read.v1

  WEBSOCKET

    Upgrade: GET /v1/chat/ws
    Auth: JWT as query param or Sec-WebSocket-Protocol.
    After upgrade, frames are JSON:

      Client → Server
        { "t": "sub",   "conv_id": "..." }             subscribe
        { "t": "unsub", "conv_id": "..." }             unsubscribe
        { "t": "msg",   "conv_id": "...",
          "body": "...", "client_msg_id": "uuid" }     send (WS fast-path)
        { "t": "typing","conv_id": "...",
          "state": true|false }                        typing indicator
        { "t": "ping" }                                heartbeat (every 25s)

      Server → Client
        { "t": "msg",   "conv_id", "message": MessageView }
        { "t": "typing","conv_id", "user_id", "state" }
        { "t": "presence", "user_id",
          "status": "online"|"away"|"offline" }
        { "t": "read",  "conv_id", "user_id",
          "up_to_message_id" }
        { "t": "ack",   "client_msg_id", "server_id", "sent_at" }
        { "t": "pong" }
        { "t": "error", "code", "message" }

────────────── 6.3  COMMUNITY SERVICE — REST ──────────────

  GET  /v1/communities
         Query: limit, cursor, q? (name prefix), dept? (filter)
         Resp : 200 { communities: [CommSummary], next_cursor }
         Cache: public, max-age=30, stale-while-revalidate=120

  POST /v1/communities
         Body : { name, description, type: "open"|"request"|"closed",
                  department_code? }
         Resp : 201 { id, slug }
         Auth : any verified student; rate-limited to 3/day/user
         Side : emits community.created.v1

  GET  /v1/communities/{id}
         Resp : 200 CommunityView { id, slug, name, description, type,
                  department_code?, member_count, created_at,
                  my_membership?: { role, joined_at } }
         Cache: public, max-age=30, stale-while-revalidate=120

  POST /v1/communities/{id}/join
         Resp : 200 { status: "joined" }
              | 202 { status: "requested" }  (for request-type comms)
         Side : emits community.member.joined.v1 OR
                community.join.requested.v1

  DELETE /v1/communities/{id}/membership
         Resp : 204   (leave community)
         Side : emits community.member.left.v1

  GET  /v1/communities/{id}/members
         Query: limit, cursor, role?
         Resp : 200 { members: [MemberView], next_cursor }
         Auth : must be member

  PUT  /v1/communities/{id}/members/{userId}/role
         Body : { role: "admin"|"moderator"|"member" }
         Resp : 200
         Auth : admin only
         Side : emits community.role.changed.v1

  GET  /v1/communities/{id}/posts
         Query: limit, cursor
         Resp : 200 { posts: [CommPostView], next_cursor }
         Auth : member (unless community is open)

  POST /v1/communities/{id}/posts
         Body : { body, media_refs?: [string] }
         Resp : 201 { id, created_at }
         Auth : member
         Side : emits community.post.created.v1

  DELETE /v1/communities/{id}/posts/{postId}
         Resp : 204
         Auth : author OR moderator/admin
         Side : emits community.post.removed.v1

  POST /v1/communities/{id}/join-requests/{reqId}/approve
         Resp : 200
         Auth : moderator/admin
         Side : emits community.member.joined.v1

────────────── 6.4  IDENTITY SERVICE — REST ──────────────

  POST /v1/auth/register
         Body : { astu_student_id, email, password, display_name }
         Resp : 201 { user_id }    (pending verification)
         Side : calls ASTU Registrar to verify; on success emits
                user.created.v1

  POST /v1/auth/login
         Body : { email, password }
         Resp : 200 { access_token (JWT, 15 min),
                      refresh_token (opaque, 30 d) }

  POST /v1/auth/refresh
         Body : { refresh_token }
         Resp : 200 { access_token, refresh_token }

  GET  /v1/users/me          → own profile
  GET  /v1/users/{id}        → public profile (cache: 30s)
  PATCH /v1/users/me         → update profile; emits user.updated.v1

  POST   /v1/users/{id}/follow    → emits user.followed.v1
  DELETE /v1/users/{id}/follow    → emits user.unfollowed.v1
  POST   /v1/users/{id}/block     → emits user.blocked.v1
  DELETE /v1/users/{id}/block     → emits user.unblocked.v1

  GET  /v1/users/{id}/followers   → paginated
  GET  /v1/users/{id}/following   → paginated

────────────── 6.5  MEDIA SERVICE — REST ──────────────

  POST /v1/media/uploads
         Body : { content_type, size_bytes }
         Resp : 200 { media_id, upload_url (presigned, 10 min),
                      required_headers }
         Side : client uploads directly to S3; then calls:

  POST /v1/media/{mediaId}/complete
         Resp : 200 { media_id, public_url, width?, height?,
                      duration_ms? }
         Side : validates object exists & size; extracts metadata.

  GET  /v1/media/{mediaId}
         Resp : 302 → CDN URL   |  404

──────────────────────────────────────────────────────────────────────────────
§7  API CONTRACTS — gRPC (Internal, service-to-service)
──────────────────────────────────────────────────────────────────────────────

All internal gRPC:
  • mTLS required. SPIFFE IDs identify callers.
  • Deadline propagation: caller sets deadline; callee respects it.
  • Default deadline 200ms unless noted.
  • All batch RPCs cap at 100 items per call.

────────────── 7.1  identity.v1.UserService ──────────────

  rpc GetUsersBatch(GetUsersBatchRequest) returns (GetUsersBatchResponse)
      Req : { user_ids: [string] (max 100),
              fields: [DISPLAY_NAME, AVATAR_URL, DEPARTMENT] }
      Res : { users: [UserSnapshot],
              not_found_ids: [string] }
      Used by: Feed (timeline enrichment — fallback path when
               local author_snapshots is cold), Community

  rpc VerifyStudentStatus(VerifyStudentStatusRequest)
        returns (VerifyStudentStatusResponse)
      Req : { user_id }
      Res : { is_active_student: bool, department_code?,
              year_of_study? }
      Used by: Community (gate community creation)
      Deadline: 500ms (may hit Registrar cache)

  rpc GetFollowerIds(GetFollowerIdsRequest)
        returns (stream FollowerIdBatch)
      Req : { user_id, batch_size: 500 }
      Res : stream of { follower_ids: [string] }
      Used by: Feed Fan-out Worker (on post.created, to enumerate
               push targets). Streaming because celebrity accounts
               may have many followers.

  rpc IsBlocked(IsBlockedRequest) returns (IsBlockedResponse)
      Req : { actor_id, target_id }
      Res : { blocked: bool }
      Used by: Chat (SendMessage), Feed (CreateComment)
      Note: consumers should cache result 60s; Identity also pushes
            user.blocked events for eager invalidation.

────────────── 7.2  community.v1.MembershipService ──────────────

  rpc IsMemberBatch(IsMemberBatchRequest) returns (IsMemberBatchResponse)
      Req : { checks: [{ user_id, community_id }] (max 100) }
      Res : { results: [{ user_id, community_id, is_member,
                          role? }] }
      Used by: Feed (authorize posting into a community),
               Chat (authorize joining community group chat)
      Note: primary path is the local replica built from
            community.member.joined/left events. This RPC is the
            FALLBACK when the replica is cold or when strong
            consistency is required (e.g., first write after join).

────────────── 7.3  media.v1.MediaService ──────────────

  rpc ValidateRefsBatch(ValidateRefsBatchRequest)
        returns (ValidateRefsBatchResponse)
      Req : { media_ids: [string] (max 20) }
      Res : { results: [{ media_id, valid: bool,
                          content_type?, size_bytes? }] }
      Used by: Feed, Chat, Community on any write containing
               media_refs, to prevent referencing non-existent or
               oversized media.

────────────── 7.4  feed.v1.TimelineAdmin (internal maintenance) ──────────────

  rpc RebuildTimeline(RebuildTimelineRequest)
        returns (RebuildTimelineResponse)
      Req : { user_id }
      Res : { entries_written: int }
      Used by: ops tooling; rebuilds a user's Redis timeline from
               Postgres. For recovery after Redis data loss.

  rpc BackfillCommunityPosts(BackfillRequest) returns (BackfillResponse)
      Req : { user_id, community_id, max_posts: int (default 20) }
      Res : { entries_written: int }
      Used by: Feed's own Kafka consumer on community.member.joined.

──────────────────────────────────────────────────────────────────────────────
§8  KAFKA TOPICS & EVENT SCHEMAS
──────────────────────────────────────────────────────────────────────────────

CLUSTER CONFIG
  • 3 brokers. Replication factor = 3. min.insync.replicas = 2.
  • Producer: acks=all, enable.idempotence=true, compression=zstd.
  • Schema registry (Confluent / Apicurio). All payloads JSON,
    validated against JSON-Schema at produce time.
  • Retention: 7 days standard. user.events and community.events
    kept 30 days (lower volume, useful for replica rebuilds).
  • Partition key chosen to preserve per-entity ordering.

ENVELOPE (all events)
  {
    "event_id":       "uuid-v7",                // sortable
    "event_type":     "post.created",
    "event_version":  1,
    "occurred_at":    "2026-03-01T10:15:22.441Z",
    "producer":       "feed-service",
    "correlation_id": "uuid"   // propagated from ingress request
  }

  Payload is a sibling field: { ...envelope, "payload": { ... } }
  Versioning: additive changes (new optional fields) keep the same
  version. Breaking changes bump event_version AND topic suffix
  (e.g., post.events.v2). Old and new coexist until all consumers
  migrate.

TOPIC INVENTORY

  ┌─────────────────────┬──────┬──────────────────┬──────────────────────────┐
  │ Topic               │ Part │ Key              │ Consumers                │
  ├─────────────────────┼──────┼──────────────────┼──────────────────────────┤
  │ user.events         │  12  │ user_id          │ Feed, Chat, Community,   │
  │                     │      │                  │ Notification, Search     │
  │ post.events         │  24  │ post_id          │ Fan-out, Notification,   │
  │                     │      │                  │ Search, Community        │
  │ comment.events      │  24  │ post_id          │ Notification, Search     │
  │ reaction.events     │  24  │ post_id          │ Notification             │
  │ message.events      │  48  │ conversation_id  │ Notification             │
  │ community.events    │  12  │ community_id     │ Feed, Chat, Notification,│
  │                     │      │                  │ Search                   │
  │ feed.fanout.cmd     │  48  │ target_user_id   │ Feed Fan-out Worker      │
  │                     │      │                  │ (internal — commands to  │
  │                     │      │                  │  write a timeline entry; │
  │                     │      │                  │  allows sharded workers) │
  └─────────────────────┴──────┴──────────────────┴──────────────────────────┘

EVENT SCHEMAS — user.events

  user.created.v1
    payload { user_id, astu_student_id, display_name, avatar_url?,
              department_code?, created_at }

  user.updated.v1
    payload { user_id, changed_fields: ["display_name"|"avatar_url"|
              "department_code"], display_name?, avatar_url?,
              department_code? }
    Consumers: Feed/Community refresh their local *_snapshots tables.

  user.followed.v1
    payload { follower_id, followee_id, followed_at }
    Consumers: Feed (fan-out worker cache warm), Notification.

  user.unfollowed.v1
    payload { follower_id, followee_id, unfollowed_at }
    Consumers: Feed (optionally prune timeline entries).

  user.blocked.v1
    payload { blocker_id, blocked_id, blocked_at }
    Consumers: Chat (deny messaging), Feed (hide content).

  user.unblocked.v1
    payload { blocker_id, unblocked_id, unblocked_at }

EVENT SCHEMAS — post.events

  post.created.v1
    payload { post_id, author_id, community_id?, body_preview (first
              280 chars), has_media: bool, media_refs?: [string],
              created_at }
    Note: full body NOT in event — consumers that need it call Feed
          or read via post_id. Keeps events small.

  post.deleted.v1
    payload { post_id, author_id, community_id?, deleted_by,
              reason?: "author"|"moderator"|"policy", deleted_at }
    Consumers: Fan-out (remove from timelines), Search (delete doc).

EVENT SCHEMAS — comment.events

  comment.created.v1
    payload { comment_id, post_id, post_author_id, commenter_id,
              body_preview, mentioned_user_ids?: [string],
              created_at }
    Consumers: Notification (notify post_author + mentions), Search.

  comment.deleted.v1
    payload { comment_id, post_id, deleted_by, deleted_at }

EVENT SCHEMAS — reaction.events

  reaction.set.v1
    payload { post_id, post_author_id, reactor_id,
              reaction_type: "like"|"love"|"laugh"|"sad"|"angry",
              previous_type?: string, reacted_at }
    Consumers: Notification (notify post_author if new reaction).

  reaction.removed.v1
    payload { post_id, reactor_id, removed_at }

EVENT SCHEMAS — message.events

  message.sent.v1
    payload { message_id, conversation_id, conversation_type:
              "direct"|"group", sender_id, recipient_ids: [string],
              has_media: bool, sent_at }
    Consumers: Notification (push to OFFLINE recipients only —
               online recipients got it via WebSocket).

  message.read.v1
    payload { conversation_id, reader_id, up_to_message_id,
              read_at }

  conversation.created.v1
    payload { conversation_id, type, creator_id,
              member_ids: [string], title?, created_at }

EVENT SCHEMAS — community.events

  community.created.v1
    payload { community_id, slug, name, type, department_code?,
              creator_id, created_at }

  community.member.joined.v1
    payload { community_id, user_id, role: "member"|"moderator"|
              "admin", joined_at, join_method: "direct"|"approved"|
              "auto_enrolled" }
    Consumers: Chat (add to group chat), Feed (backfill posts),
               Notification (notify admins if configured).

  community.member.left.v1
    payload { community_id, user_id, left_at,
              reason: "voluntary"|"removed"|"banned" }

  community.role.changed.v1
    payload { community_id, user_id, old_role, new_role,
              changed_by, changed_at }

  community.post.created.v1
    payload { post_id, community_id, author_id, body_preview,
              has_media, created_at }
    Consumers: Feed (fan-out to community members' timelines),
               Search, Notification.

  community.post.removed.v1
    payload { post_id, community_id, removed_by,
              reason: "author"|"moderator", removed_at }

  community.join.requested.v1
    payload { request_id, community_id, requester_id, requested_at }
    Consumers: Notification (notify moderators).

EVENT SCHEMAS — feed.fanout.cmd (internal command topic)

  timeline.write.v1
    payload { target_user_id, post_id, source: "follow"|"community",
              score (epoch ms for ZSET ordering), origin_event_id }
    Produced by: Feed Service (on post.created, after enumerating
                 followers via GetFollowerIds stream).
    Consumed by: Fan-out Worker → ZADD timeline:{target_user_id}.
    Why a separate topic: decouples "enumerate followers" (fast,
    one message per post) from "write timeline entry" (slow, N
    messages per post). Lets us shard workers by target_user_id
    so timeline writes for one user are serialised.

──────────────────────────────────────────────────────────────────────────────
§9  CACHING STRATEGY
──────────────────────────────────────────────────────────────────────────────

Three tiers. Cache-aside pattern (read-through: miss → load → populate).

  ┌───────────────────────┬─────────────┬──────────┬──────────────────────────┐
  │ Tier                  │ Latency     │ Scope    │ Used for                 │
  ├───────────────────────┼─────────────┼──────────┼──────────────────────────┤
  │ L1: In-process LRU    │ ~100 ns     │ Single   │ Ultra-hot boolean checks │
  │                       │             │ pod      │ (is-member, is-blocked)  │
  │ L2: Redis             │ ~0.5–1 ms   │ All pods │ Timelines, hot entities, │
  │                       │             │ of svc   │ idempotency keys         │
  │ L3: Primary DB        │ ~2–10 ms    │ Source   │ Cold reads, all writes   │
  │                       │             │ of truth │                          │
  └───────────────────────┴─────────────┴──────────┴──────────────────────────┘

CACHE KEY INVENTORY

  ┌──────────────────────────────────┬──────┬───────┬─────────────────────────┐
  │ Key pattern                      │ Tier │ TTL   │ Invalidation            │
  ├──────────────────────────────────┼──────┼───────┼─────────────────────────┤
  │ timeline:{userId}                │  L2  │  —    │ Capped ZSET (800 max).  │
  │   (Redis ZSET: postId → score)   │      │       │ No TTL; entries evicted │
  │                                  │      │       │ by ZREMRANGEBYRANK.     │
  │                                  │      │       │ Explicit ZREM on        │
  │                                  │      │       │ post.deleted.           │
  │ post:{postId}                    │  L2  │  60s  │ DEL on any post mutation│
  │   (serialized PostView)          │      │       │ (edit, delete, reaction │
  │                                  │      │       │ — reaction invalidates  │
  │                                  │      │       │ because PostView embeds │
  │                                  │      │       │ reaction_counts).       │
  │ post:{postId}:comments:p0        │  L2  │  30s  │ DEL on comment.created/ │
  │   (first page only cached)       │      │       │ deleted for this post.  │
  │ author_snap:{userId}             │  L2  │ 300s  │ DEL on user.updated     │
  │                                  │      │       │ event. Also persisted   │
  │                                  │      │       │ in Feed Postgres as     │
  │                                  │      │       │ fallback.               │
  │ community:{id}:meta              │  L2  │  60s  │ DEL on any community    │
  │                                  │      │       │ mutation.               │
  │ membership:{userId}:{commId}     │ L1+L2│ 5s/60s│ L1: time-based only.    │
  │   → { is_member, role }          │      │       │ L2: DEL on member.      │
  │                                  │      │       │ joined/left/role.changed│
  │ blocked:{userA}:{userB}          │ L1+L2│ 5s/60s│ Same pattern as above.  │
  │ presence:{userId}                │  L2  │  30s  │ TTL-only. Heartbeat     │
  │   → "online"|"away"              │      │       │ refreshes. Expiry =     │
  │                                  │      │       │ "offline".              │
  │ typing:{convId}                  │  L2  │   5s  │ TTL-only.               │
  │   (Redis SET of userIds)         │      │       │                         │
  │ ws_route:{userId}                │  L2  │  45s  │ TTL + heartbeat. On pod │
  │   → pod-id                       │      │       │ shutdown, pod DELs its  │
  │                                  │      │       │ own routes.             │
  │ idem:{svc}:{key}                 │  L2  │  24h  │ TTL-only.               │
  │   → serialized response          │      │       │                         │
  │ rate:{userId}:{window}           │  L2  │  60s  │ TTL-only (sliding-      │
  │   → request count                │      │       │ window counter).        │
  │ follower_ids:{userId}:v{n}       │  L2  │ 600s  │ Version bump on         │
  │   (for fan-out worker)           │      │       │ user.followed/          │
  │                                  │      │       │ unfollowed. Worker reads│
  │                                  │      │       │ current version pointer │
  │                                  │      │       │ first.                  │
  └──────────────────────────────────┴──────┴───────┴─────────────────────────┘

GATEWAY-LEVEL HTTP CACHING

  ┌────────────────────────────────┬─────────────────────────────────────┐
  │ Endpoint                       │ Cache-Control                       │
  ├────────────────────────────────┼─────────────────────────────────────┤
  │ GET /v1/communities            │ public, max-age=30, swr=120         │
  │ GET /v1/communities/{id}       │ public, max-age=30, swr=120,        │
  │                                │ Vary: Authorization (because        │
  │                                │ my_membership differs)              │
  │                                │ → actually: split response;         │
  │                                │ public shell cached, my_membership  │
  │                                │ fetched separately or from L2.      │
  │ GET /v1/users/{id}             │ public, max-age=30, swr=60          │
  │ GET /v1/feed/posts/{id}        │ public, max-age=10, swr=30          │
  │ GET /v1/feed/timeline          │ private, no-store (per-user)        │
  │ All POST/PUT/DELETE            │ no-store                            │
  └────────────────────────────────┴─────────────────────────────────────┘

INVALIDATION APPROACH — Event-driven where it matters.
  Each service runs a lightweight "cache invalidator" Kafka consumer
  that subscribes to the events affecting its cached entities and
  issues Redis DEL. L1 caches use short TTL (5s) only — no active
  invalidation (simplicity over perfection; 5s staleness acceptable).

NEGATIVE CACHING
  404s for posts/communities cached 10s (prevents repeated DB misses
  from bots or broken links).

CACHE STAMPEDE PROTECTION
  On L2 miss for a hot key (e.g., a viral post), use a Redis lock
  (SET NX, 3s TTL) — one request loads from DB, others wait up to
  100ms then retry the cache, falling through to DB if still cold.

──────────────────────────────────────────────────────────────────────────────
§10  ROLLOUT PLAN
──────────────────────────────────────────────────────────────────────────────

PHASED DELIVERY

  ┌───────┬────────────────────────────────────────────────────────────────┐
  │ Phase │ Scope & Exit Criteria                                          │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  0    │ FOUNDATIONS                                                    │
  │       │ • K8s cluster up; namespaces per service.                      │
  │       │ • Kafka 3-broker cluster, schema registry.                     │
  │       │ • Postgres (3×: feed/community/identity), Cassandra 3-node,    │
  │       │   Redis (2 instances: feed-cache, chat-state).                 │
  │       │ • Observability stack: OTel collector, Prometheus, Loki,       │
  │       │   Grafana, Tempo. Golden dashboards stubbed.                   │
  │       │ • CI/CD pipeline: build → unit test → container push →         │
  │       │   helm deploy to staging.                                      │
  │       │ EXIT: `helm install` of a hello-world service succeeds in all  │
  │       │       namespaces; Kafka produce/consume smoke test green;      │
  │       │       all DB health checks green.                              │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  1    │ IDENTITY + GATEWAY (MVP)                                       │
  │       │ • Identity Service: register, login, refresh, JWT issuance,    │
  │       │   user CRUD, follow/unfollow. Mock ASTU Registrar.             │
  │       │ • API Gateway: TLS, JWT validation, routing to Identity.       │
  │       │ • user.events topic produced & schema-registered.              │
  │       │ EXIT: Integration test: register → login → refresh → follow    │
  │       │       → observe user.followed.v1 in Kafka. p95 < target × 1.5. │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  2    │ FEED CORE                                                      │
  │       │ • Feed Service: create/get/delete post, comment, reaction.     │
  │       │   author_snapshots consumer of user.events.                    │
  │       │ • Timeline v0 = pull-only (direct Postgres query). No Redis    │
  │       │   yet. Functional but slow — acceptable for this phase.        │
  │       │ • post/comment/reaction topics produced.                       │
  │       │ EXIT: Create post → appears in author's own feed → react →     │
  │       │       comment → delete. All events observed. Contract tests    │
  │       │       green.                                                   │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  3    │ FEED FAN-OUT + REDIS TIMELINE                                  │
  │       │ • Redis timeline ZSETs. Hybrid push/pull. Fan-out worker.      │
  │       │ • feed.fanout.cmd topic.                                       │
  │       │ • TimelineAdmin gRPC for rebuild.                              │
  │       │ • Load test: 2,000 timeline reads/s, 15 posts/s.               │
  │       │ EXIT: p95 GET /timeline < 120ms under target load. Fan-out     │
  │       │       lag p99 < 5s. Celebrity (synthetic 5k-follower account)  │
  │       │       posts do NOT spike fan-out worker CPU above 60%.         │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  4    │ COMMUNITY                                                      │
  │       │ • Community Service full CRUD, membership, roles, moderation.  │
  │       │ • community.events produced.                                   │
  │       │ • Feed consumer: community.post.created → fan-out to members.  │
  │       │ • Feed consumer: community.member.joined → backfill.           │
  │       │ EXIT: Create community → join → post in community → appears    │
  │       │       in member timelines. Moderator removes post → removed    │
  │       │       from timelines. Membership checks via L1/L2 cache hit    │
  │       │       ratio > 95%.                                             │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  5    │ CHAT                                                           │
  │       │ • Chat Service: WS gateway, Cassandra message store, Redis     │
  │       │   presence/typing/routing.                                     │
  │       │ • Cross-pod message routing via Redis Pub/Sub.                 │
  │       │ • message.events produced.                                     │
  │       │ • Consumer of community.member.joined → auto-add to group.     │
  │       │ • Load test: 12k concurrent WS, 500 msg/s.                     │
  │       │ EXIT: End-to-end msg latency p95 < 150ms under load. Pod       │
  │       │       rolling restart loses 0 messages (clients reconnect &    │
  │       │       resync via GET /messages). Presence accuracy > 98%.      │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  6    │ SUPPORTING SERVICES + HARDENING                                │
  │       │ • Notification Service (FCM integration).                      │
  │       │ • Media Service (presigned uploads).                           │
  │       │ • Search Indexer + Elasticsearch.                              │
  │       │ • Rate limiting, idempotency, circuit breakers ALL enforced.   │
  │       │ • Chaos testing: kill pods, kill Kafka broker, kill Redis.     │
  │       │ EXIT: All NFR §3 targets met in staging under §4 peak load.    │
  │       │       Chaos scenarios recover within SLO without manual        │
  │       │       intervention.                                            │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  7    │ CLOSED BETA                                                    │
  │       │ • Real ASTU Registrar integration.                             │
  │       │ • ~500 invited students. Feature flags for kill-switches.      │
  │       │ • 2-week soak. Monitor SLOs, error budget, user feedback.      │
  │       │ EXIT: No P0/P1 incidents for 7 consecutive days. Error budget  │
  │       │       consumption < 50%. User-reported bug rate < threshold.   │
  ├───────┼────────────────────────────────────────────────────────────────┤
  │  8    │ GENERAL AVAILABILITY                                           │
  │       │ • Phased rollout by department: 10% → 25% → 50% → 100%.        │
  │       │ • Each step: 48h observation, proceed only if SLOs green.      │
  │       │ • Runbooks finalised. On-call rotation active.                 │
  │       │ EXIT: 100% of ASTU students onboarded. 30-day SLO compliance.  │
  └───────┴────────────────────────────────────────────────────────────────┘

RISK REGISTER & MITIGATIONS

  ┌───┬───────────────────────────────┬──────┬──────┬────────────────────────┐
  │ # │ Risk                          │ Prob │ Imp  │ Mitigation             │
  ├───┼───────────────────────────────┼──────┼──────┼────────────────────────┤
  │ R1│ Fan-out hotspot: viral post   │  M   │  H   │ Hybrid push/pull with  │
  │   │ from high-follower account    │      │      │ celebrity threshold.   │
  │   │ floods Redis & workers.       │      │      │ Load-test with         │
  │   │                               │      │      │ synthetic 10k-follower │
  │   │                               │      │      │ account. Autoscale     │
  │   │                               │      │      │ workers on Kafka lag.  │
  │   │                               │      │      │ Alert on lag > 30s.    │
  │ R2│ Cassandra operational         │  M   │  M   │ Start with managed     │
  │   │ complexity (team unfamiliar). │      │      │ offering if available; │
  │   │                               │      │      │ otherwise ScyllaDB     │
  │   │                               │      │      │ (simpler ops).         │
  │   │                               │      │      │ Fallback: Postgres     │
  │   │                               │      │      │ with monthly partition │
  │   │                               │      │      │ tables — revisit at    │
  │   │                               │      │      │ >100M messages. Clean  │
  │   │                               │      │      │ Arch MessageRepository │
  │   │                               │      │      │ port makes swap cheap. │
  │ R3│ Event schema drift — producer │  M   │  H   │ Schema registry with   │
  │   │ changes break consumers.      │      │      │ BACKWARD compatibility │
  │   │                               │      │      │ enforcement. CI step   │
  │   │                               │      │      │ rejects incompatible   │
  │   │                               │      │      │ schema changes.        │
  │   │                               │      │      │ Consumer contract      │
  │   │                               │      │      │ tests in each service's│
  │   │                               │      │      │ pipeline.              │
  │ R4│ Redis timeline loss on        │  L   │  M   │ Timelines are          │
  │   │ failover or eviction.         │      │      │ rebuildable from       │
  │   │                               │      │      │ Postgres via           │
  │   │                               │      │      │ RebuildTimeline RPC.   │
  │   │                               │      │      │ Automated rebuild job  │
  │   │                               │      │      │ triggered on Redis     │
  │   │                               │      │      │ primary failover.      │
  │   │                               │      │      │ Redis AOF everysec     │
  │   │                               │      │      │ (bounds loss to 1s).   │
  │ R5│ Sync call chain causes        │  M   │  H   │ Hard rule: max 1 sync  │
  │   │ cascading latency/failure.    │      │      │ hop per request.       │
  │   │                               │      │      │ Circuit breakers on    │
  │   │                               │      │      │ every client. Lint     │
  │   │                               │      │      │ rule: new sync call    │
  │   │                               │      │      │ requires arch review.  │
  │ R6│ ASTU Registrar unavailable    │  M   │  M   │ Cache verification     │
  │   │ → blocks all signups.         │      │      │ results 24h. Queue     │
  │   │                               │      │      │ pending signups; retry │
  │   │                               │      │      │ verification async;    │
  │   │                               │      │      │ user gets "pending"    │
  │   │                               │      │      │ status, limited access.│
  │ R7│ WebSocket connection storm on │  M   │  M   │ Client exponential     │
  │   │ Chat pod restart (all clients │      │      │ backoff + jitter on    │
  │   │ reconnect simultaneously).    │      │      │ reconnect. Pod-        │
  │   │                               │      │      │ DisruptionBudget: max  │
  │   │                               │      │      │ 1 pod unavailable.     │
  │   │                               │      │      │ Gateway connection     │
  │   │                               │      │      │ rate limit.            │
  │ R8│ Dual-write inconsistency:     │  L   │  H   │ Transactional outbox   │
  │   │ DB commit succeeds but Kafka  │      │      │ pattern: event written │
  │   │ publish fails → event lost.   │      │      │ to outbox table in the │
  │   │                               │      │      │ SAME DB transaction as │
  │   │                               │      │      │ the business write.    │
  │   │                               │      │      │ Separate relay process │
  │   │                               │      │      │ polls outbox → Kafka   │
  │   │                               │      │      │ → marks row published. │
  │ R9│ Cache inconsistency (stale    │  H   │  L   │ Accepted by design.    │
  │   │ L1/L2 after write).           │      │      │ TTLs bound staleness   │
  │   │                               │      │      │ to ≤ 60s. Event-driven │
  │   │                               │      │      │ invalidation for L2    │
  │   │                               │      │      │ reduces typical        │
  │   │                               │      │      │ staleness to < 1s.     │
  │   │                               │      │      │ No user-visible impact │
  │   │                               │      │      │ beyond "my like took a │
  │   │                               │      │      │ second to appear".     │
  │R10│ Kafka cluster total outage.   │  L   │  H   │ Outbox buffers writes  │
  │   │                               │      │      │ (see R8). Services     │
  │   │                               │      │      │ continue serving reads │
  │   │                               │      │      │ from cache/DB.         │
  │   │                               │      │      │ Downstream effects     │
  │   │                               │      │      │ (notifications, search │
  │   │                               │      │      │ indexing, fan-out)     │
  │   │                               │      │      │ pause; resume on       │
  │   │                               │      │      │ recovery. Alert P1.    │
  │R11│ Search index out of sync      │  M   │  L   │ Nightly reconciliation │
  │   │ after consumer bugs.          │      │      │ job: compare ES doc    │
  │   │                               │      │      │ count vs Postgres,     │
  │   │                               │      │      │ reindex delta. Full    │
  │   │                               │      │      │ reindex runbook from   │
  │   │                               │      │      │ Kafka replay.          │
  │R12│ Peak-hour load exceeds        │  L   │  H   │ ×3 headroom (§4).      │
  │   │ capacity (e.g., campus-wide   │      │      │ Autoscaling on p95     │
  │   │ event drives traffic spike).  │      │      │ latency + CPU. Gateway │
  │   │                               │      │      │ sheds load (429) per   │
  │   │                               │      │      │ user before backend    │
  │   │                               │      │      │ saturates. Pre-scale   │
  │   │                               │      │      │ before known events    │
  │   │                               │      │      │ (registration day).    │
  └───┴───────────────────────────────┴──────┴──────┴────────────────────────┘

──────────────────────────────────────────────────────────────────────────────
§11  ACCEPTANCE CRITERIA
──────────────────────────────────────────────────────────────────────────────

FUNCTIONAL

  AC-F1   Given a verified student, when they POST /v1/feed/posts, then
          the post is persisted, GET /v1/feed/posts/{id} returns it, and
          a post.created.v1 event appears in post.events within 1s.

  AC-F2   Given user A follows user B, when B creates a post, then the
          post appears in A's GET /v1/feed/timeline within 5s (p99) and
          appears in correct chronological order relative to other posts.

  AC-F3   Given user B has > 1,000 followers ("celebrity"), when B
          posts, then the fan-out worker does NOT emit timeline.write
          commands for B's followers (verified by Kafka consumer-group
          offset deltas), yet B's post still appears in follower
          timelines via the pull-merge path.

  AC-F4   Given two online users in a direct conversation, when user A
          sends a message via WebSocket, then user B receives the
          message frame within 300ms (p99), and the message is
          retrievable via GET /v1/chat/conversations/{id}/messages.

  AC-F5   Given user A blocks user B, when B attempts to send a message
          to A, then Chat rejects with 403 within 60s of the block
          (eventual-consistency window), and within 1s after
          user.blocked.v1 is consumed.

  AC-F6   Given a community of type "request", when a non-member calls
          POST /join, then response is 202 {status:"requested"}, a
          community.join.requested.v1 event fires, and moderators
          receive a push notification within 10s.

  AC-F7   Given a user joins a community, then within 10s:
          (a) Chat Service has added them to the community group chat,
          (b) Feed Service has backfilled ≤ 20 recent community posts
              into their timeline.

  AC-F8   Given any write request with an Idempotency-Key header, when
          the same request is replayed within 24h, then the service
          returns the same response without re-executing side effects
          (verified: exactly one post.created event for two identical
          POST /posts calls).

  AC-F9   Given a user updates their display_name, then within 60s
          (TTL) or immediately after user.updated.v1 consumption
          (whichever first), Feed's author_snapshots reflects the new
          name and timeline responses show it.

  AC-F10  Given a post is deleted, then within 5s (p99) it is removed
          from all follower timelines (ZREM) and returns 404 on GET,
          and the Search index deletes the document within 30s.

NON-FUNCTIONAL

  AC-N1   Under sustained §4 peak load for 30 minutes in staging, all
          latency percentiles meet §3 targets with ≤ 5% headroom
          violation.

  AC-N2   Under §4 peak load ×2 (stress test) for 10 minutes, no
          component crashes, error rate stays < 1%, and the system
          recovers to §3 targets within 2 minutes of load drop.

  AC-N3   With one Kafka broker killed, producers continue to ACK
          writes (acks=all satisfied by remaining 2 brokers) and
          consumers continue without message loss. Recovery automatic
          on broker restart.

  AC-N4   With one Feed Service pod killed, in-flight requests to that
          pod fail (acceptable) but no other requests fail, and
          autoscaler replaces the pod within 60s. Overall error rate
          spike < 0.5% during the event.

  AC-N5   With Redis (Feed Cache) flushed, timeline reads degrade to
          pull-model (Postgres) latency but do not error. Automated
          rebuild populates timelines within 10 minutes for all active
          users.

  AC-N6   With Identity Service unavailable, Feed timeline reads
          continue serving author info from local snapshots (no 5xx
          from Feed). Circuit breaker opens within 5 failed calls /
          10s window.

  AC-N7   Feed fan-out Kafka consumer lag stays < 5s (p99) under peak
          load. Alert fires if lag > 30s for > 1 minute.

  AC-N8   No cross-service database connection exists in any
          environment (verified by network policy: each DB accepts
          connections only from its owning service's namespace).

  AC-N9   Every inter-service gRPC call carries a deadline and a
          correlation ID. Verified by 100% trace-span coverage in
          Tempo for a sample of 10k requests.

  AC-N10  Schema registry rejects any event schema change that is not
          BACKWARD compatible (verified by CI test that attempts a
          breaking change and expects rejection).

──────────────────────────────────────────────────────────────────────────────
§12  DEFINITION OF DONE (Epic-level)
──────────────────────────────────────────────────────────────────────────────

CODE & DESIGN
  ☐  All services implement the Clean Architecture layering; a linter
     or ArchUnit-equivalent test enforces that the Domain layer has
     zero imports from Adapters/Frameworks.
  ☐  All REST endpoints documented in OpenAPI 3.1, published, and
     drift-checked against running services in CI.
  ☐  All gRPC services defined in .proto, versioned, published to
     internal artifact store.
  ☐  All Kafka event schemas registered; CI validates compatibility.
  ☐  Transactional outbox implemented in every service that emits
     events.

TESTING
  ☐  Unit test coverage ≥ 80% for Domain and Use-Case layers.
  ☐  Contract tests (consumer-driven) pass for every producer/consumer
     pair (REST, gRPC, and Kafka).
  ☐  Integration test suite (per service, with ephemeral DB + Kafka)
     green in CI.
  ☐  End-to-end test suite covering AC-F1 through AC-F10 green in
     staging.
  ☐  Load test (§4 peak) passes AC-N1.
  ☐  Stress test (×2 peak) passes AC-N2.
  ☐  Chaos tests (AC-N3 through AC-N6) pass.

OBSERVABILITY
  ☐  Every service exports: request latency histograms (per endpoint),
     error rate, Kafka consumer lag, DB connection pool saturation,
     cache hit ratio (L1 and L2).
  ☐  Distributed traces span the full request path (gateway → service
     → DB / Kafka) with correlation IDs.
  ☐  Golden dashboards per service (latency, traffic, errors,
     saturation) reviewed and signed off by on-call team.
  ☐  Alerts configured for every SLO with runbook links. Alerts
     tested (fired in staging, on-call received page).

SECURITY
  ☐  Security review completed; no open High/Critical findings.
  ☐  JWT validation enforced at gateway AND at each service.
  ☐  mTLS enforced for all internal traffic; network policies deny
     cross-namespace DB access.
  ☐  Secrets in vault; no secrets in env vars, code, or config maps.
  ☐  Rate limits active and tested (verified: 61st write in 60s
     returns 429).

OPERATIONS
  ☐  Runbooks exist for: Redis failover, Kafka broker loss, Cassandra
     node replacement, timeline rebuild, search reindex, rollback
     procedure per service.
  ☐  On-call rotation staffed and trained.
  ☐  DR plan documented and tested (restore Postgres from PITR
     backup in staging).
  ☐  Feature flags / kill-switches exist for: fan-out (can fall back
     to pure pull), notifications (can mute), WS chat (can degrade to
     polling).

ROLLOUT
  ☐  All 9 phases (§10) completed with exit criteria met.
  ☐  Closed beta (Phase 7): 7 consecutive days without P0/P1 incident.
  ☐  GA (Phase 8): 100% rollout complete, 30-day SLO compliance
     observed.

DOCUMENTATION
  ☐  Architecture Decision Records (ADRs) filed for: Cassandra vs
     Postgres for chat, hybrid fan-out threshold, transactional
     outbox, gateway choice.
  ☐  This spec (res3) updated to reflect final as-built state.
  ☐  Onboarding guide for new engineers: how to run one service
     locally against shared staging infra.

════════════════════════════════════════════════════════════════════════════════
END OF SPEC
════════════════════════════════════════════════════════════════════════════════
