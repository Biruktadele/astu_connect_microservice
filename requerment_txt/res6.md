════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — FEED GENERATION STRATEGY DEEP DIVE
Fan-out-on-write vs fan-out-on-read, and surviving a 5000-post burst
════════════════════════════════════════════════════════════════════════════════

Builds on:  res1 §6.2, res2 Technique 3, res3 Phase 3, res4 §7 (outbox)
Question:   Do we build each user's home feed the moment someone posts
            (push / fan-out-on-write), or only when they open the app to
            view it (pull / fan-out-on-read)?
Constraint: The system must stay healthy when 5,000 distinct users post
            simultaneously (e.g., a campus-wide announcement everyone
            reacts to at once).

================================================================================
TABLE OF CONTENTS
================================================================================

  §1  The Two Models — Mechanics Explained
  §2  Cost Analysis at Our Scale (30k users, 12k concurrent)
  §3  Trade-off Matrix
  §4  The 5,000-Post Burst — What Happens Under Each Model
  §5  Decision: Hybrid Push/Pull (and why)
  §6  Crash-Proofing Plan — Every Layer
  §7  Load Test Specification
  §8  Kill Switch & Degradation Ladder
  §9  Summary — One-Page Decision Record

================================================================================
§1  THE TWO MODELS — MECHANICS EXPLAINED
================================================================================

── 1.1  FAN-OUT-ON-WRITE  (PUSH MODEL — "build the feed when someone posts")

  When Tigist posts:
    1. INSERT INTO posts (source of truth, Postgres).
    2. For each of Tigist's 200 followers:
         ZADD timeline:{follower_id} {timestamp} {post_id}
       (Redis sorted set — the follower's pre-built feed.)

  When a follower opens the app:
    ZREVRANGE timeline:{me} 0 49  →  50 post IDs, already sorted,
                                       returned in sub-millisecond.

  Cost shape:
    • Write cost  = O(followers of the poster)
    • Read  cost  = O(1) — one Redis read, no joins, no sorting.

── 1.2  FAN-OUT-ON-READ  (PULL MODEL — "build the feed when someone views")

  When Tigist posts:
    1. INSERT INTO posts.        (that's it — no fan-out work)

  When a follower opens the app:
    SELECT p.* FROM posts p
      JOIN follows f ON f.followee_id = p.author_id
     WHERE f.follower_id = {me}
       AND p.created_at > {last_seen}
     ORDER BY p.created_at DESC
     LIMIT 50;

  Cost shape:
    • Write cost  = O(1) — just the insert.
    • Read  cost  = O(following × recent_posts_per_followee) — a join
                    across two tables, sorted, every single time the
                    user refreshes.

── 1.3  HYBRID  (our current design — res1 §6.2)

  PUSH for normal authors (< 1,000 followers):
    Their posts get written to followers' Redis timelines.

  PULL for "celebrity" authors (≥ 1,000 followers):
    Their posts are NOT pushed. At read time, we merge:
      (a) ZREVRANGE timeline:{me} …         (the push-built portion)
      (b) SELECT from posts WHERE author_id IN (my celebrity follows)
    Sorted in memory, paginated.

  Cost shape:
    • Write cost  = bounded at O(CELEBRITY_THRESHOLD) per post, no
                    matter how popular someone gets.
    • Read  cost  = O(1) Redis + one small, indexed PG query per
                    refresh (only for celebrity follows — most users
                    follow zero celebrities).

================================================================================
§2  COST ANALYSIS AT OUR SCALE
================================================================================

Inputs (from res3 §4):
  Total users                         30,000
  Peak concurrent                     12,000
  Avg follows per user                   200  (follower_count = following_count
                                               in aggregate)
  Peak post rate (normal)                 15  posts/sec
  Peak timeline read rate              2,000  refreshes/sec
  Read:write ratio                  ~130 : 1

── 2.1  PUSH — Work per second at normal peak

  Write amplification = posts/s × avg_followers
                       = 15 × 200
                       = 3,000 Redis ZADD/sec

  Redis single-node throughput: ~100,000 ops/sec (comfortable). 3k is
  trivial. Pipelined in batches of 100 → ~30 pipeline round-trips/sec.

  Postgres writes: 15 INSERT/sec (the posts themselves). Nothing.

  Read side: 2,000 ZREVRANGE/sec. Pure memory reads. Sub-millisecond.

                                               VERDICT: easily handled.

── 2.2  PULL — Work per second at normal peak

  Postgres writes: 15 INSERT/sec. Nothing.

  Read amplification = reads/s × cost_per_query
    Each timeline query joins `follows` (200 rows for this user)
    with `posts` (filtered by those 200 author_ids, recent only).
    With proper indexes (follows(follower_id), posts(author_id,
    created_at DESC)), each query is ~2–10 ms.

    2,000 queries/sec × ~5 ms each = ~10,000 ms of DB work per
    second. That means ~10 Postgres cores fully saturated JUST on
    timeline reads, before any other query (comments, profiles,
    reactions).

  Our Feed Postgres (res3 §4): primary + 2 read replicas. Say each
  replica gives ~8 cores of usable query capacity → 16 cores total.
  Timeline reads alone eat ~60% of that. Workable, but tight.

  And: no headroom. If read rate doubles (exam week, everyone
  refreshing), we're CPU-bound on Postgres. Adding read replicas
  helps linearly, but each replica costs real money and adds
  replication lag.

                                               VERDICT: workable at
                                               steady state but brittle;
                                               read-side scaling is
                                               expensive.

── 2.3  HYBRID — Work per second at normal peak

  Assume 1% of authors are "celebrities" (≥ 1,000 followers). In
  practice at a 30k-student campus, this is ≈ 5–20 accounts (student
  union, popular clubs, a handful of social stars).

  Push side: 99% of posts × avg ~150 followers (non-celebrity
  accounts skew smaller) ≈ 14.85 × 150 ≈ 2,230 ZADD/sec.

  Pull side: only users who follow ≥ 1 celebrity do the merge query,
  and that query is WHERE author_id IN (a list of ~5–20 IDs) — tiny,
  heavily cacheable, ~1 ms.

                                               VERDICT: best of both.
                                               Redis does the heavy
                                               lifting, PG handles a
                                               trickle of small
                                               celebrity queries.

================================================================================
§3  TRADE-OFF MATRIX
================================================================================

┌────────────────────────┬────────────────┬────────────────┬────────────────┐
│ Criterion              │   PUSH         │   PULL         │   HYBRID       │
│                        │ (fan-out-on-   │ (fan-out-on-   │                │
│                        │  write)        │  read)         │                │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Read latency (p50)     │ ~1 ms (Redis)  │ ~5 ms (PG      │ ~1–3 ms        │
│                        │                │ indexed join)  │ (Redis + tiny  │
│                        │                │                │  PG merge)     │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Read latency tail      │ Flat. Redis    │ Fat. Depends   │ Flat. Bounded  │
│ (p99)                  │ is predictable.│ on PG cache    │ by celebrity   │
│                        │                │ state, lock    │ query which is │
│                        │                │ contention,    │ small + hot    │
│                        │                │ vacuum.        │ (L2-cached).   │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Write latency          │ Post INSERT is │ Post INSERT is │ Same as PUSH.  │
│ (user-perceived)       │ synchronous    │ synchronous    │ Fan-out is     │
│                        │ (~20 ms).      │ (~20 ms).      │ fully async    │
│                        │ Fan-out is     │ No fan-out.    │ via outbox +   │
│                        │ ASYNC via      │                │ Kafka.         │
│                        │ Kafka — user   │                │                │
│                        │ never waits.   │                │                │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Storage overhead       │ Redis: 30k     │ Zero extra.    │ Same as PUSH   │
│                        │ users × 800    │ Just posts     │ (Redis ZSETs). │
│                        │ entries × ~48B │ table.         │                │
│                        │ (member +      │                │                │
│                        │  score)        │                │                │
│                        │ ≈ 1.1 GB RAM.  │                │                │
│                        │ Cheap.         │                │                │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Celebrity problem      │ SEVERE. A 10k- │ No problem.    │ SOLVED by      │
│ (one account with many │ follower post  │ Celebrity post │ threshold.     │
│  followers)            │ = 10k ZADDs.   │ is one INSERT, │ Celebrity uses │
│                        │ A viral account│ like any other.│ pull path.     │
│                        │ posting 5×/min │                │ Write cost     │
│                        │ = 50k ZADD/min │                │ capped at      │
│                        │ just from them.│                │ threshold.     │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Freshness / staleness  │ ~1–5s lag      │ Perfectly      │ Push portion:  │
│                        │ (outbox poll + │ fresh — you    │ ~1–5s.         │
│                        │ Kafka consume  │ query the      │ Pull portion:  │
│                        │ + ZADD). See   │ source of      │ perfectly      │
│                        │ res3 §3 NFR:   │ truth on every │ fresh.         │
│                        │ p99 ≤ 5s.      │ read.          │                │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Inactive-user waste    │ We fan out to  │ No waste.      │ Same waste as  │
│ (users who never log   │ dormant users' │ Dormant users  │ PUSH, but      │
│  in)                   │ timelines for  │ never query.   │ timelines are  │
│                        │ nothing. At    │                │ capped at 800  │
│                        │ 30k total /    │                │ entries so     │
│                        │ 12k active,    │                │ memory is      │
│                        │ ~60% of ZADDs  │                │ bounded.       │
│                        │ go to inactive │                │ Acceptable.    │
│                        │ timelines.     │                │                │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ New-user experience    │ Empty timeline │ Immediately    │ PUSH side:     │
│ (just signed up, just  │ until the      │ full — the     │ empty.         │
│  followed 20 people)   │ people they    │ query pulls    │ PULL side:     │
│                        │ follow post    │ historical     │ shows celebrity│
│                        │ something new. │ posts too.     │ posts.         │
│                        │ Mitigated by   │                │ Mitigated by   │
│                        │ backfill job   │                │ backfill job   │
│                        │ (res3 §7.4).   │                │ (same).        │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Deletion handling      │ Must ZREM from │ Automatic —    │ Must ZREM from │
│ (post deleted)         │ every follower │ deleted_at     │ followers'     │
│                        │ timeline.      │ filter in the  │ timelines.     │
│                        │ O(followers).  │ query.         │ Bounded by     │
│                        │                │                │ threshold.     │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Implementation         │ Medium. Need   │ Simple. Just a │ Medium+. PUSH  │
│ complexity             │ fan-out worker,│ SQL query.     │ infra + merge  │
│                        │ Redis ZSETs,   │                │ logic at read. │
│                        │ backfill,      │                │ Celebrity      │
│                        │ delete cleanup.│                │ detection +    │
│                        │                │                │ flag.          │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Failure mode when      │ Posts succeed  │ Posts succeed  │ Posts succeed  │
│ fan-out/cache layer    │ (PG). Timeline │ (PG). Reads    │ (PG). Timeline │
│ dies                   │ stale until    │ still work —   │ degrades to    │
│                        │ worker         │ no cache layer │ pull-only      │
│                        │ recovers.      │ to die.        │ (slower but    │
│                        │ Reads fall     │                │ correct).      │
│                        │ back to pull   │                │ res3 AC-N5.    │
│                        │ (slower).      │                │                │
├────────────────────────┼────────────────┼────────────────┼────────────────┤
│ Burst resilience       │ GOOD — Kafka   │ GOOD on write, │ GOOD — same    │
│ (5,000 posts at once)  │ absorbs the    │ BAD on read if │ Kafka buffer.  │
│ — see §4               │ burst. Worker  │ the burst      │ Worker bounded │
│                        │ drains at its  │ coincides with │ by celebrity   │
│                        │ pace. No sync  │ read spike (PG │ threshold so   │
│                        │ pressure.      │ gets hammered).│ amplification  │
│                        │                │                │ is capped.     │
└────────────────────────┴────────────────┴────────────────┴────────────────┘

================================================================================
§4  THE 5,000-POST BURST — WHAT HAPPENS UNDER EACH MODEL
================================================================================

Scenario definition:
  5,000 distinct users each create one post within a 1-second window.
  (Realistic trigger: ASTU announces exam schedules, everyone posts a
  reaction at once. Or a coordinated flash-mob post. Or a load test.)

Key observation: this is 5,000 DIFFERENT users posting ONCE each, so
per-user rate limiting (60 writes/min/user — res3 §3) does NOT help.
Every individual request is legitimate.

── 4.1  BURST UNDER PURE PUSH ──────────────────────────────────────

  Timeline of what happens:

    t=0s     5,000 HTTP POST /v1/feed/posts arrive at API Gateway.

    t=0–2s   Gateway spreads across 3–20 Feed Service pods.
             Each request:
               • Validates input (CreatePost use case).
               • BEGIN; INSERT INTO posts; INSERT INTO outbox; COMMIT;
               • Returns 201 to client.

             5,000 transactions in ~2s = 2,500 tx/sec on Feed
             Postgres primary.

             POSTGRES CAPACITY CHECK:
               A single PG primary (res3 sizing) handles ~5,000–
               10,000 short transactions/sec. 2,500 tx/s is within
               range. Connection pooling (PgBouncer, res1 §6.4)
               prevents connection exhaustion: even if 20 Feed pods
               × 10 connections each try to connect, PgBouncer
               multiplexes onto ~20 actual PG connections.

             ✅ HTTP layer survives. Users get 201 in < 200 ms.

    t=0–5s   Outbox relays (2 replicas, res4 §8) poll and publish.
             At 100 rows/batch, 50ms poll interval:
               2 relays × (1000 ms / 50 ms) × 100 rows
               = 4,000 events/sec drained → Kafka.
             5,000 outbox rows drained in ~1.25s.

             KAFKA CAPACITY CHECK:
               post.events has 24 partitions, 3 brokers, RF=3. Kafka
               handles 100k+ msg/sec easily. 5,000 msgs is a blip.

             ✅ Kafka absorbs the burst with zero stress.

    t=1–10s  Feed Service's own Kafka consumer reads post.events and
             enumerates followers for each post (via Identity gRPC
             GetFollowerIds streaming, res3 §7.1).

             5,000 posts × avg 200 followers = 1,000,000
             timeline.write commands emitted to feed.fanout.cmd.

             This is the AMPLIFICATION MOMENT. 1M messages hit
             feed.fanout.cmd over ~10 seconds.

             KAFKA CAPACITY CHECK (again):
               feed.fanout.cmd has 48 partitions. 1M msgs ≈ 150 MB
               at 150 B/msg. Partition spread: 1M / 48 ≈ 21k msgs
               per partition. Kafka's per-partition throughput is
               ~10 MB/s. 21k × 150 B = ~3 MB per partition. Drains
               in seconds.

             ✅ Kafka still fine. This is its job.

    t=5–60s  Fan-out workers (2–20 replicas, res3 §4) consume from
             feed.fanout.cmd and ZADD into Redis.

             Each worker processes ~2,000–5,000 commands/sec when
             pipelining Redis writes in batches of 100.
             At 4 workers: 4 × 3,000 = 12,000 ZADD/sec.
             1,000,000 ZADDs / 12,000 per sec ≈ 83 seconds.

             During this ~80s window, consumer lag on
             feed.fanout.cmd spikes. Autoscaler (HPA on Kafka lag
             metric) kicks in at lag > threshold, spins up more
             workers → lag drains faster.

             REDIS CAPACITY CHECK:
               Single Redis node handles 100k+ ops/sec. Even if all
               12k ZADD/sec hit one node, it's 12% utilization.
               Memory impact: 1M new ZSET entries × ~48 B ≈ 48 MB.
               Negligible against our ~3 GB timeline footprint.

             ✅ Redis survives. Workers drain the backlog. Worst
                case: some followers see the new posts ~80s late
                instead of the normal ~5s. Nobody notices.

    t=90s    System is back to steady state. No component crashed.
             No requests failed. Feeds are consistent.

  WHERE COULD PURE PUSH STILL CRASH?

    Risk A: Postgres primary overwhelmed by INSERT burst.
      If 5,000 posts arrive in < 500 ms instead of 1s, that's
      10,000 tx/sec — right at PG's ceiling. Mitigation in §6.1.

    Risk B: Celebrity burst — what if 100 of the 5,000 posters have
      5,000 followers each? Then amplification is 100 × 5,000 =
      500,000 ZADDs just from celebrities, plus 4,900 × 200 =
      980,000 from everyone else = 1.48M total. Still manageable,
      but if celebrity_count × follower_count grows unbounded, pure
      push has no ceiling. This is why HYBRID exists.

── 4.2  BURST UNDER PURE PULL ──────────────────────────────────────

    t=0–2s   Same HTTP + Postgres INSERT path as push. No outbox
             fan-out rows needed (no fan-out), so actually LIGHTER
             on PG writes (one INSERT instead of two per post).

             ✅ Write side: even healthier than push.

    t=0+     THE DANGER IS ON THE READ SIDE.

             If the same event that triggered 5,000 posts also
             triggers 12,000 users to open the app and refresh
             (plausible — "something big just happened, let me
             check"), we get:

               12,000 simultaneous timeline queries on Postgres.

             Each query: JOIN follows × posts, ~5 ms, ~5 ms of CPU.
             12,000 queries × 5 ms = 60,000 ms of CPU work in a
             short window. With 16 cores across 2 replicas, that's
             ~4 seconds of solid CPU saturation.

             CONNECTION STARVATION:
               12,000 concurrent requests × 1 DB query each, but
               PgBouncer pool has ~20–40 backend connections. The
               other ~11,960 requests QUEUE at PgBouncer.
               Queueing is fine — it's backpressure — but if queue
               depth × avg_query_time exceeds client timeouts
               (1s from res3 §3), those requests FAIL with 504.

             ❌ Likely outcome: a fraction of timeline reads time
                out. Users see errors or infinite spinners. No data
                loss, but availability SLO (res3 §3: Feed read
                99.9%) is blown.

    THE FUNDAMENTAL PROBLEM WITH PULL AT OUR SCALE:
      Read load scales with CONCURRENT READERS, not with post
      volume. We can't shed read load without degrading the user
      experience. Push shifts the work to write-time where it's
      (a) asynchronous, (b) bufferable by Kafka, (c) invisible to
      users.

── 4.3  BURST UNDER HYBRID (our choice) ───────────────────────────

    Identical to pure push (§4.1) with one improvement:

    If any of the 5,000 posters happen to be celebrities (≥ 1,000
    followers), their posts skip the fan-out path entirely. No
    timeline.write commands emitted for them. The amplification
    factor is hard-capped at CELEBRITY_THRESHOLD per post.

    Worst-case amplification: 5,000 posts × 1,000 followers each
    (every poster is exactly at the threshold) = 5,000,000 ZADDs.
    Still bounded. At 12k ZADD/sec drain rate: ~7 minutes to clear.
    During those 7 minutes: posts visible via pull-path immediately
    (the merge query sees them in Postgres); push-path catches up.

    No unbounded growth. No crash.

================================================================================
§5  DECISION: HYBRID PUSH/PULL (reaffirming res1 §6.2)
================================================================================

  WE CHOOSE HYBRID. Reasoning, in priority order:

  1. OUR READ:WRITE RATIO IS ~130:1.
     With reads dominating by two orders of magnitude, making reads
     cheap (push's O(1) Redis read) is the single biggest lever on
     total system cost. Pull makes every one of those 2,000 reads/sec
     hit Postgres. Push makes them hit Redis memory.

  2. BURST RESILIENCE IS STRUCTURAL, NOT ACCIDENTAL.
     Push + outbox + Kafka gives us a natural shock absorber. A burst
     of writes becomes a backlog in Kafka, not a pile-up of failed
     HTTP requests. The user-facing path (HTTP → PG insert → 201)
     never waits for fan-out. See §4.1.

  3. CELEBRITY THRESHOLD CAPS THE ONE WEAKNESS OF PUSH.
     Pure push has unbounded write amplification. The hybrid threshold
     turns this into a bounded quantity we can capacity-plan for.
     At 30k users, setting THRESHOLD = 1,000 means at most ~30
     celebrity accounts (0.1% of users could plausibly hit this),
     and the pull-merge query for those ~30 author_ids is trivial.

  4. GRACEFUL DEGRADATION IS BUILT IN.
     If Redis dies → timeline reads fall back to the pull query path
     (slower, but correct). If the fan-out worker dies → Kafka lag
     builds up, timelines go stale by seconds-to-minutes, but nothing
     is lost and nothing 500s. The system is NEVER hard-down because
     of the push machinery. (res3 AC-N5, AC-N7.)

  5. PULL-ONLY IS ACCEPTABLE AT LAUNCH, INADEQUATE AT PEAK.
     In res3 §10 Phase 2, Timeline v0 is pull-only. This is
     deliberate: it's simpler, proves the data model, and handles
     early low traffic. Phase 3 adds the push layer. We are not
     rejecting pull — we are layering push ON TOP of it so that
     pull becomes the fallback instead of the critical path.

  WHAT WE ARE NOT DOING — and why:

    ✗ Lazy push (fan out only to recently-active followers).
      Adds complexity (tracking last-seen per user, deciding
      active/inactive). The inactive-user waste at our scale
      (~60% of ZADDs) costs ~2 GB of Redis RAM — not worth
      optimizing yet. Revisit if user base grows 10×.

    ✗ Rank-at-read (compute a relevance score when the user opens
      the app, instead of pure reverse-chronological).
      Future epic. Reverse-chron is fine for MVP and the push
      model supports it natively (ZSET score = timestamp). Adding
      ranking later = re-scoring ZSET entries at read time, which
      is an additive change.

================================================================================
§6  CRASH-PROOFING PLAN — EVERY LAYER
================================================================================

Goal: 5,000 posts in 1 second causes ZERO crashes, ZERO data loss,
and at worst a temporary (≤ 2 min) increase in fan-out lag.

── 6.1  HTTP INGRESS LAYER (API Gateway + Feed Service pods) ───────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  Gateway global rate       5,000 req/s ceiling   If burst exceeds total
  limit (not per-user —     on POST /feed/posts   capacity, gateway returns
  a ceiling on the route)   (well above normal    429 instead of forwarding
                            15/s, below PG        to a saturated backend.
                            meltdown point).      Clients retry with
                                                  backoff. No backend
                                                  crash.

  HPA on Feed Service       Scale 3→20 pods on    More pods = more
                            CPU > 70% OR p95      concurrent HTTP handlers
                            latency > 150 ms.     = burst absorbed without
                            Scale-up window: 30s. queueing at the pod.

  Request timeout           Server-side 2s hard   A slow request fails
                            timeout on CreatePost cleanly (500/504) instead
                            use case.             of holding a connection
                                                  forever and starving the
                                                  pool.

  Bounded worker pool       Max in-flight         If all handlers are busy,
  per pod                   requests per pod =    new connections queue at
                            500 (tunable).        the TCP/accept level, not
                            Excess → 503.         inside the app. Prevents
                                                  goroutine/thread/memory
                                                  explosion inside a pod.

── 6.2  DATABASE LAYER (Feed Postgres primary) ─────────────────────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  PgBouncer (transaction    Pool size: 20 backend The primary never sees
  mode)                     connections.          more than 20 concurrent
                            Client-side pool:     connections, no matter
                            per-pod 10, shared    how many pods exist.
                            via PgBouncer.        PG's max_connections
                                                  (default 100) is never
                                                  approached. No "too many
                                                  connections" crash.

  Statement timeout         statement_timeout =   A runaway INSERT (e.g.,
                            5s on the Feed app    waiting on a lock) gets
                            role.                 killed instead of
                                                  blocking the pool
                                                  forever.

  Short transactions        CreatePost tx =       Lock hold time is
                            2 INSERTs + COMMIT.   microseconds. No
                            No SELECTs inside     long-running transaction
                            the write tx.         holds row locks during
                                                  the burst → no lock
                                                  convoys.

  Outbox in same tx         INSERT INTO outbox    The burst produces 5,000
  (res4 §7)                 is part of the same   post rows + 5,000 outbox
                            atomic tx as the      rows. Both inserts are
                            post INSERT.          append-only, no index
                                                  hotspots (UUIDv7 PKs
                                                  spread across btree).

  Checkpoint tuning         checkpoint_timeout =  A 5k-insert burst
                            5min, max_wal_size =  generates ~10 MB of WAL.
                            4GB.                  Won't trigger a
                                                  checkpoint mid-burst
                                                  (which would cause an
                                                  I/O spike and latency
                                                  tail).

── 6.3  OUTBOX RELAY LAYER ─────────────────────────────────────────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  FOR UPDATE SKIP LOCKED    (res4 §7.5)           Multiple relay replicas
                                                  poll concurrently without
                                                  blocking each other.
                                                  Burst drains in parallel.

  Bounded batch size        batch_size = 100      Each poll cycle has
                                                  predictable memory
                                                  footprint. Relay never
                                                  tries to load 5,000 rows
                                                  into memory at once.

  Poll-immediately-on-full  If batch was full     Under burst, relay runs
                            (100 rows), skip the  hot (no sleep), draining
                            50ms sleep and poll   at max speed. Under idle,
                            again instantly.      it sleeps and stays
                                                  cheap.

  Relay autoscale           HPA on outbox_        If 2 relays can't keep
                            unpublished_rows      up (drain rate < fill
                            gauge > 1,000 for     rate), add relays.
                            > 30s → add replica.  FOR UPDATE SKIP LOCKED
                            Max 6 relays.         ensures they don't step
                                                  on each other.

── 6.4  KAFKA LAYER ────────────────────────────────────────────────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  Producer config           acks=all,             If a broker is slow, the
  (res4 §7.5)               enable.idempotence=   producer retries safely.
                            true,                 No duplicate events.
                            max.in.flight=5,      acks=all means the event
                            retries=MAX_INT,      is durable before the
                            delivery.timeout=     relay marks the outbox
                            120s.                 row as published.

  Partition count           post.events: 24       1M messages / 48
                            feed.fanout.cmd: 48   partitions ≈ 21k per
                                                  partition. Well within
                                                  per-partition throughput
                                                  (~10 MB/s ≈ 70k msg/s
                                                  at 150 B/msg).

  Broker disk               Each broker: NVMe,    5,000 posts × 500 B +
                            100 GB free minimum.  1M fanout cmds × 150 B
                                                  ≈ 150 MB total. × RF=3
                                                  = 450 MB on disk. Noise.

  min.insync.replicas       = 2 (with RF=3)       One broker can die
                                                  mid-burst and producers
                                                  still get acks. No
                                                  stall, no data loss.

── 6.5  FAN-OUT WORKER LAYER ───────────────────────────────────────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  Consumer autoscale        HPA on consumer lag:  Burst → lag spikes →
  (HPA on Kafka lag         lag > 10,000 for      more workers spin up →
  metric via KEDA)          > 30s → +1 replica.   lag drains faster. Self-
                            Max 20 replicas       healing. Scale-down after
                            (≤ 48 partitions).    5 min of lag < 1,000.

  Redis pipelining          Batch ZADDs in groups One round-trip per 100
                            of 100 commands per   ZADDs instead of per
                            pipeline.             ZADD. 100× throughput.
                                                  Bounded memory per batch.

  Bounded consumer fetch    max.poll.records =    Worker never pulls more
                            500                   messages than it can
                                                  process before the next
                                                  poll. Prevents rebalance
                                                  storms from slow
                                                  processing.

  max.poll.interval.ms      = 300,000 (5 min)     If a worker stalls (e.g.,
                                                  Redis is slow), Kafka
                                                  waits 5 min before
                                                  kicking it out of the
                                                  group. Prevents rebalance
                                                  churn during transient
                                                  slowness.

  Idempotent processing     ZADD is naturally     A worker crash + restart
  (res4 §7.6)               idempotent (same      + re-consume of the same
                            member + score =      partition from the last
                            no-op).               committed offset is safe.
                                                  No duplicate timeline
                                                  entries.

  DLT after max retries     After 10 failed       A poison message (e.g.,
  (res4 §4.2 R4)            ZADDs for one         malformed post_id) goes
                            command → DLT.        to feed-fanout-worker.dlt
                                                  instead of blocking the
                                                  partition forever.

── 6.6  REDIS LAYER ────────────────────────────────────────────────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  maxmemory + eviction      maxmemory = 8 GB      Burst adds ~50 MB. Even
                            maxmemory-policy =    if we never trimmed
                            noeviction (on the    timelines, hitting
                            timeline DB; we       maxmemory with noeviction
                            manage size via       causes write errors
                            ZREMRANGEBYRANK,      (caught by worker, sent
                            not eviction).        to DLT), not a crash.
                                                  In practice we're at
                                                  ~3 GB, nowhere near.

  Timeline cap              Every ZADD batch is   No single timeline grows
  (res3 §5.1)               followed by           unbounded. A user
                            ZREMRANGEBYRANK       followed by 5,000 burst
                            timeline:{u} 0 -801   posters gets 5,000 ZADDs
                            (keep last 800).      but immediately trimmed
                                                  to 800. Memory bounded.

  Client-side timeout       Redis command         If Redis is slow (e.g.,
                            timeout = 500 ms in   forking for BGSAVE), the
                            fan-out worker.       worker's ZADD fails fast,
                                                  retries, doesn't hang
                                                  the Kafka consumer.

  Replica + AOF             1 replica, AOF        Primary crash mid-burst:
  (res3 R4)                 everysec.             lose ≤ 1s of ZADDs.
                                                  Replica promotes. Missing
                                                  entries rebuilt by RB-6
                                                  or just re-ZADD'd when
                                                  the fan-out worker's
                                                  consumer re-reads from
                                                  its last committed
                                                  offset.

── 6.7  CROSS-CUTTING ──────────────────────────────────────────────

  MECHANISM                 CONFIG                WHY IT PREVENTS CRASH
  ───────────────────────── ───────────────────── ─────────────────────────
  Circuit breakers on       Identity gRPC         If the burst also
  sync deps (res1 §4.1)     GetFollowerIds: open  overwhelms Identity
                            after 5 failures in   (unlikely — different
                            10s. Half-open probe  service, different DB),
                            every 30s.            Feed's post-event
                                                  consumer stops calling
                                                  it, lag builds in Kafka
                                                  (buffered, not lost),
                                                  resumes when Identity
                                                  recovers.

  Alerting                  • outbox_unpublished  On-call is paged BEFORE
                              > 5,000 for > 1 min users notice stale feeds.
                            • kafka consumer lag  Early intervention
                              (feed.fanout.cmd)   (manual scale-up, check
                              > 50,000 for > 2min for poison messages)
                            • redis_used_memory   prevents escalation.
                              > 80%
                            • pg_connections
                              > 80% of pool

  Runbook                   res5 RB-6 (timeline   If something DOES break,
                            rebuild) + RB-10      recovery is a documented
                            (DLT reprocessing).   procedure, not a novel
                                                  debugging session.

================================================================================
§7  LOAD TEST SPECIFICATION (proves §6 actually works)
================================================================================

Must pass before Phase 3 exit (res3 §10).

── 7.1  TEST: POST-BURST-5K ────────────────────────────────────────

  Setup:
    • Staging environment at production sizing (res3 §4).
    • 5,000 synthetic user accounts, each with 150–250 followers
      (normal distribution around 200).
    • Baseline steady-state load running (2,000 timeline reads/sec,
      15 posts/sec) for 5 min before burst.

  Execution:
    • At t=0, fire 5,000 POST /v1/feed/posts from 5,000 distinct
      JWTs, concurrency = 5,000 (all at once, not ramped).
    • Continue baseline read load throughout.

  Pass criteria:
    ☐  ≥ 99.5% of burst POSTs return 2xx.
       (Up to 0.5% may get 429/503 from gateway shedding — acceptable.)
    ☐  p99 latency of burst POSTs < 2,000 ms (res3 §3 hard max).
    ☐  p99 latency of concurrent timeline READs stays < 500 ms
       during and after the burst (reads must not be collateral
       damage).
    ☐  Zero 5xx from Feed Service (503 from bounded-pool shed is
       OK; 500 from unhandled exception is NOT).
    ☐  Zero Postgres connection errors in logs.
    ☐  Kafka consumer lag (feed.fanout.cmd) returns to < 1,000
       within 3 minutes of burst end.
    ☐  All 5,000 posts appear in a sampled follower's timeline
       within 5 minutes of burst end (p99 freshness).
    ☐  No pod OOMKilled. No pod CrashLoopBackOff.
    ☐  Redis memory delta < 100 MB.

── 7.2  TEST: POST-BURST-5K-CELEBRITY ──────────────────────────────

  Same as 7.1 but 100 of the 5,000 posters are flagged as
  celebrities (given 5,000 synthetic followers each).

  Additional pass criteria:
    ☐  feed.fanout.cmd receives ZERO timeline.write commands with
       source author_id in the celebrity set (verified by consuming
       the topic and filtering).
    ☐  Celebrity posts appear in follower timelines via the
       pull-merge path within 1 refresh (immediate — it's a PG
       query on fresh data).

── 7.3  TEST: POST-BURST-5K-DEGRADED ───────────────────────────────

  Same as 7.1 but with one dependency killed mid-burst:

  Variant A — Kill 1 Kafka broker at t=0.5s.
    ☐  All pass criteria from 7.1 still met (acks=all + RF=3
       tolerates 1 broker loss).

  Variant B — Kill Redis primary at t=0.5s.
    ☐  Burst POSTs still succeed (PG path unaffected).
    ☐  Timeline reads degrade to pull path (slower p99, but < 1s).
    ☐  After Redis replica promotion (~10s) + RB-6 rebuild (~10min),
       push path recovers.

  Variant C — Kill 1 fan-out worker pod at t=0.5s.
    ☐  All pass criteria from 7.1 still met. Remaining workers +
       autoscaled replacement drain the backlog.

================================================================================
§8  KILL SWITCH & DEGRADATION LADDER
================================================================================

If production is burning and we need to shed load RIGHT NOW, in
order of increasing aggressiveness:

  LEVEL 1 — Shed fan-out, keep writes.
    Feature flag: FANOUT_ENABLED = false
    Effect: CreatePost still writes to PG + outbox. Outbox relay
            still publishes post.events. But the Feed consumer that
            emits feed.fanout.cmd is paused. No timeline writes.
    User impact: New posts don't appear in push-path timelines.
                 Pull-merge path still shows them (for celebrity
                 authors immediately; for normal authors only via
                 the PG fallback when Redis timeline is empty/stale).
                 Feeds feel slower/staler but functional.
    Recovery: Re-enable flag. Consumer resumes from its committed
              offset. Backlog drains. Timelines catch up.

  LEVEL 2 — Shed reads to stale cache.
    Feature flag: TIMELINE_PG_FALLBACK = false
    Effect: Timeline reads serve ONLY from Redis ZSET. No PG merge
            query, no PG fallback. If Redis ZSET is empty → empty
            feed shown.
    User impact: Some users (new signups, post-Redis-flush) see
                 empty feeds. Everyone else sees a slightly stale
                 feed (missing celebrity posts until push catches
                 up). Zero PG read load from timelines.
    Use when: PG replicas are CPU-pegged and we need to shed read
              load immediately.

  LEVEL 3 — Read-only mode.
    Feature flag: WRITES_ENABLED = false
    Effect: POST /v1/feed/posts returns 503 with Retry-After.
    User impact: Can't post. Can still read.
    Use when: PG primary is the bottleneck and we need breathing
              room to scale/fix it.

  LEVEL 4 — Full maintenance mode.
    Gateway returns 503 for all /v1/feed/* routes.
    Use when: Everything is on fire. Buy time.

  All flags are runtime-toggleable (Helm value → ConfigMap →
  watched by the app, no redeploy needed). Each level is documented
  in the on-call runbook with exact toggle commands.

================================================================================
§9  SUMMARY — ONE-PAGE DECISION RECORD
================================================================================

┌──────────────────────┬───────────────────────────────────────────────────┐
│ Question             │ Do we build feeds on POST (push) or on VIEW       │
│                      │ (pull)?                                           │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Decision             │ HYBRID PUSH/PULL.                                 │
│                      │ • Push (fan-out-on-write) for authors with        │
│                      │   < 1,000 followers. Timeline pre-built in Redis. │
│                      │ • Pull (fan-out-on-read) for "celebrity" authors  │
│                      │   with ≥ 1,000 followers. Merged at read time.    │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Primary driver       │ Read:write ratio is ~130:1 at our scale. Making   │
│                      │ reads cheap (O(1) Redis) dominates total cost.    │
│                      │ Pull puts every read on Postgres → expensive and  │
│                      │ brittle under read spikes.                        │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Why hybrid, not pure │ Pure push has unbounded write amplification for   │
│ push                 │ high-follower accounts. The celebrity threshold   │
│                      │ caps amplification at a known constant we can     │
│                      │ capacity-plan for.                                │
├──────────────────────┼───────────────────────────────────────────────────┤
│ 5,000-post burst     │ SURVIVES by design. The HTTP path (PG insert +    │
│ handling             │ outbox insert) completes in ~200 ms regardless of │
│                      │ fan-out state. Fan-out is fully async:            │
│                      │   Outbox → Kafka → Worker → Redis                 │
│                      │ Each layer buffers. Kafka absorbs the 1M-command  │
│                      │ amplification. Workers drain at their pace        │
│                      │ (autoscaled on lag). Worst case: ~80s of stale    │
│                      │ timelines. Zero errors. Zero data loss.           │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Crash-proof          │ Gateway route-level rate ceiling (5k/s).          │
│ mechanisms (top 5)   │ PgBouncer bounds PG connections (20 max).         │
│                      │ Outbox + SKIP LOCKED drains writes in parallel.   │
│                      │ Kafka is the elastic buffer (sized for 100× this).│
│                      │ Worker HPA on consumer lag (self-healing drain).  │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Degraded mode        │ Redis down → pull-only (slow but correct).        │
│                      │ Worker down → timelines stale (Kafka holds        │
│                      │ backlog, nothing lost).                           │
│                      │ PG primary down → writes fail cleanly (503),      │
│                      │ reads continue from replicas + Redis.             │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Proof                │ Load test POST-BURST-5K (§7) is a Phase 3 exit    │
│                      │ criterion. Must pass all 9 assertions before      │
│                      │ shipping.                                         │
├──────────────────────┼───────────────────────────────────────────────────┤
│ Revisit when         │ • User base > 300k (10× growth) — Redis timeline  │
│                      │   memory becomes non-trivial; consider lazy push. │
│                      │ • Celebrity count > 100 — pull-merge query grows; │
│                      │   consider caching celebrity-posts separately.    │
│                      │ • Adding ML ranking — push model still works      │
│                      │   (re-score at read); evaluate then.              │
└──────────────────────┴───────────────────────────────────────────────────┘

════════════════════════════════════════════════════════════════════════════════
END
════════════════════════════════════════════════════════════════════════════════
