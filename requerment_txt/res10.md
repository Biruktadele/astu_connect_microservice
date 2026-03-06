════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — OPERATIONS & SCALING GUIDE
Running the system, growing it, watching it, and fixing it when it breaks
════════════════════════════════════════════════════════════════════════════════

Audience:   Platform operators, SREs, and on-call engineers.
Purpose:    End-to-end playbook for operating ASTU Connect in production.
            Covers cold start, scaling up, monitoring, incident response
            (chat outages, database failures), and graceful degradation.
Builds on:  res1 (architecture), res3 (API contracts), res4 (event system),
            res5 (replay runbooks), res6 (feed design), res7 (chat design),
            res8 (auth/identity), res9 (community integration).
Status:     Living document. Update after every incident post-mortem.

================================================================================
TABLE OF CONTENTS
================================================================================

  §1   System At A Glance — What You're Operating
  §2   Running The System — Cold Start & Dependency Order
  §3   Day-2 Operations — Deploys, Config Changes, Rotations
  §4   Scaling The System — Horizontal, Vertical, Data Tier
  §5   Watching For Problems — Signals, Dashboards, Alerts
  §6   When Chat Breaks — Diagnosis & Recovery
  §7   When The Database Breaks — Diagnosis & Recovery
  §8   When Kafka / Redis / Search Breaks — Quick Reference
  §9   Emergency Degradation Ladder — Kill Switches
  §10  Whole-Plan Summary — The Operating Model On One Page

================================================================================
§1  SYSTEM AT A GLANCE — WHAT YOU'RE OPERATING
================================================================================

── 1.1  THE SEVEN SERVICES ─────────────────────────────────────────

  You're running seven stateless service deployments, plus workers,
  plus five stateful data systems. Everything runs on Kubernetes.

  ┌─────────────────────┬──────────────┬─────────────────────────────┐
  │ Service             │ Type         │ What it does                │
  ├─────────────────────┼──────────────┼─────────────────────────────┤
  │ API Gateway         │ Stateless    │ TLS, JWT verify, rate-limit │
  │ Identity Service    │ Stateless    │ Login, tokens, follow graph │
  │ Feed Service        │ Stateless    │ Posts, comments, timelines  │
  │ Chat Service        │ WS Stateful  │ Messages, presence, typing  │
  │ Community Service   │ Stateless    │ Communities, membership     │
  │ Notification Svc    │ Kafka cons.  │ Push + email fan-out        │
  │ Search Indexer      │ Kafka cons.  │ Elasticsearch upkeep        │
  ├─────────────────────┼──────────────┼─────────────────────────────┤
  │ Feed Fan-out Worker │ Kafka cons.  │ Writes Redis timelines      │
  │ Outbox Relay (×N)   │ Poller       │ PG outbox → Kafka           │
  │ Media Service       │ Stateless    │ Presigned S3 URLs           │
  └─────────────────────┴──────────────┴─────────────────────────────┘

── 1.2  THE FIVE DATA SYSTEMS ──────────────────────────────────────

  ┌──────────────┬───────────────────────────┬────────────────────────┐
  │ System       │ Config                    │ What depends on it     │
  ├──────────────┼───────────────────────────┼────────────────────────┤
  │ PostgreSQL   │ 1 primary + 2 replicas    │ Feed, Community,       │
  │              │ PgBouncer, sync replica   │ Identity (writes HARD  │
  │              │                           │ depend; reads fallback)│
  ├──────────────┼───────────────────────────┼────────────────────────┤
  │ Cassandra    │ 3-node, RF=3, quorum      │ Chat only (messages)   │
  ├──────────────┼───────────────────────────┼────────────────────────┤
  │ Redis        │ 2 instances: feed-cache   │ Feed timelines (soft), │
  │              │ + chat-state, each w/     │ Chat routing (soft),   │
  │              │ replica, AOF everysec     │ Denylist cache (soft)  │
  ├──────────────┼───────────────────────────┼────────────────────────┤
  │ Kafka        │ 3 brokers, RF=3,          │ All async: fan-out,    │
  │              │ min.insync=2, acks=all    │ notifs, search, outbox │
  ├──────────────┼───────────────────────────┼────────────────────────┤
  │ Elasticsearch│ 3-node, alias-based idx   │ Search only (soft dep) │
  └──────────────┴───────────────────────────┴────────────────────────┘

  "Soft" = the dependent service degrades but doesn't fail outright.
  "Hard" = the dependent service returns errors until recovery.

── 1.3  CURRENT SCALE TARGETS ──────────────────────────────────────

  Design point:   30,000 total users
  Peak concurrent: 12,000 (40% of total)
  Timeline reads:  2,000 /sec
  Post writes:     15 /sec
  Chat messages:   500 /sec
  WS heartbeats:   1,200 /sec

  Headroom target: 3× — we size for 13,000 req/s to serve 4,400 peak.
  When any axis exceeds 60% of provisioned capacity, plan the next
  scaling step BEFORE it becomes urgent.

================================================================================
§2  RUNNING THE SYSTEM — COLD START & DEPENDENCY ORDER
================================================================================

── 2.1  STARTUP DEPENDENCY GRAPH ───────────────────────────────────

  Services will crash-loop until their dependencies are healthy. Start
  in this order (each tier must pass health checks before the next):

      TIER 0 — INFRASTRUCTURE
         PostgreSQL  ●─────┐
         Cassandra   ●─────┤
         Redis       ●─────┼───── must be reachable
         Kafka       ●─────┤      before any service starts
         Elasticsearch●────┘
            │
            ▼
      TIER 1 — CONTROL PLANE
         Schema Registry  ●───── must serve schemas before
                                 any producer starts
            │
            ▼
      TIER 2 — CORE SERVICES
         Identity Service ●───── must be up to issue tokens
         API Gateway      ●───── needs Identity's JWKS
            │
            ▼
      TIER 3 — DOMAIN SERVICES (parallel)
         Feed Service       ●
         Chat Service       ●
         Community Service  ●
            │
            ▼
      TIER 4 — WORKERS & CONSUMERS (parallel)
         Outbox Relay (per service) ●
         Feed Fan-out Worker        ●
         Notification Service       ●
         Search Indexer             ●
         Media Service              ●

── 2.2  LOCAL DEVELOPMENT BRING-UP ─────────────────────────────────

  Single command brings up all infra + services:

      $ docker-compose up

  Compose file orders via `depends_on` with health checks. First boot
  takes ~90s (Cassandra bootstrap is the long pole). Subsequent boots
  with persisted volumes take ~20s.

  Verify:
      $ curl -s localhost:8080/health/ready | jq .
      # Expect: {"status":"ok","checks":{"postgres":"ok",
      #          "redis":"ok","kafka":"ok"}}

      $ docker-compose logs -f feed-service   # tail one service

  Teardown:
      $ docker-compose down           # stop, keep data
      $ docker-compose down -v        # stop, WIPE data (careful)

── 2.3  PRODUCTION BRING-UP (KUBERNETES) ───────────────────────────

  Infra tier is managed by your cloud provider (managed Postgres,
  managed Kafka, etc.) or by separate Helm charts. This section
  covers the APPLICATION tier only.

  Step 1 — Verify infrastructure health.

      $ kubectl get pods -n data-tier
      # All pods Running, READY column = N/N

      $ kubectl exec -n data-tier postgres-0 -- pg_isready
      $ kubectl exec -n data-tier kafka-0 -- \
          kafka-topics.sh --bootstrap-server localhost:9092 --list

  Step 2 — Deploy control-plane tier.

      $ helm upgrade --install schema-registry ./charts/schema-registry \
          -n platform -f values-prod.yaml --wait

      $ helm upgrade --install identity ./charts/identity \
          -n identity -f values-prod.yaml --wait

      $ helm upgrade --install gateway ./charts/api-gateway \
          -n gateway -f values-prod.yaml --wait

  Step 3 — Deploy domain services (parallel safe).

      $ for svc in feed chat community; do
          helm upgrade --install $svc ./charts/$svc \
            -n $svc -f values-prod.yaml &
        done; wait

  Step 4 — Deploy workers.

      $ for w in fanout-worker outbox-relay notification \
                 search-indexer media; do
          helm upgrade --install $w ./charts/$w \
            -n workers -f values-prod.yaml &
        done; wait

  Step 5 — Verify the stack end-to-end.

      $ ./scripts/smoke-test.sh prod
      # Runs: login → post → read timeline → send msg → search
      # Expect: all green

── 2.4  HEALTH CHECK SEMANTICS ─────────────────────────────────────

  Every pod exposes two endpoints. Kubernetes uses both.

  /health/live  — "Am I deadlocked?"
    Returns 200 if the process event loop is responsive.
    Kubernetes kills the pod on repeated failure.
    NEVER check downstream dependencies here — if Postgres
    goes down we want the pod to STAY UP and serve from cache.

  /health/ready — "Can I serve traffic RIGHT NOW?"
    Returns 200 if:
      • Process started successfully.
      • Required dependencies (PG primary for write-capable
        services, Cassandra for Chat) responded to a ping in
        the last 10 seconds.
      • Warm-up complete (JWKS cached, denylist loaded).
    Kubernetes removes the pod from the load balancer on failure
    but does NOT kill it. Pod rejoins when it returns 200.

── 2.5  GRACEFUL SHUTDOWN ──────────────────────────────────────────

  On SIGTERM (rolling deploy, node drain), each pod:

  Stateless services (Feed, Community, Identity, Gateway):
    1. Flip /health/ready to 503 → removed from LB.
    2. Wait 5s for in-flight requests to drain.
    3. Close DB / Redis / Kafka connections cleanly.
    4. Exit 0.

  Chat Service (holds WebSockets — special handling):
    1. Flip /health/ready to 503 → no new WS connections routed.
    2. For each held connection:
       • Send {"t":"error","code":"server_restart","reconnect":true}
       • Close with WS code 1012 (Service Restart)
       • DELETE ws_route:{userId} from Redis
    3. Wait up to 15s for clients to reconnect to OTHER pods.
    4. Exit 0.
    Clients reconnect with exponential backoff + jitter to avoid
    thundering herd. They resync missed messages from Cassandra.

  Kafka consumers (Fan-out, Notification, Search):
    1. Flip /health/ready to 503.
    2. Stop polling. Finish processing the current batch.
    3. Commit offsets. Close consumer.
    4. Exit 0.
    Kafka rebalances partitions to remaining pods.

================================================================================
§3  DAY-2 OPERATIONS — DEPLOYS, CONFIG CHANGES, ROTATIONS
================================================================================

── 3.1  DEPLOYING A NEW VERSION ────────────────────────────────────

  Standard rolling deploy for one service:

      $ helm upgrade feed ./charts/feed \
          -n feed \
          --set image.tag=$GIT_SHA \
          --wait --timeout 5m

  Kubernetes respects PodDisruptionBudget (maxUnavailable=1). One
  pod terminates, replacement becomes Ready, then the next.

  Pre-deploy checklist:
    ☐  CI passed (tests + schema compatibility check).
    ☐  Schema Registry updated if this version emits a new event
       shape (see res4 §5). BACKWARD_TRANSITIVE enforced.
    ☐  Database migrations applied SEPARATELY before the app deploy
       (expand → deploy → contract pattern — never drop a column in
       the same release that stops writing to it).
    ☐  Announced in #platform-ops with rollback command ready.

  Rollback (fast):
      $ helm rollback feed        # previous revision
      $ helm rollback feed 0      # last known GOOD revision

── 3.2  CHANGING CONFIGURATION ─────────────────────────────────────

  Three tiers of config, from most to least volatile:

  A) Feature flags & thresholds — ConfigMap, watched at runtime.
     NO pod restart needed.

        $ kubectl patch configmap feed-config -n feed \
            --patch '{"data":{"FANOUT_ENABLED":"false"}}'

     Services watch the ConfigMap and reload within ~5 seconds.
     Full list of runtime-toggleable flags:

        FANOUT_ENABLED           true/false   (Feed)
        TIMELINE_PG_FALLBACK     true/false   (Feed)
        WRITES_ENABLED           true/false   (Feed/Community)
        CELEBRITY_THRESHOLD      integer      (Feed, default 1000)
        DENYLIST_POLL_INTERVAL   seconds      (all, default 5)

  B) Secrets (DB passwords, signing keys) — Kubernetes Secrets,
     REQUIRE pod restart to pick up.

        $ kubectl create secret generic identity-signing-key \
            --from-file=private.pem=/path/to/new-key.pem \
            -n identity --dry-run=client -o yaml | kubectl apply -f -
        $ kubectl rollout restart deployment/identity -n identity

  C) Structural config (replica counts, resource limits) — Helm
     values, redeploy required.

        $ helm upgrade feed ./charts/feed -n feed \
            --reuse-values --set replicaCount=10

── 3.3  ROTATING SIGNING KEYS (Identity) ───────────────────────────

  Access tokens are RS256-signed. Keys expire yearly. Rotation
  procedure (zero-downtime):

    1. Generate new keypair.
    2. Add new PUBLIC key to JWKS alongside the old one.
       → All services that verify tokens will accept BOTH.
    3. Wait for JWKS cache refresh across all pods (~1 hour
       interval, or force with `kubectl rollout restart`).
    4. Switch Identity to SIGN with the new private key.
       → New access tokens use new kid; old tokens still verify
         with old public key.
    5. Wait for all old access tokens to expire
       (ACCESS_TOKEN_TTL = 10 min, so wait 15 min to be safe).
    6. Remove old public key from JWKS.

── 3.4  DATABASE MIGRATIONS ────────────────────────────────────────

  Rule: EXPAND → DEPLOY → CONTRACT. Never break backward
  compatibility in a single step.

  Example — renaming a column:
    Step 1 (expand):  ALTER TABLE ADD new_col; backfill; add trigger
                      old_col → new_col.
    Step 2 (deploy):  App reads new_col, writes both.
    Step 3 (deploy):  App reads & writes new_col only.
    Step 4 (contract):DROP trigger; DROP old_col.

  Run migrations as a Kubernetes Job BEFORE the app deploy:

      $ kubectl apply -f migrations/job-feed-v42.yaml
      $ kubectl wait --for=condition=complete \
          job/feed-migrate-v42 -n feed --timeout=10m

  Long-running migrations (> 30s) on large tables MUST use
  batched UPDATEs with sleep between batches to avoid replication
  lag spikes and lock contention.

================================================================================
§4  SCALING THE SYSTEM — HORIZONTAL, VERTICAL, DATA TIER
================================================================================

── 4.1  HORIZONTAL POD AUTOSCALING (the default) ───────────────────

  Every stateless service has an HPA. You normally don't touch
  this — Kubernetes scales automatically. But you need to know the
  bounds:

  ┌─────────────────────┬─────┬─────┬─────────────────────────────┐
  │ Deployment          │ Min │ Max │ Autoscale trigger           │
  ├─────────────────────┼─────┼─────┼─────────────────────────────┤
  │ api-gateway         │  3  │ 10  │ CPU > 70% OR p95 > 250ms    │
  │ identity            │  3  │ 10  │ Refresh req rate > 100/s    │
  │ feed                │  3  │ 20  │ CPU > 70% OR p95 > 150ms    │
  │ chat                │  3  │ 30  │ WS count > 1,800 per pod    │
  │ community           │  2  │ 10  │ CPU > 70%                   │
  │ fanout-worker       │  2  │ 20  │ feed.fanout.cmd lag > 10k   │
  │ notification        │  2  │  8  │ *.events lag > 100k         │
  │ search-indexer      │  2  │  6  │ post.events lag > 100k      │
  │ outbox-relay        │  1  │  6  │ Unpublished rows > 1k       │
  └─────────────────────┴─────┴─────┴─────────────────────────────┘

  To manually bump (e.g., before a known traffic event):

      $ kubectl scale deployment/feed -n feed --replicas=15
      # HPA will scale back down after the event if load drops.

  To raise the MAX (the system is growing permanently):

      $ helm upgrade feed ./charts/feed -n feed \
          --reuse-values --set autoscaling.maxReplicas=30

── 4.2  SCALING CHAT (WebSocket constraints) ───────────────────────

  Chat is the trickiest to scale because WS connections pin to pods.

  The hard cap: ~2,000 concurrent sockets per pod (file descriptor
  + memory limits). At 12,000 concurrent users with 80% on chat
  that's 9,600 sockets → minimum 5 pods. We run min=3 for HA and
  let HPA add more when ws_connections_current > 1,800.

  Scaling UP is cheap — just add pods. New connections route to
  new pods via the load balancer's least-connection algorithm.

  Scaling DOWN is disruptive — terminating a pod drops its sockets.
  Clients reconnect (backoff + jitter), but that's a visible blip.
  HPA is configured with a slow scale-down cooldown (10 min) to
  avoid flapping.

  At > 50k concurrent (future growth): move to Redis-pub/sub
  SHARDED by conversation_id prefix, or migrate to a dedicated
  WS gateway tier that proxies to the Chat app.

── 4.3  SCALING THE FEED FAN-OUT PATH ──────────────────────────────

  The fan-out pipeline is: Post → Outbox → Kafka → Fan-out Worker
  → Redis ZADD. Each stage scales independently.

  ┌──────────────────┬──────────────────────────────────────────────┐
  │ Bottleneck       │ How to relieve it                            │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ Outbox relay lag │ Scale outbox-relay pods. Check the PG index  │
  │ (unpublished     │ on outbox.published_at IS NULL — must exist. │
  │  rows growing)   │                                              │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ feed.fanout.cmd  │ Scale fanout-worker pods (HPA does this      │
  │ lag growing      │ automatically on lag > 10k). If MAX hit,     │
  │                  │ raise maxReplicas. Check Redis isn't the     │
  │                  │ bottleneck (see §4.5).                       │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ Kafka itself     │ Add partitions to feed.fanout.cmd            │
  │ (rare)           │ (currently 48). Partitions can only go UP.   │
  │                  │ One-way door. Plan carefully.                │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ Celebrity posts  │ Lower CELEBRITY_THRESHOLD (default 1000).    │
  │ cause spikes     │ At 500 → more authors use pull path →        │
  │                  │ less fan-out work, more read-time merge work.│
  │                  │ Trade-off: PG read replicas see more load.   │
  └──────────────────┴──────────────────────────────────────────────┘

── 4.4  SCALING POSTGRESQL ─────────────────────────────────────────

  Current:  1 primary + 2 read replicas + PgBouncer.
  Write ceiling: ~5,000 tx/sec on a single primary.
  Our peak writes: ~15 posts/sec + ~200 comments/sec + ~500
  reactions/sec ≈ 715 tx/sec. 7× headroom today.

  Read scaling ladder (do these IN ORDER as load grows):

    STAGE 1 (now): Two read replicas. All GETs route to replicas
                   via the ReadRepository pattern. Replication lag
                   budget: 500ms (monitored, alert on > 2s).

    STAGE 2:       Add third read replica. Route by geographic
                   region if applicable.

    STAGE 3:       Shed more reads to Redis. The timeline path
                   already does this — extend to post-body cache
                   and comment-list cache with short TTLs.

    STAGE 4:       Partition the posts table by month (range
                   partitioning on created_at). Queries almost
                   always hit the most recent 2 partitions.

  Write scaling (only when you've exhausted the above):

    Option A:      Bigger primary (vertical). Simple but has a
                   ceiling. Good to ~10k tx/sec.

    Option B:      Shard by user_id (horizontal). Feed Service
                   already routes all queries via a Repository
                   interface — the shard router plugs in there.
                   This is a large project; don't start it until
                   you're projected to hit 3k tx/sec.

── 4.5  SCALING REDIS ──────────────────────────────────────────────

  Current:  Two single-node instances (feed-cache, chat-state),
            each with a replica.

  Feed-cache sizing:
    30k users × 800 timeline entries × ~60 bytes/entry ≈ 1.4 GB.
    8 GB node → 5.7× headroom on memory.
    Ops/sec: fan-out does ~3,000 ZADD/sec at peak + ~2,000
    ZRANGE/sec on reads = 5,000 ops/sec. A single Redis handles
    ~100k simple ops/sec. 20× headroom.

  Chat-state sizing:
    ~10 MB total (see res7 §2.6). Negligible. This instance is
    effectively free.

  When to move to Redis Cluster:
    • Memory > 60% of node and you can't evict more (feed-cache
      uses noeviction — timelines must stick).
    • Ops/sec > 50k sustained.
    • Single-AZ failure takes down the node and 10-second replica
      promotion isn't fast enough for your SLO.

  Cluster migration path:
    1. Spin up Cluster with hash-tag-aware keys. Timeline keys
       become timeline:{user_id} → {user_id} is the hash tag.
    2. Dual-write period (old + cluster).
    3. Cut reads over to cluster.
    4. Stop writes to old node. Decommission.

── 4.6  SCALING CASSANDRA (Chat storage) ───────────────────────────

  Current:  3-node cluster, RF=3, quorum reads/writes.
  Partition key: conversation_id. Messages cluster by TIMEUUID
  message_id DESC — recent messages first.

  Cassandra scales linearly by adding nodes. When to add:

    • Disk usage > 50% on any node (with RF=3, losing one node
      means the other two temporarily hold all data).
    • Write latency p99 > 10ms sustained.
    • Read latency p99 > 50ms sustained.

  To add a node:
      1. Provision new node, same DC configuration.
      2. Node auto-bootstraps, streams its token range from peers.
      3. Run `nodetool cleanup` on ALL old nodes after bootstrap
         completes (reclaims space for ranges they no longer own).

  Watch for: wide partitions. A single very active conversation
  (10k+ messages) becomes a hot partition. Mitigation: bucket
  the partition key as (conversation_id, month_bucket) if any
  conversation exceeds 100 MB.

── 4.7  SCALING KAFKA ──────────────────────────────────────────────

  Current:  3 brokers, RF=3, min.insync.replicas=2.

  Partition count is the lever. More partitions = more consumer
  parallelism. Current allocation (res4 §6):

      feed.fanout.cmd     48 partitions  (highest throughput)
      message.events      48 partitions
      post.events         24 partitions
      comment.events      24 partitions
      reaction.events     24 partitions
      user.events         12 partitions  (compacted)
      community.events    12 partitions  (compacted)

  Partitions can ONLY increase. Each partition adds broker load
  (file handles, replication). Rule: don't exceed ~4,000 total
  partitions per broker on current hardware.

  To add partitions:
      $ kafka-topics.sh --alter \
          --topic feed.fanout.cmd \
          --partitions 96 \
          --bootstrap-server kafka-0:9092

  ⚠ Adding partitions reshuffles key→partition mapping. For
  non-compacted topics this is fine (ordering per key is only
  guaranteed WITHIN a partition; new keys go elsewhere). For
  COMPACTED topics (user.events, community.events) this breaks
  "latest value per key" semantics. Don't change compacted topic
  partition counts — do a side-by-side topic migration instead.

  To add brokers:
      1. Provision new broker, same cluster config.
      2. Use kafka-reassign-partitions.sh to rebalance existing
         partitions onto the new broker.
      3. Throttle the reassignment to avoid saturating the cluster
         during the move.

================================================================================
§5  WATCHING FOR PROBLEMS — SIGNALS, DASHBOARDS, ALERTS
================================================================================

── 5.1  THE FOUR GOLDEN SIGNALS (per service) ──────────────────────

  Every service exposes Prometheus metrics. Every service has a
  dashboard showing these four signals. Open the dashboard FIRST
  when responding to a page.

  ┌───────────────┬──────────────────────────┬────────────────────┐
  │ Signal        │ Metric                   │ Healthy range      │
  ├───────────────┼──────────────────────────┼────────────────────┤
  │ TRAFFIC       │ http_requests_total      │ Smooth curve.      │
  │               │ (rate, by endpoint)      │ Spikes OK if       │
  │               │                          │ matched by         │
  │               │                          │ autoscaler.        │
  ├───────────────┼──────────────────────────┼────────────────────┤
  │ ERRORS        │ http_requests_total      │ < 0.1% 5xx.        │
  │               │ {status=~"5.."} /        │ 4xx is user error  │
  │               │ http_requests_total      │ — ignore unless    │
  │               │                          │ spiking (attack).  │
  ├───────────────┼──────────────────────────┼────────────────────┤
  │ LATENCY       │ http_request_duration_   │ p50 < 50ms         │
  │               │ seconds (histogram p95)  │ p95 < 150ms        │
  │               │                          │ p99 < 400ms        │
  ├───────────────┼──────────────────────────┼────────────────────┤
  │ SATURATION    │ CPU %, memory %,         │ CPU < 70%          │
  │               │ connection pool usage    │ Mem < 80%          │
  │               │                          │ Pool < 80%         │
  └───────────────┴──────────────────────────┴────────────────────┘

── 5.2  SYSTEM-SPECIFIC SIGNALS (the ones that actually page) ──────

  Beyond golden signals, these are the leading indicators of
  trouble for OUR specific architecture:

  ┌─────────────────────────────┬─────────────┬────────────────────┐
  │ Metric                      │ Alert at    │ What it means      │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ kafka_consumer_lag          │ > 1k  WARN  │ Consumer can't     │
  │ {group="fanout-worker"}     │ > 10k CRIT  │ keep up with fan-  │
  │                             │             │ out commands.      │
  │                             │             │ Timelines going    │
  │                             │             │ stale. See §4.3.   │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ kafka_consumer_lag          │ > 100k WARN │ Notifications or   │
  │ {group="notification"}      │             │ search index       │
  │ {group="search-indexer"}    │             │ falling behind.    │
  │                             │             │ Usually self-      │
  │                             │             │ heals. Scale pods. │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ feed_outbox_unpublished_    │ > 5k  WARN  │ Outbox relay       │
  │ rows                        │             │ stuck. Events not  │
  │                             │             │ reaching Kafka.    │
  │                             │             │ Check relay logs.  │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ pg_replication_lag_seconds  │ > 2s  WARN  │ Read replicas      │
  │                             │ > 10s CRIT  │ serving stale      │
  │                             │             │ data. Users see    │
  │                             │             │ "my post           │
  │                             │             │ disappeared" bugs. │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ redis_memory_used_bytes /   │ > 80% WARN  │ Approaching        │
  │ redis_maxmemory_bytes       │ > 90% CRIT  │ maxmemory. With    │
  │                             │             │ noeviction policy, │
  │                             │             │ writes will FAIL.  │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ chat_ws_connections_current │ > 1,800/pod │ Chat pod near      │
  │                             │       WARN  │ socket cap. HPA    │
  │                             │             │ should scale. If   │
  │                             │             │ at max replicas:   │
  │                             │             │ raise the cap.     │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ chat_message_delivery_      │ p99 > 500ms │ Inter-pod routing  │
  │ latency_seconds             │       WARN  │ or Cassandra       │
  │                             │ p99 > 2s    │ write slow. See    │
  │                             │       CRIT  │ §6.                │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ cassandra_write_latency_    │ p99 > 10ms  │ Cassandra under    │
  │ seconds                     │       WARN  │ pressure. Compac-  │
  │                             │             │ tion backlog or    │
  │                             │             │ disk saturation.   │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ identity_denylist_poll_     │ > 15s WARN  │ Denylist cache     │
  │ age_seconds                 │             │ stale. Banned      │
  │                             │             │ users might still  │
  │                             │             │ have access        │
  │                             │             │ briefly.           │
  ├─────────────────────────────┼─────────────┼────────────────────┤
  │ kafka_dlt_messages_total    │ > 0   WARN  │ Poison messages in │
  │ (rate over 5m)              │             │ a dead-letter      │
  │                             │             │ topic. Investigate │
  │                             │             │ → res5 RB-10.      │
  └─────────────────────────────┴─────────────┴────────────────────┘

── 5.3  TRACING & LOG CORRELATION ──────────────────────────────────

  Every inbound request gets a correlationId (UUID, minted at the
  API Gateway). It propagates through:
    • HTTP headers (X-Correlation-Id)
    • gRPC metadata
    • Kafka event envelope (see res4 §2)
    • Structured log lines (JSON field)

  To trace one request end-to-end:
      1. Get the correlationId from the client report or a log line.
      2. Tempo: search by trace attribute correlation.id={id}.
         See every span across all services.
      3. Loki: query `{service=~".+"} | json | correlationId="{id}"`
         for the log lines.

  Structured log format (every line):
      {"ts":"...","level":"info","service":"feed",
       "useCase":"CreatePost","correlationId":"...",
       "userId":"...","msg":"...","duration_ms":12}

── 5.4  THE DAILY CHECKLIST ────────────────────────────────────────

  On-call runs this once per shift:

    ☐  All HPAs in green band (not pinned at min OR max).
    ☐  No sustained consumer lag on any Kafka group.
    ☐  PG replication lag < 500ms on both replicas.
    ☐  Redis memory < 60% on both instances.
    ☐  DLT topics empty (or known issues documented).
    ☐  No pods in CrashLoopBackOff.
    ☐  Cert expiry > 30 days (TLS + JWT signing keys).
    ☐  Backup job succeeded in last 24h (PG + Cassandra snapshots).

================================================================================
§6  WHEN CHAT BREAKS — DIAGNOSIS & RECOVERY
================================================================================

── 6.1  DECISION TREE ──────────────────────────────────────────────

  START: Chat is broken. What exactly do users see?

  ┌──────────────────────────────────────────────────────────────┐
  │                                                              │
  │  "Messages aren't arriving" / "sent but not delivered"       │
  │      → §6.2  Delivery Failure                                │
  │                                                              │
  │  "Can't connect to chat at all" / WS connection refused      │
  │      → §6.3  Connection Failure                              │
  │                                                              │
  │  "Everyone shows offline" / presence wrong                   │
  │      → §6.4  Presence Failure                                │
  │                                                              │
  │  "Chat is slow" / messages take > 2s to appear               │
  │      → §6.5  Latency Degradation                             │
  │                                                              │
  │  "Seeing messages from blocked users"                        │
  │      → res5 RB-8 (Rebuild block-list projection)             │
  │                                                              │
  │  "Messages lost" / history missing                           │
  │      → §6.6  Cassandra Data Loss                             │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘

── 6.2  DELIVERY FAILURE — messages sent but not arriving ──────────

  The delivery path is:
    Client WS → Chat Pod A → Cassandra write → Redis route lookup
    → Redis Pub/Sub to Chat Pod B → Client WS

  Diagnosis (in order):

  Step 1 — Are messages reaching Cassandra?
      Check metric: chat_messages_persisted_total (should track
      chat_messages_received_total closely).

      If NOT persisting → Cassandra write failure. Go to §6.6.

  Step 2 — Is Redis route lookup working?
      $ kubectl exec -n chat chat-0 -- redis-cli -h chat-state \
          GET ws_route:test-user-id

      If connection refused / timeout → Redis is down.
      Impact: delivery is broken BUT messages are persisted.
      Clients will get them on reconnect/resync.
      Fix: restore Redis (replica promotion, or fresh instance —
      route keys repopulate as users reconnect, TTL ~30s anyway).

      If empty result → recipient isn't connected, OR pod crashed
      without cleaning up its route keys. Stale routes expire on
      next heartbeat miss (30s). Acceptable.

  Step 3 — Is inter-pod Pub/Sub working?
      $ kubectl exec -n chat chat-0 -- redis-cli -h chat-state \
          PUBLISH pod:chat-test "ping"

      If 0 subscribers → pods aren't subscribed to their own
      channel. Check pod logs for Redis reconnect loops.

      $ kubectl logs -n chat chat-0 | grep -i "pubsub\|subscribe"

      Fix: usually a pod restart clears it. Rolling restart the
      chat deployment:
      $ kubectl rollout restart deployment/chat -n chat

  Step 4 — Client-side issue?
      If server-side all looks healthy, the client's WS may be
      half-open (TCP connection alive but not receiving). Clients
      should detect this via missed server heartbeats and
      reconnect. Check client logs/reports.

── 6.3  CONNECTION FAILURE — can't connect to chat at all ──────────

  Diagnosis:

  Step 1 — Is the Chat deployment healthy?
      $ kubectl get pods -n chat
      # All should be Running, READY N/N.

      If pods crashing → check logs for cause. Common:
        • Cassandra unreachable at startup → fix Cassandra first.
        • OOMKilled → scale up memory OR reduce max sockets/pod.

  Step 2 — Is the Gateway routing WS upgrades correctly?
      $ curl -v -H "Upgrade: websocket" \
             -H "Connection: Upgrade" \
             -H "Sec-WebSocket-Key: x3JJHMbDL1EzLkh9GBhXDw==" \
             -H "Sec-WebSocket-Version: 13" \
             https://gateway/v1/chat/ws

      Look for 101 Switching Protocols. If 502/504 → gateway
      can't reach chat pods. Check Service and network policies:

      $ kubectl get svc chat -n chat
      $ kubectl get networkpolicy -n chat

  Step 3 — Auth failure?
      If clients see 401 on WS upgrade, the JWT is expired/invalid
      or Identity's JWKS is unreachable. Check gateway logs for
      the specific auth error. Clients should refresh their token.

  Immediate mitigation if Chat pods are completely down:
      The system already advertises a REST fallback path
      (POST /v1/chat/.../messages + long-poll GET). Confirm the
      gateway is routing those correctly — they hit Chat Service
      too, but don't require WS upgrade. If Chat Service ITSELF
      is down, there's no fallback — restore the service.

── 6.4  PRESENCE FAILURE — everyone shows offline ──────────────────

  Presence is Redis-only: SET presence:{userId} EX 30 on each
  heartbeat (every 25s from the client).

  Diagnosis:

  Step 1 — Are heartbeats arriving?
      Metric: chat_heartbeats_received_total — should be ~1,200/s
      at 12k concurrent. If near zero → clients aren't sending
      (client bug) or gateway is blocking the heartbeat frame.

  Step 2 — Are presence keys being written?
      $ kubectl exec -n chat chat-0 -- redis-cli -h chat-state \
          --scan --pattern 'presence:*' | wc -l

      Should be ~12,000. If zero → Redis writes failing. Check
      Redis health. If Redis is fine but keys missing → chat pod
      isn't writing them. Check logs.

  Step 3 — Are presence keys being READ correctly?
      The get-presence-for-conversation endpoint does an MGET
      on presence keys. If MGET returns null but keys exist
      (verify with redis-cli GET), there's a key construction
      bug — check for recent deploys.

  Mitigation: Presence is cosmetic. No data loss risk. Worst
  case, restart chat pods to clear any in-process cache issue.

── 6.5  LATENCY DEGRADATION — chat is slow ─────────────────────────

  Target: p50 10ms, p99 150ms for message delivery.

  If p99 > 500ms, diagnose by breaking down the span:

  ┌────────────────────────────┬──────────────┬────────────────────┐
  │ Span                       │ Healthy p99  │ If slow, check...  │
  ├────────────────────────────┼──────────────┼────────────────────┤
  │ Cassandra write            │ < 10ms       │ Compaction backlog │
  │                            │              │ (nodetool          │
  │                            │              │ compactionstats).  │
  │                            │              │ Disk IOPS. GC      │
  │                            │              │ pauses.            │
  ├────────────────────────────┼──────────────┼────────────────────┤
  │ Redis route lookup         │ < 1ms        │ Redis CPU. Network │
  │ (MGET ws_route:*)          │              │ between chat pod   │
  │                            │              │ and Redis.         │
  ├────────────────────────────┼──────────────┼────────────────────┤
  │ Pub/Sub delivery           │ < 5ms        │ Redis CPU.         │
  │ (PUBLISH pod:X)            │              │ Subscriber pod     │
  │                            │              │ event loop         │
  │                            │              │ blocked.           │
  ├────────────────────────────┼──────────────┼────────────────────┤
  │ WS frame send to client    │ < 5ms        │ Client network.    │
  │                            │              │ Not server-side.   │
  └────────────────────────────┴──────────────┴────────────────────┘

  Most common cause: Cassandra compaction falling behind under
  write pressure. Check:

      $ kubectl exec -n data-tier cassandra-0 -- \
          nodetool compactionstats

  If pending compactions > 10 → temporarily raise compaction
  throughput:

      $ nodetool setcompactionthroughput 64   # MB/s, default 16

  Reset to default after backlog clears (high throughput steals
  IOPS from user queries).

── 6.6  CASSANDRA DATA LOSS — messages gone ────────────────────────

  This should be rare (RF=3 + quorum writes). If it happens:

  Step 1 — Confirm it's real, not a query bug.
      Directly query Cassandra for the missing message range:
      $ cqlsh -e "SELECT * FROM chat.messages \
          WHERE conversation_id=X \
          AND message_id > minTimeUUID('2026-03-01') \
          LIMIT 100;"

      If messages ARE there → app query bug, not data loss.

  Step 2 — Check node health.
      $ nodetool status
      All nodes should be UN (Up/Normal). If a node is DN and
      the others are serving, RF=3 means you've lost one copy
      but have two. Recover the node or replace it.

  Step 3 — Restore from snapshot.
      Daily snapshots are on the persistent volume. To restore:
        1. Stop Chat Service writes (WRITES_ENABLED=false for
           chat, or scale chat pods to 0).
        2. On each Cassandra node, copy snapshot SSTables back
           into the live data directory.
        3. Run `nodetool refresh chat messages`.
        4. Run `nodetool repair` to reconcile across nodes.
        5. Re-enable writes.

      RPO is ~24h (snapshot cadence). Messages sent since the
      last snapshot ARE lost. Communicate to users.

  Step 4 — Post-mortem.
      Cassandra data loss with RF=3 and quorum indicates a
      serious misconfiguration or correlated failure. Root-cause
      before resuming normal operation.

================================================================================
§7  WHEN THE DATABASE BREAKS — DIAGNOSIS & RECOVERY
================================================================================

── 7.1  DECISION TREE ──────────────────────────────────────────────

  "Database" here means PostgreSQL (Feed, Community, Identity).
  Cassandra is covered in §6.6.

  ┌──────────────────────────────────────────────────────────────┐
  │                                                              │
  │  "Can't write" / 500 on POST / "connection refused"          │
  │      → §7.2  Primary Failure                                 │
  │                                                              │
  │  "Reads are slow" / GET p99 > 1s                             │
  │      → §7.3  Replica Overload                                │
  │                                                              │
  │  "Wrote X but read shows old value"                          │
  │      → §7.4  Replication Lag                                 │
  │                                                              │
  │  "Out of disk" / writes failing with disk-full               │
  │      → §7.5  Disk Exhaustion                                 │
  │                                                              │
  │  "DB is fine but feeds are empty"                            │
  │      → It's Redis, not PG. See §8.1.                         │
  │                                                              │
  │  "Specific table corrupted" / integrity error                │
  │      → §7.6  Point-in-Time Recovery                          │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘

── 7.2  PRIMARY FAILURE — writes are failing ───────────────────────

  User-visible: 500 errors on all POST/PUT/DELETE. Reads may still
  work (replicas are independent).

  Immediate triage:
    1. Confirm it's the primary (not just one service's bad config).
       If only one service is 500ing → likely a code/config bug in
       that service, not PG. Check that service's logs first.

    2. Check primary status:
       $ kubectl get pods -n data-tier -l app=postgres,role=primary
       $ kubectl exec -n data-tier postgres-primary-0 -- pg_isready

    3. Check connections:
       $ kubectl exec postgres-primary-0 -- \
           psql -c "SELECT count(*), state FROM pg_stat_activity \
                    GROUP BY state;"
       If all connections are "idle in transaction" → something is
       holding locks. Find the blocker:
       $ psql -c "SELECT * FROM pg_locks WHERE NOT granted;"
       Kill the blocker if it's a stuck migration or a bad query:
       $ psql -c "SELECT pg_terminate_backend(PID);"

  If primary is truly DOWN (pod crashed, node gone, disk dead):

    MANAGED POSTGRES (cloud provider):
      Failover is automatic. One replica promotes to primary.
      Typical time: 30–60 seconds. You do nothing but watch.

    SELF-MANAGED:
      Promote a replica manually:
        1. Pick the replica with the least lag (check
           pg_last_wal_replay_lsn on each).
        2. On the chosen replica: `pg_ctl promote`.
        3. Update the Kubernetes Service `postgres-primary` to
           point at the new pod.
        4. Other replicas need to re-follow the new primary.
           Update their primary_conninfo and restart.

  IMPORTANT — don't bring the OLD primary back online without
  rebuilding it. It has data the new primary didn't receive
  (if sync replication was off for any period) or it will try
  to run its own timeline. It must rejoin as a fresh replica.

  During the outage window:
    • Flip WRITES_ENABLED=false to give users a clean error
      message instead of timeouts (§9 Level 3).
    • Reads continue to work from remaining replicas.

── 7.3  REPLICA OVERLOAD — reads are slow ──────────────────────────

  Symptom: GET endpoints have high p99. Primary is fine. Replicas
  are CPU-pegged.

  Most common cause: a new query pattern that's doing a sequential
  scan instead of using an index.

  Diagnosis:
      $ kubectl exec postgres-replica-0 -- \
          psql -c "SELECT query, calls, total_exec_time, \
                   mean_exec_time FROM pg_stat_statements \
                   ORDER BY total_exec_time DESC LIMIT 10;"

      Look for queries with high mean_exec_time and high calls.
      Run EXPLAIN ANALYZE on the suspect query to see the plan.

  Fixes, in order of preference:
    1. Add the missing index (do this on replicas first, then
       primary — index creation on the primary replicates but
       causes write amplification during the build).
    2. If the query is from a recent deploy → rollback and fix.
    3. Shed read load: flip TIMELINE_PG_FALLBACK=false (§9
       Level 2) so timeline reads don't hit PG at all. Buys
       time while you add the index.
    4. Add a third replica (slow, ~10 min to spin up and sync).

── 7.4  REPLICATION LAG — reads show stale data ────────────────────

  Symptom: User posts, then their feed doesn't show it. Or: user
  changes profile, old name still appears.

  Diagnosis:
      $ kubectl exec postgres-replica-0 -- \
          psql -c "SELECT now() - pg_last_xact_replay_timestamp() \
                   AS lag;"

      Healthy: < 500ms. Problematic: > 2s.

  Causes:
    • Long-running transaction on primary holding WAL (find it:
      SELECT * FROM pg_stat_activity WHERE state='active' AND
      now() - xact_start > interval '10s';).
    • Replica disk IO saturated (check disk metrics).
    • Huge write spike on primary (migrations, bulk imports).
    • Network between primary and replica constrained.

  Fixes:
    • Kill the long transaction on primary if it's a runaway.
    • For huge migrations: batch them with sleeps (§3.4).
    • For persistent lag: check replica disk IOPS limits.
      Replicas need enough IO to replay WAL as fast as primary
      generates it.

  User-visible mitigation:
    The "read your own write" pattern in the app already routes
    a user's reads to PRIMARY for 5 seconds after they write.
    If lag exceeds 5s, they'll see stale data. Extend the window
    temporarily:
      $ kubectl patch configmap feed-config -n feed \
          --patch '{"data":{"RYOW_WINDOW_SECONDS":"15"}}'

── 7.5  DISK EXHAUSTION — out of space ─────────────────────────────

  PG will fail writes when disk is full. Prevent this with an
  alert at 80% usage; if you got here anyway:

  Immediate:
    1. Extend the volume (cloud: usually online operation).
       $ kubectl patch pvc postgres-primary-data -n data-tier \
           --patch '{"spec":{"resources":{"requests":
                     {"storage":"200Gi"}}}}'
       Wait for the cloud provider to resize. Run pg_resize or
       resize2fs if required by the filesystem.

    2. If extending isn't instant, reclaim space:
       • Archive old WAL if archiver is behind.
       • VACUUM FULL on a large table you can briefly lock
         (reclaims space immediately but locks the table).
       • Delete old pg_log files if they're on the same volume.

  Preventive:
    • Autovacuum should be reclaiming space. Check it's running:
      SELECT relname, last_autovacuum FROM pg_stat_user_tables;
    • If a table is growing faster than vacuum can keep up, it
      likely has long-running transactions holding old tuple
      versions. Find and fix those transactions.

── 7.6  POINT-IN-TIME RECOVERY — undo a bad write ──────────────────

  Someone ran a bad UPDATE/DELETE, or a bug corrupted a table.
  PITR lets you restore to any second within the WAL retention
  window.

  ⚠ This is disruptive. You're effectively restoring a backup to
  a specific timestamp. Any writes AFTER that timestamp are lost.
  Only do this if the corruption is worse than losing recent data.

  Procedure (managed PG):
    1. Identify the timestamp BEFORE the bad write. Use app logs
       (correlationId of the bad request) or PG's own
       current_timestamp in audit columns.
    2. Use the cloud console's "Restore to point in time" feature.
       This creates a NEW instance at that timestamp.
    3. Verify the data on the new instance.
    4. Cut over: update the Kubernetes Secret with the new
       instance's connection string. Restart services.

  Less disruptive option — for a single corrupted table:
    1. Restore PITR to a SEPARATE scratch instance.
    2. Export just the affected table from scratch:
       $ pg_dump -t affected_table -f /tmp/table.sql scratch_db
    3. On PRODUCTION, truncate and reload that one table in a
       transaction. Verify before committing.
    4. Delete scratch instance.

================================================================================
§8  WHEN KAFKA / REDIS / SEARCH BREAKS — QUICK REFERENCE
================================================================================

── 8.1  REDIS FAILURE ──────────────────────────────────────────────

  Redis holds DERIVED state (timelines, presence, routing, caches).
  All of it is rebuildable. Redis failure is DEGRADATION, not data
  loss.

  ┌─────────────────────────┬────────────────────────────────────┐
  │ Instance                │ Impact when down                   │
  ├─────────────────────────┼────────────────────────────────────┤
  │ feed-cache (timelines)  │ Timeline reads fall back to PG     │
  │                         │ pull-query (slower, ~500ms p99     │
  │                         │ instead of ~5ms). Fan-out writes   │
  │                         │ fail but backlog buffers in Kafka. │
  │                         │ When Redis returns: run res5 RB-6  │
  │                         │ to rebuild timelines (~10 min).    │
  ├─────────────────────────┼────────────────────────────────────┤
  │ chat-state (routing,    │ Real-time delivery stops. Messages │
  │ presence, dedup)        │ still persisted to Cassandra.      │
  │                         │ Clients fall back to REST+poll     │
  │                         │ mode (res7 §2.5). Presence shows   │
  │                         │ everyone offline. When Redis       │
  │                         │ returns: self-heals as clients     │
  │                         │ reconnect (route/presence keys     │
  │                         │ repopulate on heartbeat). No       │
  │                         │ manual rebuild needed.             │
  └─────────────────────────┴────────────────────────────────────┘

  Recovery:
    • Replica promotion: automatic in managed Redis, ~10s.
    • If both primary and replica die (AZ failure): spin up a
      fresh instance. It starts empty. For feed-cache, run RB-6.
      For chat-state, nothing — it repopulates.
    • AOF recovery: if you have the AOF file from the dead node,
      start Redis with it. Data as of last fsync (everysec → lose
      up to 1 second of writes).

── 8.2  KAFKA FAILURE ──────────────────────────────────────────────

  With RF=3 and min.insync.replicas=2, Kafka tolerates one broker
  failure transparently. Producers using acks=all keep working.

  ┌─────────────────────────┬────────────────────────────────────┐
  │ Scenario                │ Impact                             │
  ├─────────────────────────┼────────────────────────────────────┤
  │ 1 broker down           │ None. Writes continue. Consumers   │
  │                         │ rebalance. Replace broker at       │
  │                         │ leisure.                           │
  ├─────────────────────────┼────────────────────────────────────┤
  │ 2 brokers down          │ Writes FAIL (min.insync=2 not      │
  │                         │ met). Outbox tables accumulate     │
  │                         │ unpublished rows — that's BY       │
  │                         │ DESIGN (durable buffer). Consumers │
  │                         │ can still read existing messages   │
  │                         │ from the one surviving broker.     │
  │                         │ Restore a broker → writes resume,  │
  │                         │ outbox relay drains the backlog.   │
  ├─────────────────────────┼────────────────────────────────────┤
  │ All 3 brokers down      │ All async processing stops. Feed   │
  │                         │ fan-out, notifications, search     │
  │                         │ indexing all paused. Outbox        │
  │                         │ buffers up to its capacity (alert  │
  │                         │ on > 5k rows). Restore brokers →   │
  │                         │ everything drains.                 │
  └─────────────────────────┴────────────────────────────────────┘

  Recovery:
    • Broker replacement: bring up new broker with same broker.id
      (if disks intact) or a new id + reassign partitions.
    • Watch under-replicated partitions after recovery:
      $ kafka-topics.sh --describe --under-replicated-partitions
      Should empty out as re-replication completes.
    • Consumer groups resume from committed offsets — no replay
      needed, no duplicates (consumers are idempotent per res4).

── 8.3  ELASTICSEARCH FAILURE ──────────────────────────────────────

  Search is a soft dependency. If ES is down:
    • Search endpoints return 503. Everything else works.
    • Search Indexer (Kafka consumer) can't write. Lag builds up
      in its consumer group. That's fine — it'll catch up.

  Recovery:
    • If cluster recovers with data intact → indexer catches up
      automatically. No action.
    • If data lost → run res5 RB-5 (full reindex from Kafka).
      Takes ~30 min with 30-day event retention.

── 8.4  DEAD-LETTER TOPIC ALERTS ───────────────────────────────────

  When a consumer can't process an event after N retries, it ships
  to a DLT: {consumer-group}.dlt. Alert fires on ANY message in a
  DLT.

  Procedure: res5 RB-10. Summary:
    1. Read the message. Understand why it failed (bad schema?
       missing FK? transient downstream?).
    2. Fix the root cause (deploy, data patch, whatever).
    3. Replay the DLT back to the original topic using a temporary
       consumer group.
    4. Watch for the message to re-enter DLT (if so, your fix
       didn't work — loop back to step 1).
    5. Delete the message from DLT once successfully processed.

================================================================================
§9  EMERGENCY DEGRADATION LADDER — KILL SWITCHES
================================================================================

  When the system is under duress and you need to shed load RIGHT
  NOW, use these switches in order of increasing aggressiveness.
  All are runtime-toggleable ConfigMap values — no redeploy.

── LEVEL 1 — SHED FAN-OUT ──────────────────────────────────────────

  Use when: Fan-out workers overloaded, Redis under write pressure,
            or Kafka consumer lag climbing despite max pods.

  Flip:  FANOUT_ENABLED = false

      $ kubectl patch configmap feed-config -n feed \
          --patch '{"data":{"FANOUT_ENABLED":"false"}}'

  Effect:
    • CreatePost still writes to PG + outbox. Events still
      published to Kafka. But the fan-out consumer pauses.
    • No more Redis timeline writes.
    • Timeline reads still work — celebrity posts via pull path
      (immediate), non-celebrity posts via PG fallback (slower).
    • User-visible: feeds feel slower/staler but functional.

  Recovery:
    • Flip back to true. Consumer resumes from committed offset.
    • Backlog drains. Timelines catch up over a few minutes.

── LEVEL 2 — SHED PG READ LOAD ─────────────────────────────────────

  Use when: PG read replicas CPU-pegged and you need relief.

  Flip:  TIMELINE_PG_FALLBACK = false

      $ kubectl patch configmap feed-config -n feed \
          --patch '{"data":{"TIMELINE_PG_FALLBACK":"false"}}'

  Effect:
    • Timeline reads serve ONLY from Redis. No PG merge, no
      fallback query.
    • Zero timeline read load on PG replicas.
    • User-visible: users with empty Redis timelines (new
      signups, post-Redis-flush) see empty feeds. Everyone
      else sees a slightly stale feed (missing celebrity
      posts that rely on pull-merge).

  Recovery: flip back once replicas recover.

── LEVEL 3 — READ-ONLY MODE ────────────────────────────────────────

  Use when: PG primary is the bottleneck. Or: you're doing a
            risky maintenance op and want a safety net.

  Flip:  WRITES_ENABLED = false

      $ kubectl patch configmap feed-config -n feed \
          --patch '{"data":{"WRITES_ENABLED":"false"}}'
      # Repeat for community-config if needed.

  Effect:
    • All POST/PUT/DELETE return 503 with Retry-After header.
    • Clients show "posting temporarily unavailable" UI.
    • Reads continue to work fully.

  Recovery: flip back. Clients retry automatically.

── LEVEL 4 — FULL MAINTENANCE MODE ─────────────────────────────────

  Use when: Everything is on fire. You need to buy time.

  Gateway returns 503 for all routes (or specific route prefixes):

      $ kubectl patch configmap gateway-config -n gateway \
          --patch '{"data":{"MAINTENANCE_MODE":"true"}}'

  Effect: Clients get a maintenance page. You have space to work.

── DEGRADATION QUICK REFERENCE ─────────────────────────────────────

  ┌─────┬───────────────────┬────────────────────┬────────────────┐
  │ Lvl │ Switch            │ What it sheds      │ User sees      │
  ├─────┼───────────────────┼────────────────────┼────────────────┤
  │  1  │ FANOUT_ENABLED    │ Redis writes,      │ Slightly stale │
  │     │     = false       │ fan-out worker CPU │ feeds          │
  │  2  │ TIMELINE_PG_      │ PG replica read    │ Some empty/    │
  │     │ FALLBACK = false  │ load               │ stale feeds    │
  │  3  │ WRITES_ENABLED    │ PG primary write   │ Can't post,    │
  │     │     = false       │ load               │ can read       │
  │  4  │ MAINTENANCE_MODE  │ Everything         │ Maintenance    │
  │     │     = true        │                    │ page           │
  └─────┴───────────────────┴────────────────────┴────────────────┘

  Rule: engage the LOWEST level that solves your problem. Escalate
  only if it's not enough. De-escalate in reverse order.

================================================================================
§10  WHOLE-PLAN SUMMARY — THE OPERATING MODEL ON ONE PAGE
================================================================================

── 10.1  THE PHILOSOPHY ────────────────────────────────────────────

  This system is built around three operating principles:

  1. DERIVED STATE IS DISPOSABLE.
     PostgreSQL and Cassandra hold the truth. Redis, Elasticsearch,
     and Kafka consumer projections are all rebuildable from
     primary stores or from Kafka's retained event log. When
     derived state breaks, don't panic — rebuild it (res5).

  2. DEGRADE, DON'T DIE.
     Every cross-component dependency has a fallback. Redis down?
     PG pull-query. Chat routing down? REST+poll. Search down?
     Hide the search box. The system gets WORSE when things break,
     but it doesn't go DOWN. The degradation ladder (§9) gives you
     manual control over the same trade-offs.

  3. ASYNC EVERYTHING THAT CAN BE ASYNC.
     The only synchronous cross-service calls are auth checks
     (gRPC, 200ms timeout, circuit-breakered). Everything else
     flows through Kafka with durable outbox buffers. A slow
     consumer doesn't block writes — it just falls behind, and
     its lag metric pages you.

── 10.2  THE DAILY RHYTHM ──────────────────────────────────────────

  Normal operation:
    • HPA scales pods up/down with traffic. You watch, don't act.
    • Run the daily checklist (§5.4) once per on-call shift.
    • Deploy during business hours via rolling update (§3.1).
    • Database migrations batched + scheduled off-peak (§3.4).

  Weekly:
    • Review alert noise. Tune thresholds if >5 false pages/week.
    • Check headroom: if any resource consistently > 60%, plan
      the next scaling step before it becomes urgent (§4).

  Quarterly:
    • Run a game day: kill a broker, kill a Redis primary, fail
      over PG. Verify the runbooks still work and new team
      members know them.
    • Rotate signing keys (§3.3).

── 10.3  THE INCIDENT FLOW ─────────────────────────────────────────

  When paged:

    1. ACKNOWLEDGE the page. Tell #platform-ops you're on it.

    2. ORIENT. Open the dashboard for the paging service. Check
       the four golden signals (§5.1). Is it this service, or is
       it a dependency that failed? Follow the chain down.

    3. TRIAGE. Use the decision trees:
         Chat broken?       → §6.1
         Database broken?   → §7.1
         Feeds broken?      → Check Redis (§8.1) then Kafka (§8.2)
         Search broken?     → §8.3
         Events stuck?      → res5 RB-0 decision tree

    4. STABILIZE. If user impact is severe, engage the
       degradation ladder (§9) to stop the bleeding while you
       diagnose.

    5. FIX. Work the specific runbook. Rollback a deploy if it
       correlates. Restart pods if state is corrupt. Replace
       infrastructure if hardware failed.

    6. RECOVER. De-escalate the degradation ladder. Rebuild any
       derived state that was lost (res5). Verify end-to-end
       with smoke tests.

    7. DOCUMENT. Post-mortem within 48 hours. Update this guide
       if a runbook was wrong or missing.

── 10.4  THE COMPONENT SCORECARD ───────────────────────────────────

┌──────────────┬──────────────────┬─────────────┬───────────────────┐
│ Component    │ Scales via       │ Failure     │ Recovery path     │
│              │                  │ blast radius│                   │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ API Gateway  │ HPA (CPU/p95)    │ Total outage│ Rollout restart   │
│              │ 3–10 pods        │ (entrypoint)│                   │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Identity     │ HPA (refresh/s)  │ No new      │ Rollout restart;  │
│              │ 3–10 pods        │ logins;     │ existing tokens   │
│              │                  │ existing    │ valid for 10 min  │
│              │                  │ sessions OK │                   │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Feed Service │ HPA (CPU/p95)    │ Feed        │ Rollout restart   │
│              │ 3–20 pods        │ read/write  │                   │
│              │                  │ down; chat  │                   │
│              │                  │ still works │                   │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Chat Service │ HPA (WS count)   │ Chat down;  │ Rollout restart;  │
│              │ 3–30 pods        │ feed still  │ clients resync    │
│              │                  │ works       │ from Cassandra    │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Community    │ HPA (CPU)        │ Community   │ Rollout restart;  │
│              │ 2–10 pods        │ features    │ Feed continues    │
│              │                  │ degrade     │ with cached       │
│              │                  │             │ membership        │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Fan-out Wkr  │ HPA (Kafka lag)  │ Feeds go    │ Kafka buffers;    │
│              │ 2–20 pods        │ stale       │ drain on recovery │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Notification │ HPA (Kafka lag)  │ Notifs      │ Kafka buffers;    │
│              │ 2–8 pods         │ delayed     │ drain on recovery │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Search Idx   │ HPA (Kafka lag)  │ Search      │ Kafka buffers;    │
│              │ 2–6 pods         │ stale       │ drain on recovery │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ PostgreSQL   │ Read replicas +  │ Writes fail │ Promote replica   │
│              │ vertical         │ (hard dep)  │ (auto if managed);│
│              │                  │             │ PITR for          │
│              │                  │             │ corruption        │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Cassandra    │ Add nodes        │ Chat writes │ RF=3 tolerates    │
│              │ (linear)         │ fail        │ 1 node; snapshot  │
│              │                  │             │ restore for worse │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Redis        │ Bigger node →    │ Degrade to  │ Replica promote;  │
│              │ Cluster mode     │ PG fallback │ rebuild (RB-6);   │
│              │                  │ (feed) or   │ chat-state self-  │
│              │                  │ REST mode   │ heals             │
│              │                  │ (chat)      │                   │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Kafka        │ More partitions  │ Async       │ RF=3 tolerates    │
│              │ → more brokers   │ pipelines   │ 1 broker; outbox  │
│              │                  │ pause;      │ buffers writes    │
│              │                  │ writes OK   │                   │
│              │                  │ (outbox)    │                   │
├──────────────┼──────────────────┼─────────────┼───────────────────┤
│ Elasticsearch│ More shards →    │ Search only │ Full reindex from │
│              │ more nodes       │             │ Kafka (RB-5)      │
└──────────────┴──────────────────┴─────────────┴───────────────────┘

── 10.5  THE ESCALATION CHEAT SHEET ────────────────────────────────

  Pin this to the wall. When things are burning:

  ┌──────────────────────────────────────────────────────────────┐
  │                                                              │
  │  IS IT A DEPLOY?                                             │
  │    → Check: was something deployed in the last 30 min?       │
  │    → Rollback first, diagnose second.                        │
  │      $ helm rollback {service}                               │
  │                                                              │
  │  IS IT A DEPENDENCY?                                         │
  │    → Follow the error down the chain. Services log which     │
  │      downstream call failed. Fix the dependency, not the     │
  │      service.                                                │
  │                                                              │
  │  IS IT LOAD?                                                 │
  │    → Check HPA status. At max replicas? Raise the max.       │
  │    → Still not enough? Engage degradation ladder (§9).       │
  │                                                              │
  │  IS IT DATA?                                                 │
  │    → Derived data corrupted? Rebuild (res5 runbooks).        │
  │    → Primary data corrupted? PITR (§7.6). Call for help.     │
  │                                                              │
  │  STILL ON FIRE?                                              │
  │    → Level 4 maintenance mode. Page the team. Breathe.       │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘

────────────────────────────────────────────────────────────────────
END OF DOCUMENT
────────────────────────────────────────────────────────────────────
