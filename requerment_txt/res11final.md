════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — FINAL ARCHITECTURE SUMMARY
The whole system on a few pages, and where we take it from here
════════════════════════════════════════════════════════════════════════════════

Audience:   Everyone — new engineers, product, leadership, on-call.
Purpose:    A single place to understand HOW the parts fit, WHAT rules
            to follow when building, HOW we stay fast with many students
            online at once, and WHERE we grow next.
Builds on:  res1 (microservices & Clean Arch), res2 (plain-language
            tour), res3 (detailed spec & phases), res4 (event system),
            res5 (replay runbooks), res6 (feed fan-out), res7 (chat &
            presence), res8 (auth & identity), res9 (community ↔ feed
            contract), res10 (operations & scaling guide).
Status:     Capstone reference. Link to the detail docs; don't
            duplicate them.

================================================================================
TABLE OF CONTENTS
================================================================================

  §1  System Portrait — One Diagram, One Paragraph
  §2  How Parts Talk — Sync, Async, and the Rules That Govern Each
  §3  How Parts Store — Which Data Goes Where, and Why
  §4  Best Practices — The Rules We Live By
  §5  Handling Many Students — The Load-Bearing Techniques
  §6  Growth Roadmap — From GA to Multi-Campus
  §7  The Plan Explained — Why This Design Wins

================================================================================
§1  SYSTEM PORTRAIT — ONE DIAGRAM, ONE PARAGRAPH
================================================================================

                         ┌──────────────────┐
   Clients (mobile/web)─►│  API GATEWAY     │  TLS, JWT, rate-limit,
                         └────────┬─────────┘  routing
                                  │
        ┌───────────┬─────────────┼────────────┬─────────────┐
        ▼           ▼             ▼            ▼             ▼
   ┌────────┐  ┌────────┐   ┌──────────┐  ┌────────┐   ┌─────────┐
   │IDENTITY│  │  FEED  │   │   CHAT   │  │COMMUNI-│   │  MEDIA  │
   │(tokens,│  │(posts, │   │(WS, msgs,│  │TY (mem-│   │(pre-    │
   │follows)│  │timelns)│   │presence) │  │bership)│   │signed)  │
   └───┬────┘  └───┬────┘   └────┬─────┘  └───┬────┘   └─────────┘
       │           │             │            │
       │  All state changes become EVENTS     │
       └───────────┴──────┬──────┴────────────┘
                          ▼
                  ┌───────────────┐
                  │     KAFKA     │  Durable event log. Everyone who
                  │(7 topics,     │  needs to know subscribes. Nobody
                  │ RF=3, outbox) │  asks anybody else directly.
                  └───────┬───────┘
                          │
        ┌─────────────────┼─────────────────────┐
        ▼                 ▼                     ▼
  ┌───────────┐   ┌───────────────┐   ┌─────────────────┐
  │ FAN-OUT   │   │ NOTIFICATION  │   │ SEARCH INDEXER  │
  │ WORKER    │   │ (push/email)  │   │ (Elasticsearch) │
  │(Redis)    │   └───────────────┘   └─────────────────┘
  └───────────┘

  THE ONE-PARAGRAPH VERSION:
  Seven small services, each owning ONE job and ONE database. When a
  user does something, the owning service writes to its database AND
  drops an event into Kafka (atomically, via the outbox pattern).
  Every other service that cares subscribes to that event and updates
  its own local copy of whatever it needs — nobody reads anybody
  else's database. Fast reads come from Redis caches that are built
  FROM the event stream and can be rebuilt at any time. Real-time
  chat uses WebSockets with Redis-routed inter-pod delivery. Auth is
  stateless JWT with a three-tier denylist for instant bans.
  Everything stateless autoscales on Kubernetes; everything stateful
  is replicated and survives single-node failure.

================================================================================
§2  HOW PARTS TALK — SYNC, ASYNC, AND THE RULES
================================================================================

── 2.1  TWO CHANNELS, STRICT USE CASES ─────────────────────────────

  ┌────────────────────────────────┬────────────────────────────────┐
  │ SYNC — gRPC internal,          │ ASYNC — Kafka events           │
  │        REST at the edge        │                                │
  ├────────────────────────────────┼────────────────────────────────┤
  │ Use when the caller NEEDS an   │ Use when state CHANGED and     │
  │ answer to proceed. Blocking.   │ others should REACT. Fire &    │
  │ Adds latency. Adds a failure   │ forget. Producer doesn't wait. │
  │ dependency.                    │ Consumer catches up later.     │
  ├────────────────────────────────┼────────────────────────────────┤
  │ Allowed ONLY for:              │ Used for EVERYTHING else:      │
  │  • Authorization checks        │  • "A post was created"        │
  │    ("can this user post in     │  • "A user joined a community" │
  │    community X?")              │  • "A user was banned"         │
  │  • Read-side enrichment        │  • "A message was sent"        │
  │    ("give me display names     │  • "A reaction was added"      │
  │    for these user IDs")        │                                │
  ├────────────────────────────────┼────────────────────────────────┤
  │ Hard limit: ONE hop per        │ Producer and consumer never    │
  │ user request. No chains.       │ know about each other. Add a   │
  │ Every call: 200ms timeout,     │ new consumer without touching  │
  │ circuit breaker, cached        │ the producer.                  │
  │ fallback.                      │                                │
  └────────────────────────────────┴────────────────────────────────┘

── 2.2  SYNC FLOW EXAMPLE — FETCHING A TIMELINE ────────────────────

      Client ──── GET /v1/feed/timeline ──► API Gateway
                      │
                      ▼ (verify JWT, route)
                 Feed Service
                      │
                      ├─► Redis ZRANGE timeline:{userId}   ◄── fast path
                      │   (sub-millisecond, 800 entries)
                      │
                      └─► Postgres (only if Redis miss,    ◄── fallback
                          or for celebrity pull-merge)
                      │
                      ▼
                 200 OK [posts]

  No other service was called. Author names/avatars come from a
  local author_snapshots table that Feed maintains BY CONSUMING
  user.events — not by asking Identity synchronously.

── 2.3  ASYNC FLOW EXAMPLE — CREATING A POST ───────────────────────

   Client ─── POST /v1/feed/posts ─► Feed Service

   INSIDE Feed Service (one DB transaction):
     INSERT INTO posts (...)
     INSERT INTO outbox (event_type='post.created', payload={...})
     COMMIT                          ◄── both succeed or both fail
       │
       ▼
   Outbox Relay (background poller)
     Reads outbox WHERE published=false → publishes to Kafka
     → marks published=true
       │
       ▼
   Kafka topic: post.events (partition key = post_id, 24 partitions)
       │
       ├────────────────┬────────────────────┬──────────────────┐
       ▼                ▼                    ▼                  ▼
   Fan-out Worker   Notification Svc    Search Indexer    Community Svc
   (if author has   (ping mentioned     (index post body  (increment
    < 1k followers,  users via FCM)      into ES)          post counter
    emit N fanout                                          if community
    commands →                                             post)
    Redis ZADD)

  Four consumers, zero coupling. The Feed Service doesn't know any
  of them exist. Adding a fifth (say, analytics) means ONE new
  consumer — zero changes anywhere else.

── 2.4  THE CONTRACTS THAT MAKE THIS SAFE ──────────────────────────

  Every Kafka event has a schema in Avro, stored in Schema Registry,
  enforced BACKWARD_TRANSITIVE. You cannot deploy a producer that
  emits a shape old consumers can't read — CI blocks the merge.

  Every gRPC service has a .proto contract, version-locked. Breaking
  a method signature requires a new versioned service (feed.v2).

  Details: res4 (events), res3 §7 (gRPC), res9 (cross-team example).

================================================================================
§3  HOW PARTS STORE — WHICH DATA GOES WHERE, AND WHY
================================================================================

── 3.1  POLYGLOT PERSISTENCE — RIGHT TOOL FOR EACH JOB ─────────────

  ┌──────────────┬──────────────────────┬───────────────────────────┐
  │ Store        │ Holds                │ Why this store            │
  ├──────────────┼──────────────────────┼───────────────────────────┤
  │ PostgreSQL   │ Posts, comments,     │ Relational data with      │
  │ (3 DBs: one  │ reactions, users,    │ transactions. Moderate    │
  │ per service) │ follows, communities,│ write rate (~700 tx/s     │
  │              │ memberships, outbox  │ peak). Needs joins,       │
  │              │ tables               │ constraints, ACID.        │
  ├──────────────┼──────────────────────┼───────────────────────────┤
  │ Cassandra    │ Chat messages only   │ High write volume (500    │
  │ (1 cluster)  │ (conversation_id →   │ msg/s), append-only,      │
  │              │ time-ordered msgs)   │ natural partitioning by   │
  │              │                      │ conversation, scales      │
  │              │                      │ linearly by adding nodes. │
  ├──────────────┼──────────────────────┼───────────────────────────┤
  │ Redis        │ Timelines (ZSET),    │ Sub-millisecond reads.    │
  │ (2 nodes:    │ presence (TTL keys), │ The hot path. All data    │
  │ feed-cache,  │ WS routing table,    │ here is DERIVED — can be  │
  │ chat-state)  │ typing indicators,   │ rebuilt from PG/Kafka if  │
  │              │ denylist cache,      │ lost.                     │
  │              │ dedup keys           │                           │
  ├──────────────┼──────────────────────┼───────────────────────────┤
  │ Kafka        │ Event log            │ Durable buffer. Producers │
  │ (3 brokers)  │ (7 topics, 7–30 day  │ never blocked by slow     │
  │              │ retention, compacted │ consumers. Replay to      │
  │              │ for user/community)  │ rebuild projections.      │
  ├──────────────┼──────────────────────┼───────────────────────────┤
  │ Elastic-     │ Full-text search     │ Inverted index. Fed by    │
  │ search       │ index (posts,        │ Kafka consumer. Fully     │
  │ (3 nodes)    │ comments, community  │ rebuildable.              │
  │              │ descriptions)        │                           │
  ├──────────────┼──────────────────────┼───────────────────────────┤
  │ S3/MinIO     │ Images, videos,      │ Object storage. Clients   │
  │              │ attachments          │ upload directly via       │
  │              │                      │ presigned URL. Never      │
  │              │                      │ touches our DBs.          │
  └──────────────┴──────────────────────┴───────────────────────────┘

── 3.2  THE TWO KINDS OF DATA ──────────────────────────────────────

  AUTHORITATIVE (source of truth)          DERIVED (rebuildable)
  ─────────────────────────────            ──────────────────────────
  • PostgreSQL tables                      • Redis timelines
  • Cassandra messages                     • Redis presence/routing
  • Kafka compacted topics                 • Elasticsearch index
    (latest user state)                    • Author snapshot tables
                                           • Membership cache tables
                                           • Denylist in-process cache

  If authoritative data is corrupted → restore from backup (PITR,
  Cassandra snapshots). Painful. Data loss possible.

  If derived data is corrupted → rebuild from authoritative + Kafka
  event log. Automated (res5). No data loss. Minutes, not hours.

  This distinction drives our operational calm: most "the data is
  wrong" incidents are derived-data problems with push-button fixes.

── 3.3  ONE DATABASE PER SERVICE — NO EXCEPTIONS ───────────────────

  Feed Service has its own Postgres. Community Service has its own.
  They CANNOT read each other's tables, even though both are "just
  Postgres." Enforced by network policy + separate credentials.

  When Feed needs to know "is user X a member of community Y?" it
  does NOT query Community's membership table. It queries its OWN
  local membership_cache table, which it built by consuming
  community.member.joined / community.member.left events.

  Why so strict? Shared databases become hidden coupling. If both
  services query the same table, neither team can change its schema
  without breaking the other. Isolation now = velocity later.

================================================================================
§4  BEST PRACTICES — THE RULES WE LIVE BY
================================================================================

── 4.1  ARCHITECTURE RULES ─────────────────────────────────────────

  BP-1   Clean Architecture in every service.
         Domain (entities) → Use Cases → Interface Adapters →
         Frameworks. Dependencies point INWARD only. Business
         rules have zero framework imports. Details: res1 §2.

  BP-2   One service, one database. No cross-DB queries.
         Enforced at the network layer (K8s NetworkPolicy).

  BP-3   Async first. Sync is the exception, not the default.
         Every sync call requires: timeout (200ms), circuit
         breaker (5 failures → open), cached fallback, and a
         justification in the design doc for why async won't do.

  BP-4   Events are immutable facts in the past tense.
         "post.created" not "create.post". Never modify a
         published event — publish a correction event instead.

  BP-5   Idempotent everything.
         Every write endpoint accepts an Idempotency-Key header.
         Every Kafka consumer handles duplicate delivery (natural
         keys or explicit dedup tables). Safe retries everywhere.

── 4.2  DATA & SCHEMA RULES ────────────────────────────────────────

  BP-6   Transactional outbox for every cross-boundary effect.
         Never do "write DB then publish Kafka" as two steps —
         the second can fail. Write BOTH to the DB in one
         transaction; a relay publishes from the outbox table.
         Details: res4 §7.

  BP-7   Schema evolution is backward-compatible.
         Kafka: Avro + Schema Registry + BACKWARD_TRANSITIVE.
         Database: expand → deploy → contract (never drop a
         column in the same release that stops writing to it).
         Details: res4 §5, res10 §3.4.

  BP-8   Partition keys chosen for ordering AND distribution.
         Kafka: key by the entity whose events must be ordered
         (post_id for post events, conversation_id for messages).
         Cassandra: partition by access pattern (conversation_id
         so "get recent messages" hits one partition).

  BP-9   TTLs on everything ephemeral.
         Presence keys: 30s. Typing: 5s. Dedup: 5min. Denylist
         JTI: token's remaining life. No unbounded growth.

── 4.3  OPERATIONAL RULES ──────────────────────────────────────────

  BP-10  Every service: /health/live and /health/ready with
         DIFFERENT semantics.
         Live = "am I deadlocked?" (never checks dependencies).
         Ready = "can I serve traffic NOW?" (checks dependencies).
         Details: res10 §2.4.

  BP-11  Every request: correlationId, propagated everywhere.
         HTTP header → gRPC metadata → Kafka envelope → log field.
         One grep gives you the full story. Details: res10 §5.3.

  BP-12  Every deployment: PodDisruptionBudget, graceful shutdown.
         Stateless: drain requests. Chat: send WS close 1012,
         clients reconnect with backoff. Consumers: commit
         offsets, then exit. Details: res10 §2.5.

  BP-13  Every failure mode: a degraded path, not an error page.
         Redis down → PG fallback. Identity slow → cached author
         snapshots. Search down → hide the search bar. Kafka
         down → outbox buffers. Details: res10 §9.

  BP-14  Every runbook: tested in a quarterly game day.
         Kill a broker. Kill Redis. Fail over PG. If the runbook
         is wrong, you find out on a Tuesday afternoon, not at
         3am. Details: res10 §10.2.

── 4.4  SECURITY RULES ─────────────────────────────────────────────

  BP-15  JWT verification everywhere, not just at the gateway.
         Defense in depth. If an internal route is accidentally
         exposed, the service still rejects unauthenticated
         requests. JWKS cached with 1-hour refresh.

  BP-16  Instant ban via three-tier denylist.
         T1 in-process (5s poll) → T2 Redis → T3 Kafka (durable).
         Token version bump invalidates ALL of a user's tokens
         at once. ~1 second from admin click to locked out.
         Details: res8.

  BP-17  Short access tokens, long refresh tokens, rotation on use.
         Access: 10 minutes. Refresh: 30 days, device-bound,
         rotated on every refresh with reuse detection (stolen
         refresh token triggers family revocation).

  BP-18  Validate at the boundary, trust inside.
         Input validation at the API layer (schema-enforced).
         Internal gRPC assumes clean inputs. No redundant
         validation deep in the stack.

── 4.5  DEVELOPMENT RULES ──────────────────────────────────────────

  BP-19  Contract-first integration.
         Before two teams integrate, they write and sign off on
         the contract doc (event schemas, gRPC protos, error
         codes, SLAs). See res9 for the template.

  BP-20  Load test before every phase exit.
         No feature ships until it meets its latency SLO under
         target load in staging. See res3 §10 phase gates.

  BP-21  New feature = new consumer, not a code change in an
         existing service.
         Want to add "trending posts"? New Kafka consumer that
         reads post.events + reaction.events, computes trending
         scores, writes its own Redis keys. Feed Service
         untouched. Details: res1 §7.

================================================================================
§5  HANDLING MANY STUDENTS — THE LOAD-BEARING TECHNIQUES
================================================================================

── 5.1  THE TRAFFIC PROFILE ────────────────────────────────────────

  Design point:  30,000 registered students (one ASTU campus).
  Peak hour:     12,000 concurrent (40% — lunch, evening, exam week).
  Read:write:    ~130:1 (people scroll far more than they post).

  ┌──────────────────────────┬──────────┬─────────────────────────┐
  │ Operation                │ Peak/sec │ Design capacity (3×)    │
  ├──────────────────────────┼──────────┼─────────────────────────┤
  │ Timeline reads (GET)     │   2,000  │   6,000                 │
  │ Post writes (POST)       │      15  │      45                 │
  │ Comment/reaction writes  │     700  │   2,100                 │
  │ Chat messages            │     500  │   1,500                 │
  │ Presence heartbeats      │   1,200  │   3,600                 │
  │ Search queries           │      50  │     150                 │
  └──────────────────────────┴──────────┴─────────────────────────┘

── 5.2  TECHNIQUE 1 — MAKE READS CHEAP (the 130:1 killer) ──────────

  Reads dominate 130-to-1, so the architecture makes every hot
  read a single Redis hit.

  Timeline read path:
      ZRANGE timeline:{userId} 0 49 WITHSCORES
      → sub-millisecond
      → 800 entries pre-built per user
      → no Postgres query on the happy path

  The cost: timelines must be PRE-BUILT. Every post triggers a
  fan-out to N follower timelines. That's the write-amplification
  trade-off — and it's worth it because writes are 130× rarer.

── 5.3  TECHNIQUE 2 — HYBRID FAN-OUT (the viral-post defuser) ──────

  Pure fan-out-on-write explodes when one user has 10,000 followers.
  One post → 10,000 Redis ZADDs → hotspot.

  The fix: a celebrity threshold.

      follower_count < 1,000  →  PUSH (fan-out on write)
                                 Cheap for the common case.
                                 p99 visibility: 5s.

      follower_count ≥ 1,000  →  PULL (fan-out on read)
                                 No fan-out work on post.
                                 Timeline read includes a merge
                                 query: "recent posts from my
                                 celebrity follows." p99 immediate.

  At 30k students, ~5 accounts will cross 1,000 followers. The pull
  query for 5 accounts is trivial. The 99.98% normal case stays on
  the fast push path. Details: res6.

── 5.4  TECHNIQUE 3 — KAFKA AS SHOCK ABSORBER ──────────────────────

  Bursts happen (exam results drop → everyone posts at once).
  Synchronous chains would block. We don't have any.

  Burst scenario: 5,000 posts in 1 second.
      → 5,000 DB writes succeed (PG handles 5k tx/s).
      → 5,000 outbox rows created.
      → Outbox relay drains at its own pace into Kafka.
      → Kafka holds the backlog (48 partitions, plenty of room).
      → Fan-out workers drain at ~12k ZADD/sec.
      → Timelines catch up in ~45 seconds.
      → Users posting see "success" immediately.
      → Users reading see the posts appear over the next minute.

  No component was overwhelmed. The burst stretched out in TIME
  instead of stretching any one system in LOAD.

── 5.5  TECHNIQUE 4 — STATELESS EVERYTHING (the clone-on-demand) ───

  Feed, Community, Identity, API Gateway, all workers: zero
  in-process state that matters. Request state lives in the
  request. Session state is in the JWT (self-contained) or Redis
  (shared). Kill any pod → another handles the next request with
  no warmup, no sticky sessions, no handoff protocol.

  Result: HPA adds pods during the lunch spike, removes them at
  night. You pay for load, not for peak capacity 24/7.

  Exception: Chat Service holds WebSockets. Those ARE sticky. But
  routing state (which pod holds which user's socket) lives in
  Redis, not in the pod. Kill a Chat pod → clients reconnect to
  another pod → that pod writes its own routing entries → delivery
  resumes. ~5 seconds of blip, zero message loss (messages were
  already persisted to Cassandra before delivery).

── 5.6  TECHNIQUE 5 — READ REPLICAS & THE RYOW WINDOW ──────────────

  All GETs route to PG read replicas. Writes go to primary.
  Replicas lag ~100ms typically.

  Problem: user posts, then immediately reads their own profile
  → might hit a replica that doesn't have their post yet →
  "my post disappeared!"

  Fix: Read-Your-Own-Write window. For 5 seconds after ANY write,
  that user's reads route to PRIMARY. Implemented as a client-side
  timestamp-in-cookie + server-side routing rule. Cheap, invisible,
  solves the one UX-visible consistency gap.

── 5.7  TECHNIQUE 6 — PRESENCE WITHOUT DB WRITES ───────────────────

  Naive presence: every heartbeat updates a users.last_seen column.
  1,200 heartbeats/sec × 1 DB write each = 1,200 writes/sec just
  for "is online" — more than all posts/comments/reactions combined.

  Our presence: SET presence:{userId} EX 30 in Redis. Key expires
  if no heartbeat for 30s → user shows offline. Zero DB writes.
  Redis handles 100k+ ops/sec; 1,200 is 1.2% utilization.

  Reading "who's online in this conversation" = one MGET on the
  participant list's presence keys. Sub-millisecond.

================================================================================
§6  GROWTH ROADMAP — FROM GA TO MULTI-CAMPUS
================================================================================

── 6.1  WHERE WE ARE ───────────────────────────────────────────────

  The build phases (0 → 8) from res3 §10 take us to General
  Availability: 30k ASTU students, full feature set, SLOs met.

  The roadmap below is POST-GA: what to build and scale as usage
  grows. Each horizon lists the TRIGGER (what tells you it's time),
  the WORK, and the REVISIT-WHEN checkpoints from earlier design
  docs that activate here.

── 6.2  HORIZON 1 — STABILIZE & POLISH (first ~quarter post-GA) ────

  TRIGGER:  GA complete. Real traffic flowing.

  ┌────────────────────────────────────────────────────────────────┐
  │ PRODUCT                                                        │
  │  • Ship ML-ranked timeline (rerank Redis ZSET at read time;    │
  │    push model already supports this — res6 §9 revisit).        │
  │  • Presence privacy controls ("appear offline" — res7 §3.7).   │
  │  • Search facets (filter by community, date, author type).     │
  ├────────────────────────────────────────────────────────────────┤
  │ PLATFORM                                                       │
  │  • Tune HPA thresholds based on real traffic (the 70% CPU /    │
  │    150ms p95 defaults are guesses until GA data arrives).      │
  │  • Close any runbook gaps found during beta incidents.         │
  │  • Automate the PG failover if self-managed; verify auto-      │
  │    failover if managed.                                        │
  │  • Add slow-query alerts (pg_stat_statements → Prometheus).    │
  ├────────────────────────────────────────────────────────────────┤
  │ SCALE CHECKPOINT                                               │
  │  • None expected. 3× headroom holds.                           │
  └────────────────────────────────────────────────────────────────┘

── 6.3  HORIZON 2 — SECOND CAMPUS (scale: 30k → ~100k) ─────────────

  TRIGGER:  Onboarding a second university.

  ┌────────────────────────────────────────────────────────────────┐
  │ PRODUCT                                                        │
  │  • Multi-tenant identity (campus_id as first-class dimension). │
  │  • Cross-campus communities (opt-in federation).               │
  │  • Campus-scoped search & discovery defaults.                  │
  ├────────────────────────────────────────────────────────────────┤
  │ PLATFORM                                                       │
  │  • Add campus_id to every event envelope + every partition     │
  │    strategy (Avro schema change — additive, backward-compat).  │
  │  • Raise HPA max replicas across the board (~1.5×).            │
  │  • Third PG read replica.                                      │
  │  • Review celebrity threshold — 100k users means ~20-30        │
  │    celebrities; pull-merge query still cheap but monitor.      │
  ├────────────────────────────────────────────────────────────────┤
  │ SCALE CHECKPOINT                                               │
  │  • Redis feed-cache: 100k × 800 entries × 60B ≈ 4.8 GB. Still  │
  │    fits on one 8GB node but approaching 60%. Plan Cluster.     │
  │  • Kafka partitions: still fine at 3× traffic.                 │
  │  • Cassandra: probably add a 4th node for disk headroom.       │
  └────────────────────────────────────────────────────────────────┘

── 6.4  HORIZON 3 — REGIONAL (scale: 100k → ~300k) ─────────────────

  TRIGGER:  Multiple campuses, 3× Horizon-2 traffic. This is the
            10× point where several "revisit when" flags from
            earlier docs fire.

  ┌────────────────────────────────────────────────────────────────┐
  │ PRODUCT                                                        │
  │  • Events & RSVP (new service — res1 §7 pattern: new consumer  │
  │    of community.events + user.events, own PG, own Redis keys). │
  │  • Analytics dashboard for community moderators.               │
  │  • Rich media in chat (video, audio messages — Media Service   │
  │    already handles uploads; Chat adds message-type support).   │
  ├────────────────────────────────────────────────────────────────┤
  │ PLATFORM — the big-ticket items                                │
  │  • Redis Cluster migration (res10 §4.5). 300k users × 800      │
  │    entries ≈ 14 GB. One node won't cut it. Hash-tagged keys,   │
  │    dual-write migration, cut over reads, decommission.         │
  │  • PG posts table partitioning by month (res10 §4.4 Stage 4).  │
  │    Cold partitions move to cheaper storage.                    │
  │  • Celebrity pull-cache (res6 §9 revisit). At 100+ celebrities │
  │    the per-read merge query gets heavier. Cache "recent        │
  │    celebrity posts" in a shared Redis key, refreshed every 2s. │
  │  • Dedicated WS gateway tier in front of Chat (res10 §4.2).    │
  │    Separates connection-holding from message-handling; lets    │
  │    each scale independently.                                   │
  ├────────────────────────────────────────────────────────────────┤
  │ PLATFORM — smaller but necessary                               │
  │  • Double Kafka partitions on high-throughput topics           │
  │    (feed.fanout.cmd, message.events: 48 → 96).                 │
  │  • Cassandra to 6 nodes.                                       │
  │  • Consider sharded Redis Pub/Sub for chat routing if          │
  │    single-channel throughput becomes a ceiling.                │
  └────────────────────────────────────────────────────────────────┘

── 6.5  HORIZON 4 — NATIONAL (scale: 300k → 1M+) ───────────────────

  TRIGGER:  Growth beyond what a single region comfortably serves.

  ┌────────────────────────────────────────────────────────────────┐
  │ PLATFORM — the hard projects                                   │
  │  • PG write sharding by user_id (res10 §4.4 Option B). Clean   │
  │    Architecture's Repository port makes this an adapter swap,  │
  │    not a rewrite — but it's still a multi-month project.       │
  │    Start when projected to hit 3k sustained write tx/s.        │
  │  • Multi-region deployment. Read replicas per region. Writes   │
  │    go to a home region (per-user home). Kafka MirrorMaker      │
  │    replicates events cross-region. Eventual consistency        │
  │    cross-region is acceptable for feed/community; chat stays   │
  │    region-local.                                               │
  │  • Lazy timeline push (res6 §9 revisit). At 1M users, eager    │
  │    push fans out to many timelines that are never read. Lazy   │
  │    push: mark timeline dirty, only build on first read.        │
  │    Trades first-read latency for write-side savings.           │
  ├────────────────────────────────────────────────────────────────┤
  │ WHAT DOESN'T CHANGE                                            │
  │  • The service boundaries. The event contracts. The outbox     │
  │    pattern. The Clean Architecture layering. All of these      │
  │    were chosen precisely because they don't need to change as  │
  │    we scale — only the adapters and the infrastructure behind  │
  │    them do.                                                    │
  └────────────────────────────────────────────────────────────────┘

── 6.6  ROADMAP TRIGGERS TABLE ─────────────────────────────────────

  Watch these numbers. When one crosses its threshold, pull the
  corresponding horizon item into the current quarter.

  ┌───────────────────────────────┬──────────┬─────────────────────┐
  │ Metric                        │ Trigger  │ Action              │
  ├───────────────────────────────┼──────────┼─────────────────────┤
  │ Registered users              │  > 90k   │ Horizon 2 prep      │
  │ Registered users              │  > 250k  │ Horizon 3 Redis     │
  │                               │          │ Cluster migration   │
  │ Celebrity accounts (≥1k fol.) │  > 100   │ Celebrity pull-     │
  │                               │          │ cache (res6 revisit)│
  │ PG primary write tx/sec (p95) │  > 2,500 │ Shard planning      │
  │ Redis feed-cache memory       │  > 60%   │ Cluster migration   │
  │ Chat concurrent WS (total)    │  > 50k   │ Dedicated WS        │
  │                               │          │ gateway tier        │
  │ Kafka consumer lag p99        │  > 30s   │ Partition increase  │
  │ (sustained, any group)        │          │ or more brokers     │
  │ Cross-region user complaints  │  notable │ Multi-region plan   │
  │ ("app is slow from city X")   │          │                     │
  └───────────────────────────────┴──────────┴─────────────────────┘

================================================================================
§7  THE PLAN EXPLAINED — WHY THIS DESIGN WINS
================================================================================

── 7.1  THREE BETS WE MADE ─────────────────────────────────────────

  BET 1 — Events over RPC.
    We said: "services talk by recording facts into a shared log,
    not by asking each other questions." Cost: eventual consistency,
    more moving parts (outbox, relay, schema registry). Payoff:
    total decoupling. Slow consumers don't block fast producers.
    Bursts buffer. Replay fixes corrupted projections. New features
    plug in as consumers without touching existing code.

  BET 2 — Derived state is cheap, authoritative state is sacred.
    We said: "optimize for rebuilding, not for never-losing." Cost:
    every cache/index needs a rebuild procedure (res5). Payoff:
    most incidents are a button-push, not a restore-from-backup.
    Operators sleep better when "Redis lost its data" means a
    10-minute automated rebuild, not a crisis.

  BET 3 — Clean Architecture in every service.
    We said: "business rules don't know about databases, frameworks,
    or transport." Cost: more interfaces, more files, more
    ceremony. Payoff: swapping Postgres for a sharded store
    (Horizon 4) is an adapter change. Swapping REST for gRPC didn't
    touch the use-case layer. Tests run without infrastructure.

── 7.2  THE THROUGH-LINE ───────────────────────────────────────────

  Every document in this series (res1–res10) answers the same
  question at a different level of detail:

      "How do we make this fast for students AND safe for us?"

  • res1 answered it with SERVICE BOUNDARIES — isolate failure.
  • res2 translated it to PLAIN ENGLISH — so everyone gets it.
  • res3 made it CONCRETE — exact contracts, exact phases, exact
    SLOs, exact risk mitigations.
  • res4 made it RELIABLE — the event system, outbox, replay,
    schema evolution.
  • res5 made it RECOVERABLE — step-by-step runbooks for every
    projection rebuild.
  • res6 made the feed FAST — hybrid fan-out, the 130:1 trade-off,
    burst handling.
  • res7 made chat REAL-TIME — WebSocket routing, TTL-based
    presence, REST fallback.
  • res8 made auth SECURE — short tokens, refresh rotation,
    instant-ban denylist.
  • res9 proved we can INTEGRATE — two teams, one contract,
    bounded blast radius.
  • res10 made it OPERABLE — run it, scale it, watch it, fix it.
  • This doc (res11) ties it TOGETHER — and points forward.

── 7.3  WHAT YOU SHOULD REMEMBER ───────────────────────────────────

  If you read nothing else, remember these five lines:

    1. Each service owns ONE database. Never reach across.
    2. Sync calls are expensive. Default to async events.
    3. Redis is a cache, not a store. It can always be rebuilt.
    4. Kafka is the shock absorber. Bursts stretch in time.
    5. The degradation ladder exists. Use it before panicking.

── 7.4  THE CONFIDENCE CHECK ───────────────────────────────────────

  This design handles 30k students today with 3× headroom. It
  scales to 300k with infrastructure changes only (more pods,
  Redis Cluster, PG partitioning) — no rewrites. It scales to 1M+
  with ONE hard project (PG sharding) that Clean Architecture
  makes tractable. And at every step, a failure in one component
  degrades one feature, never the whole platform.

  That's the plan. Go build.

────────────────────────────────────────────────────────────────────
END OF FINAL ARCHITECTURE SUMMARY
────────────────────────────────────────────────────────────────────
