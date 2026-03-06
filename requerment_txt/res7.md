════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — CHAT SERVICE INTERNALS
Multi-server message delivery, Redis-backed connection fabric, presence,
and flaky-network resilience
════════════════════════════════════════════════════════════════════════════════

Builds on:  res1 §3.2/§5.2 (Chat bounded context, Cassandra + Redis storage)
            res3 §6.2 (Chat REST + WebSocket contracts)
            res3 §4  (capacity: 12k concurrent WS, 500 msg/s, 1,200 heartbeat/s)
            res4 §7  (outbox for message.events)

Questions answered:
  §1  How do messages stay fast when we run many chat servers?
  §2  How does Redis keep everyone connected across servers?
  §3  How do we show who is online without touching the database?
  §4  What happens when the internet is bad and a message fails?

================================================================================
§1  HOW MESSAGES STAY FAST ACROSS MANY SERVERS
================================================================================

── 1.1  THE CORE PROBLEM ───────────────────────────────────────────

  Chat is not like Feed. Feed Service is STATELESS — any replica can
  handle any request because all state lives in Postgres/Redis. Chat
  Service holds open WEBSOCKET connections, which are stateful by
  nature: a WebSocket is a long-lived TCP pipe tied to ONE specific
  server process.

                    ┌────────────────────────────────┐
                    │                                │
    Abebe ═════════►│   Chat Pod #1                  │
                    │   (holds Abebe's WebSocket)    │
                    │                                │
                    └────────────────────────────────┘

                    ┌────────────────────────────────┐
                    │                                │
    Hana  ═════════►│   Chat Pod #3                  │
                    │   (holds Hana's WebSocket)     │
                    │                                │
                    └────────────────────────────────┘

  When Abebe sends a message to Hana, Pod #1 receives it. But Hana's
  WebSocket is on Pod #3. Pod #1 CANNOT push bytes down Hana's
  socket — only Pod #3 can.

  This is the CROSS-POD ROUTING PROBLEM. Every horizontally-scaled
  WebSocket system has it. There are three ways to solve it.

── 1.2  THREE ROUTING STRATEGIES (we use #3) ───────────────────────

  STRATEGY A — Sticky routing (rejected)

    Force all members of a conversation onto the SAME pod using
    consistent hashing on conversation_id.

    Problem: A user is in many conversations. Conversation A hashes
    to Pod #1, conversation B hashes to Pod #5. The user can only
    hold one WebSocket. We'd need one WS per conversation → wasteful
    and complex. Also: rebalancing on pod add/remove means mass
    reconnects.

  STRATEGY B — Broadcast to all pods (rejected)

    Every pod subscribes to a single Redis Pub/Sub channel. When
    any pod receives a message, it publishes to that channel. Every
    pod receives every message and checks "do I hold a socket for
    any recipient?" — if yes, deliver; if no, drop.

    Problem: At 500 msg/s and 30 pods, every pod processes 500 msg/s
    but delivers maybe 17 of them. 97% wasted work. Scales linearly
    with pod count (bad direction). Works fine at small scale,
    degrades as we grow.

  STRATEGY C — Directed routing via lookup table (CHOSEN)

    Maintain a Redis hash that maps {user_id → pod_id}. When a pod
    needs to deliver to a user, it looks up which pod holds that
    user's socket and sends the message ONLY to that pod via a
    pod-specific Redis Pub/Sub channel.

    Every pod does O(recipients) work per message, not O(all users).
    Scales flat regardless of pod count.

── 1.3  THE ROUTING TABLE — ws_route:{userId} ─────────────────────

  Redis key layout (res1 §5.2):

    ws_route:{userId}  →  {pod_id}     TTL: 45s, refreshed every 25s

  Lifecycle:

    ON CONNECT (user opens WebSocket to Pod #3):
      SET ws_route:{userId} "chat-pod-3" EX 45
      SUBSCRIBE pod:chat-pod-3          ← pod's inbox channel

    ON HEARTBEAT (every 25s, client sends {"t":"ping"}):
      EXPIRE ws_route:{userId} 45       ← refresh TTL
      (pod replies {"t":"pong"})

    ON DISCONNECT (socket closes cleanly):
      DEL ws_route:{userId}

    ON CRASH (pod dies, no clean disconnect):
      ws_route:{userId} expires after ≤ 45s.
      Next heartbeat from a reconnected client on a new pod
      overwrites the route.

  Why 45s TTL with 25s heartbeat:
    • Gives ~20s grace for a missed heartbeat (network hiccup,
      GC pause) before the route is considered stale.
    • Short enough that a crashed pod's stale routes don't linger.
    • Aligns with res3 §6.2 ping interval (25s).

── 1.4  END-TO-END MESSAGE FLOW ───────────────────────────────────

  Abebe (on Pod #1) sends to Hana (on Pod #3) in conversation C:

    ┌────────────────────────────────────────────────────────────────┐
    │                                                                │
    │  t=0ms    Abebe's client sends WS frame:                       │
    │             {"t":"msg","conv_id":"C",                          │
    │              "body":"hey","client_msg_id":"uuid-1"}            │
    │                                                                │
    │  t=1ms    Pod #1 receives frame. SendMessage use case:         │
    │             1. Validate: is Abebe a member of conv C?          │
    │                (L1 cache hit — membership loaded on WS         │
    │                 connect, refreshed via community.events)       │
    │             2. Validate: is Abebe blocked by any recipient?    │
    │                (L1 cache hit — block-list via user.events)     │
    │             3. Validate: client_msg_id not seen before?        │
    │                (Redis SET NX dedup:{client_msg_id} EX 300)     │
    │                                                                │
    │  t=3ms    Pod #1 writes to Cassandra:                          │
    │             INSERT INTO messages_by_conversation               │
    │               (conversation_id, message_id, sender_id,         │
    │                body, sent_at)                                  │
    │             VALUES ('C', now_uuid(), 'abebe', 'hey', NOW());   │
    │             (consistency = QUORUM → 2 of 3 nodes ACK)          │
    │                                                                │
    │           Pod #1 writes to outbox_chat (for message.events     │
    │           → Notification Service, async, see res4 §7.4).       │
    │                                                                │
    │  t=8ms    Cassandra ACKs. Message is durable.                  │
    │                                                                │
    │  t=8ms    Pod #1 sends ACK to Abebe:                           │
    │             {"t":"ack","client_msg_id":"uuid-1",               │
    │              "server_id":"msg-xyz","sent_at":"..."}            │
    │           Abebe's client marks the message as "sent" (single   │
    │           checkmark). ← USER-PERCEIVED LATENCY: ~8ms.          │
    │                                                                │
    │  t=8ms    Pod #1 looks up recipients:                          │
    │             MGET ws_route:hana ws_route:dawit ws_route:...     │
    │             (one Redis round-trip for all conv members)        │
    │             → {"hana": "chat-pod-3", "dawit": null, ...}       │
    │                                                                │
    │  t=9ms    Pod #1 groups recipients by pod and publishes:       │
    │             PUBLISH pod:chat-pod-3                             │
    │               {"type":"deliver","conv_id":"C",                 │
    │                "message":{...},"recipients":["hana"]}          │
    │           (One PUBLISH per destination pod, not per user.      │
    │            If 5 recipients are on pod-3, one PUBLISH with      │
    │            all 5 user_ids.)                                    │
    │                                                                │
    │           For dawit (ws_route = null → offline): SKIP the      │
    │           real-time path. Notification Service will push       │
    │           FCM later via message.events.                        │
    │                                                                │
    │  t=10ms   Pod #3 receives Pub/Sub message on pod:chat-pod-3.   │
    │           For each recipient in the payload:                   │
    │             IF we hold an active socket for that user          │
    │             AND they're subscribed to conv_id "C"              │
    │             THEN push WS frame:                                │
    │               {"t":"msg","conv_id":"C","message":{...}}        │
    │                                                                │
    │  t=12ms   Hana's client receives the frame. Renders message.   │
    │           ← HANA'S PERCEIVED LATENCY: ~12ms from Abebe's send. │
    │                                                                │
    └────────────────────────────────────────────────────────────────┘

  Why this is fast:

    • Only ONE Cassandra write in the hot path (durability).
    • Only TWO Redis round-trips total (dedup check + MGET routes).
    • Pub/Sub is O(1) network hops — Pod #1 → Redis → Pod #3.
      No broadcast storm.
    • Membership and block-list checks hit L1 (in-process) cache
      — zero network in the common case.
    • Outbox write (for Notification) happens, but the outbox RELAY
      is a separate process — Abebe and Hana never wait for it.

── 1.5  WHAT IF THE ROUTE IS STALE? ────────────────────────────────

  Scenario: Pod #3 crashed 10 seconds ago. Hana's ws_route still
  points to "chat-pod-3" (hasn't TTL'd out yet). Pod #1 publishes
  to pod:chat-pod-3 — but nobody is listening (pod is dead).

  Result: Redis Pub/Sub delivery is fire-and-forget. The message
  goes into the void. Hana never receives it via real-time.

  THIS IS FINE. Here's why:

    1. The message is already durable in Cassandra. It is NOT lost.

    2. Hana's client detects the disconnect (TCP RST or missed
       pong). It reconnects (to a new pod, say Pod #7). On
       reconnect, the client sends:
         {"t":"sub","conv_id":"C","since_msg_id":"<last-seen>"}
       Pod #7 queries Cassandra for messages in C after
       <last-seen> and pushes them down the socket. Hana catches
       up. This is the RESYNC mechanism — see §4.3.

    3. If Hana stays offline, the Notification Service (consuming
       message.events from Kafka) sends an FCM push. She gets a
       phone notification.

  The real-time path is an OPTIMIZATION, not the source of truth.
  Cassandra is the source of truth. A dropped Pub/Sub message costs
  ~2 seconds of delay (reconnect + resync), not data loss.

── 1.6  POD STARTUP AND SHUTDOWN ──────────────────────────────────

  ON POD START:
    1. Generate pod_id (stable: use K8s pod name, e.g.,
       "chat-pod-7d4f9c-xk2p").
    2. SUBSCRIBE pod:{pod_id} on Redis.
    3. Start accepting WebSocket upgrades.

  ON POD GRACEFUL SHUTDOWN (SIGTERM during rolling deploy):
    1. Stop accepting NEW WebSocket connections (readiness probe
       goes false; K8s stops routing to this pod).
    2. For every held socket, send:
         {"t":"error","code":"server_restart",
          "message":"Reconnecting...","retry_after_ms":2000}
       Then close the socket with WS close code 1012 (Service
       Restart).
    3. For every user this pod held:
         DEL ws_route:{userId}
       (So other pods don't try to route to us while we drain.)
    4. UNSUBSCRIBE pod:{pod_id}.
    5. Exit.

    Clients receiving 1012 reconnect after retry_after_ms + jitter
    (see §4.4). They land on a surviving pod. Resync (§4.3) fills
    any gap.

  K8s PodDisruptionBudget (res3 §10 R7): maxUnavailable=1 ensures
  only one chat pod drains at a time during a rolling deploy. A
  12k-user reconnect spread across the remaining pods is easily
  absorbed (each pod's share: ~12k / 29 pods ≈ 400 reconnects,
  handled in < 5s).

── 1.7  SCALING KNOBS ─────────────────────────────────────────────

  ┌──────────────────────────┬──────────────────────────────────────┐
  │ Bottleneck               │ Fix                                  │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ Too many concurrent WS   │ Add chat pods. Each pod handles ~2k  │
  │ (file descriptor / RAM   │ sockets comfortably (tune ulimit).   │
  │  pressure per pod)       │ 12k users / 2k per pod = 6 pods      │
  │                          │ minimum. HPA on connection count.    │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ Redis Pub/Sub saturated  │ Unlikely at our scale (500 msg/s ×   │
  │                          │ ~3 recipients avg = 1,500 PUBLISH/s, │
  │                          │ trivial). If it happens: Redis       │
  │                          │ Cluster with sharded channels        │
  │                          │ (pod:{id} naturally shards).         │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ Cassandra write latency  │ Add Cassandra nodes. Writes at       │
  │                          │ QUORUM scale linearly. partition_key │
  │                          │ = conversation_id spreads load.      │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ Route lookup latency     │ Already O(1) with MGET. If Redis RTT │
  │ (MGET ws_route)          │ is the problem, co-locate chat pods  │
  │                          │ and Redis in the same AZ. Or: cache  │
  │                          │ routes in L1 with 5s TTL (trade      │
  │                          │ staleness for latency).              │
  └──────────────────────────┴──────────────────────────────────────┘

================================================================================
§2  HOW REDIS KEEPS EVERYONE CONNECTED
================================================================================

Redis is NOT holding the WebSocket connections — the chat pods are.
Redis holds the METADATA that lets pods find each other and
coordinate. Four distinct Redis roles:

── 2.1  ROLE 1: THE ROUTING TABLE (covered in §1.3) ───────────────

  ws_route:{userId} → pod_id      TTL 45s, heartbeat-refreshed

  This is the phonebook. Any pod can ask "where is user X?" and get
  an answer in one Redis GET (~0.5 ms).

── 2.2  ROLE 2: THE INTER-POD MESSAGE BUS ─────────────────────────

  Redis Pub/Sub channel:  pod:{pod_id}

  Each pod subscribes to its own channel. Other pods PUBLISH
  delivery commands to it. Pub/Sub is fire-and-forget (no
  persistence, no replay) — perfect for real-time delivery where
  the durable copy is already in Cassandra.

  Why Pub/Sub and not a Redis LIST or STREAM:
    • Pub/Sub latency is sub-millisecond. LIST (BRPOP) and STREAM
      (XREAD) add polling overhead.
    • We don't NEED durability here. A missed message is recovered
      by resync (§4.3). Adding Stream persistence is cost without
      benefit.
    • Pub/Sub fanout is O(subscribers) at Redis, but each channel
      has exactly ONE subscriber (the target pod). No fanout cost.

  Channel naming with pod_id (not user_id) means:
    • Constant number of channels (= number of pods, ~30).
    • One SUBSCRIBE per pod, not per user (would be 12k SUBSCRIBEs).
    • The delivering pod batches recipients per target pod, so
      5 users on the same pod = one PUBLISH, not five.

── 2.3  ROLE 3: DEDUPLICATION STORE ───────────────────────────────

  dedup:{client_msg_id} → "1"      TTL 300s (5 min)

  Clients include a client_msg_id (UUID) with every message (res3
  §6.2). Before processing, the pod does:

    SET dedup:{client_msg_id} "1" NX EX 300

  Return value:
    "OK"  → new message, proceed.
    nil   → duplicate (client retried), skip processing, re-send
            the original ACK.

  This is the IDEMPOTENCY gate. It makes client retries (§4) safe.

  Why 5-minute TTL:
    • Long enough to outlast any realistic retry window
      (clients give up after ~30s of retries).
    • Short enough that Redis memory stays bounded
      (500 msg/s × 300s × ~50 B/key ≈ 7.5 MB — nothing).

── 2.4  ROLE 4: SUBSCRIPTION STATE (IN-MEMORY, NOT REDIS) ─────────

  Which conversations is a connected user subscribed to?

    We keep this IN THE POD'S MEMORY, not in Redis.

      pod_local: socket_id → { user_id, subscribed_conv_ids: Set }

  Why not Redis:
    • Subscriptions are ephemeral to a single socket. When the
      socket closes, they're gone. No need for durability.
    • Every inbound message checks "is this user subscribed to
      conv C?" — doing that in Redis would add a round-trip per
      delivery. In-memory is nanoseconds.
    • If the pod crashes, the socket is gone anyway. Subscription
      state is meaningless without the socket.

  On reconnect, the client re-sends {"t":"sub",...} for each open
  conversation. Pod rebuilds in-memory state. No Redis involved.

── 2.5  REDIS FAILURE HANDLING ────────────────────────────────────

  ┌─────────────────────────────┬──────────────────────────────────┐
  │ Failure                     │ Impact & Recovery                │
  ├─────────────────────────────┼──────────────────────────────────┤
  │ Redis primary dies.         │ Replica promotes (~10s).         │
  │                             │ During failover:                 │
  │                             │  • Route lookups fail → new msgs │
  │                             │    can't be delivered real-time. │
  │                             │    They ARE persisted (Cassandra │
  │                             │    write happens first). Clients │
  │                             │    resync on next reconnect.     │
  │                             │  • Dedup checks fail → pod       │
  │                             │    rejects new messages with     │
  │                             │    retriable error. Clients      │
  │                             │    retry after failover.         │
  │                             │  • Pub/Sub subscription lost →   │
  │                             │    pods detect (Redis client     │
  │                             │    emits disconnect event) and   │
  │                             │    auto-resubscribe on replica   │
  │                             │    promotion.                    │
  │                             │ Net impact: ~10s of delayed      │
  │                             │ delivery. No data loss.          │
  ├─────────────────────────────┼──────────────────────────────────┤
  │ Redis totally unreachable   │ Chat degrades to REST-only mode: │
  │ (network partition)         │  • WS sends return                │
  │                             │    {"t":"error","code":"degraded"│
  │                             │     "retry_via":"rest"}          │
  │                             │  • Client falls back to          │
  │                             │    POST /v1/chat/.../messages    │
  │                             │    which writes Cassandra only   │
  │                             │    (no Redis needed on that      │
  │                             │     path — dedup via             │
  │                             │     Idempotency-Key header       │
  │                             │     stored in a local PG outbox  │
  │                             │     instead, see §4.5).          │
  │                             │  • Real-time delivery suspended. │
  │                             │    Clients poll GET /messages    │
  │                             │    every 10s (long-poll degraded │
  │                             │    mode).                        │
  │                             │ Ugly but functional. Fix Redis.  │
  └─────────────────────────────┴──────────────────────────────────┘

── 2.6  DATA VOLUME IN REDIS (at peak) ─────────────────────────────

  ┌──────────────────────────┬────────────┬────────────────────────┐
  │ Key pattern              │ Count      │ Size                   │
  ├──────────────────────────┼────────────┼────────────────────────┤
  │ ws_route:{userId}        │ 12,000     │ 12k × ~80 B ≈ 1 MB     │
  │ dedup:{client_msg_id}    │ 150,000    │ 500/s × 300s TTL       │
  │                          │            │ × ~50 B ≈ 7.5 MB       │
  │ presence:{userId}        │ 12,000     │ 12k × ~80 B ≈ 1 MB     │
  │ (see §3)                 │            │                        │
  │ typing:{convId}          │ ~500       │ 500 × ~120 B ≈ 60 KB   │
  │ Pub/Sub overhead         │ —          │ Negligible (no         │
  │                          │            │ persistence)           │
  ├──────────────────────────┼────────────┼────────────────────────┤
  │ TOTAL                    │            │ ~10 MB                 │
  └──────────────────────────┴────────────┴────────────────────────┘

  Chat's Redis footprint is tiny. A single small Redis instance
  handles this with room for 100× growth.

================================================================================
§3  SHOWING WHO'S ONLINE WITHOUT HURTING THE DATABASE
================================================================================

── 3.1  THE NAIVE APPROACH (what we're avoiding) ───────────────────

  Store `last_seen_at` in a Postgres/Cassandra column. Update on
  every heartbeat. Query it on every "show friend list" render.

  Math at our scale:
    • Writes:  12,000 online users × 1 heartbeat / 25s
               = 480 UPDATE/sec. On a column that triggers a row
               rewrite. Index churn, vacuum pressure, WAL bloat.
    • Reads:   Every conversation list view fetches presence for
               ~20 contacts. 2,000 list views/sec × 20 lookups
               = 40,000 presence reads/sec. Against the primary
               (can't read from replica — presence must be fresh).

  This is how you kill a database with ephemeral data that doesn't
  even need to be durable.

── 3.2  OUR APPROACH: TTL-BASED PRESENCE IN REDIS ─────────────────

  THE KEY INSIGHT: "online" means "heartbeat received in the last
  30 seconds". We don't need to STORE a timestamp and COMPARE it —
  we let Redis TTL do the comparison for free.

  Redis key:

    presence:{userId}  →  "online"     TTL: 30s, refreshed on heartbeat

  How it works:

    ON HEARTBEAT (every 25s from each connected client):
      SET presence:{userId} "online" EX 30

      That's it. One O(1) Redis command. No read-modify-write.
      No timestamp comparison. The TTL IS the presence logic.

    ON DISCONNECT (clean close):
      DEL presence:{userId}
      (Optional — the TTL would clean it up in ≤ 30s anyway. DEL
       just makes it instant.)

    ON CRASH (no clean disconnect):
      No action needed. The key expires 30s after the last
      heartbeat. User automatically shows as offline.

    TO CHECK IF USER X IS ONLINE:
      EXISTS presence:{userId}
        1 → online
        0 → offline

    TO CHECK 20 USERS AT ONCE (friend list render):
      MGET presence:user1 presence:user2 ... presence:user20
        ["online", null, "online", null, ...]
      One round-trip for all 20. ~0.5 ms.

── 3.3  WHY THIS DOESN'T HURT ANYTHING ─────────────────────────────

  ┌────────────────────────────────────────────────────────────────┐
  │                                                                │
  │   WRITES: 480 SET/sec (one per heartbeat).                     │
  │           Redis handles 100,000+ ops/sec. This is 0.5%.        │
  │           Each SET is O(1), in-memory, ~microseconds.          │
  │           No disk I/O (AOF everysec batches these).            │
  │                                                                │
  │   READS:  40,000 presence lookups/sec, but batched via MGET    │
  │           into ~2,000 MGET/sec of 20 keys each. Still 0.5%.    │
  │                                                                │
  │   MEMORY: 12,000 keys × ~80 B/key ≈ 1 MB. Nothing.             │
  │                                                                │
  │   DATABASE: ZERO queries. Postgres/Cassandra never hear about  │
  │             presence. They're blissfully unaware.              │
  │                                                                │
  └────────────────────────────────────────────────────────────────┘

  This is the correct shape for EPHEMERAL, HIGH-FREQUENCY state:
  in-memory store, TTL-based expiry, no durable writes.

── 3.4  THREE PRESENCE STATES (online / away / offline) ────────────

  Most chat apps distinguish "online" (active) from "away" (idle
  tab). We support this with the VALUE of the presence key:

    presence:{userId} → "online"  — client is foregrounded, user
                                    is actively using the app.
    presence:{userId} → "away"    — client is backgrounded or
                                    idle > 5 min. Still connected
                                    (WS open, heartbeating), but
                                    not actively looking.
    (key absent)      → "offline" — no heartbeat in 30s. Socket
                                    is closed or dead.

  Client controls the transition:
    • On WS connect: SET presence:{me} "online" EX 30
    • On tab blur / app background: SET presence:{me} "away" EX 30
    • On tab focus / app foreground: SET presence:{me} "online" EX 30
    • On idle timer (5 min no interaction): same as blur.
    • Heartbeat refreshes with CURRENT state (client remembers).

  Server-side reads are unchanged — MGET returns the string, caller
  interprets.

── 3.5  PUSHING PRESENCE CHANGES (not polling) ────────────────────

  The MGET approach above is pull-based: client renders a friend
  list, fetches presence at that moment. Fine for one-off renders,
  but chat UIs want LIVE updates ("Abebe just came online").

  TWO OPTIONS:

  OPTION A — Keyspace notifications (rejected)

    Redis can publish an event when a key is SET or EXPIRES
    (`notify-keyspace-events Kx`). Chat pods subscribe to
    `__keyevent@0__:set` and `__keyevent@0__:expired`, filter for
    `presence:*`, and push to interested sockets.

    Problem: EVERY pod receives EVERY presence event. At 480
    changes/sec and 30 pods, each pod filters 480 events/sec to
    find the ~16 it cares about. Wasteful (same problem as §1.2
    Strategy B).

  OPTION B — Explicit presence subscriptions (CHOSEN)

    When a client opens a conversation (or a friend list view), it
    sends a WS frame:
      {"t":"presence_sub","user_ids":["abebe","hana","dawit"]}

    The pod records these in its in-memory state:
      socket_id → { ..., presence_watching: Set<user_id> }

    When the pod processes a heartbeat from user X (it IS the pod
    that received the heartbeat, so it knows), it checks its local
    inverted index:
      presence_watchers:{userId} → Set<socket_id>

    If any local sockets are watching X, push to them:
      {"t":"presence","user_id":"X","status":"online"}

    CROSS-POD: What if Abebe heartbeats on Pod #1, but Hana (who's
    watching Abebe) is on Pod #3?

      We use the same routing fabric as messages (§1.4). When
      Pod #1 processes Abebe's heartbeat:

        1. SET presence:abebe "online" EX 30
        2. Look up who's watching Abebe (from a Redis SET):
             SMEMBERS presence_watchers:abebe
             → ["hana", "tigist"]
        3. For each watcher, MGET their route:
             MGET ws_route:hana ws_route:tigist
             → ["chat-pod-3", "chat-pod-1"]
        4. Group by pod, PUBLISH presence update:
             PUBLISH pod:chat-pod-3
               {"type":"presence_update","user_id":"abebe",
                "status":"online","deliver_to":["hana"]}

      Pod #3 receives, looks up hana's socket, pushes the frame.

    STORAGE for this:

      presence_watchers:{userId} → Redis SET of watcher user_ids
        TTL: 60s, refreshed when any watcher re-subscribes.

      On {"t":"presence_sub"}: for each watched user_id,
        SADD presence_watchers:{watched} {watcher}
        EXPIRE presence_watchers:{watched} 60

      On {"t":"presence_unsub"} or socket close: SREM.

    Cost: one SADD per watched user per subscription (bounded —
    typical friend list = 20 users = 20 SADDs on view open). One
    SMEMBERS + MGET per heartbeat that has watchers. Negligible.

── 3.6  TYPING INDICATORS — SAME PATTERN, SHORTER TTL ──────────────

  "Hana is typing…" is presence's little sibling. Identical
  mechanism, tighter TTL.

    typing:{convId} → Redis SET of user_ids currently typing
      TTL: 5s, refreshed on each keystroke burst.

  Client sends {"t":"typing","conv_id":"C","state":true} when the
  user starts typing, {"state":false} when they stop or send.

  On state=true:
    SADD typing:{convId} {userId}
    EXPIRE typing:{convId} 5
    PUBLISH to all online conv members (via route lookup).

  On state=false or 5s TTL expire:
    Typing indicator disappears. No explicit state=false message
    needed if user just stops typing — TTL handles it.

  5s TTL means a user who starts typing then closes the laptop
  doesn't show "typing…" forever. Self-healing.

── 3.7  PRESENCE PRIVACY (future consideration) ────────────────────

  Some users may want to hide their online status. If we add this:

    user_settings:hide_presence → true/false  (in Identity DB)

    Chat pods cache this flag (via user.events). If true:
      • Don't SET presence:{userId} on heartbeat.
      • Don't register them in presence_watchers.

    The user always appears offline. The TTL mechanism doesn't
    change — we just skip participating in it.

================================================================================
§4  WHAT HAPPENS WHEN THE INTERNET IS BAD AND A MESSAGE FAILS
================================================================================

── 4.1  FAILURE TAXONOMY ───────────────────────────────────────────

  "The internet is bad" manifests in several ways:

  ┌──────────────────────────┬──────────────────────────────────────┐
  │ Failure mode             │ What the client observes             │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ A. Packet loss /         │ WS frame sent, no ACK received       │
  │    transient drop        │ within timeout. Socket still open.   │
  │    (2G/edge, congestion) │                                      │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ B. Connection reset      │ Socket closes with error. TCP RST    │
  │    (wifi→cellular        │ or WS close frame. Must reconnect.   │
  │     handoff, tunnel,     │                                      │
  │     NAT timeout)         │                                      │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ C. High latency spike    │ Everything works but takes 2–10s     │
  │    (overloaded cell      │ per round-trip. Pongs arrive late.   │
  │     tower, VPN)          │                                      │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ D. Partial success       │ Server persisted the message but the │
  │    (server got it, ACK   │ ACK frame was lost on the way back.  │
  │     was lost)            │ Client doesn't know it succeeded.    │
  ├──────────────────────────┼──────────────────────────────────────┤
  │ E. Long offline          │ No connectivity at all. Client       │
  │    (airplane mode,       │ queues locally. Hours may pass       │
  │     rural area)          │ before reconnect.                    │
  └──────────────────────────┴──────────────────────────────────────┘

── 4.2  CLIENT-SIDE OUTBOX (the universal answer) ─────────────────

  The mobile/web client maintains its own LOCAL outbox — a queue of
  messages that have been composed but not yet ACKed by the server.

  CLIENT OUTBOX SCHEMA (SQLite on mobile, IndexedDB on web):

    outbox (
      client_msg_id   UUID PRIMARY KEY   -- generated by client
      conversation_id TEXT
      body            TEXT
      media_refs      TEXT               -- JSON array
      created_at      TIMESTAMP          -- when user hit send
      attempts        INT DEFAULT 0
      last_attempt_at TIMESTAMP
      state           TEXT               -- 'pending'|'sent'|'failed'
    )

  SEND FLOW:

    1. User types "hey" and hits send.
    2. Client generates client_msg_id = uuid_v7().
    3. Client INSERTs into local outbox (state='pending').
    4. Client IMMEDIATELY renders the message in the UI with a
       "sending…" spinner (optimistic UI).
    5. Client sends WS frame (or REST POST if WS is down).
    6. Client starts a 5s ACK timer.

    ON ACK received {"t":"ack","client_msg_id":...,"server_id":...}:
    7. UPDATE outbox SET state='sent', server_id=...
       WHERE client_msg_id=...
    8. UI: spinner → single checkmark ("sent").
    9. (Later, on {"t":"read",...}: checkmark → double/blue.)

    ON TIMEOUT (5s, no ACK):
    7. attempts += 1, last_attempt_at = now.
    8. Retry (see §4.4 backoff schedule).

    ON EXPLICIT ERROR {"t":"error","code":...}:
    7. If retriable (code="degraded", "rate_limited",
       "server_restart"): same as timeout, retry with backoff.
    8. If non-retriable (code="forbidden", "blocked",
       "conversation_not_found"): state='failed'. UI shows red
       "!" with the error message. No retry.

── 4.3  RESYNC ON RECONNECT (handles failures B, D, E) ─────────────

  When a WebSocket reconnects after ANY disruption, the client
  doesn't know what it missed. The resync protocol fixes this.

  CLIENT ON RECONNECT:

    For each open conversation C:
      1. Look up last_confirmed_msg_id for C (the highest server_id
         we've received and rendered).
      2. Send {"t":"sub","conv_id":"C",
              "since_msg_id":"<last_confirmed>"}

  SERVER ON {"t":"sub",...,"since_msg_id":X}:

    1. Query Cassandra:
         SELECT * FROM messages_by_conversation
          WHERE conversation_id = C
            AND message_id > X      -- TIMEUUID comparison
          LIMIT 200;
    2. Push each row as a {"t":"msg",...} frame.
    3. If 200 rows returned (limit hit), also send
       {"t":"resync_more","conv_id":"C"} — client paginates.

  WHAT THIS FIXES:

    • Failure B (connection reset): Missed messages while
      disconnected → filled in on reconnect.
    • Failure D (ACK lost): Client thinks message failed, retries.
      Server dedup (§2.3) catches the retry, re-sends the ACK.
      Meanwhile, the message IS in Cassandra and IS delivered to
      recipients. On resync, client sees its own message coming
      back from the server (matches by client_msg_id, marks as
      sent, dedupes in UI).
    • Failure E (long offline): Same as B but bigger gap. Client
      resyncs potentially hundreds of messages. Pagination
      handles it.

  ORDERING GUARANTEE:

    Cassandra clustering key is message_id = TIMEUUID, ordered DESC
    (res1 §5.2). Resync returns messages in order. Client inserts
    them into its local timeline by server timestamp. No reordering
    glitches.

── 4.4  RETRY + BACKOFF SCHEDULE ──────────────────────────────────

  Applies to BOTH message send retries and WebSocket reconnects.

  ┌─────────┬────────────────┬────────────────────────────────────┐
  │ Attempt │ Wait before    │ Notes                              │
  │         │ retry          │                                    │
  ├─────────┼────────────────┼────────────────────────────────────┤
  │   1     │ 0s (immediate) │ Network hiccup often resolves      │
  │         │                │ instantly. Try once right away.    │
  │   2     │ 1s  + jitter   │ jitter = random(0, 500ms).         │
  │   3     │ 2s  + jitter   │ Exponential backoff. Jitter        │
  │   4     │ 4s  + jitter   │ prevents thundering herd when      │
  │   5     │ 8s  + jitter   │ 1,000 clients all disconnect at    │
  │   6     │ 16s + jitter   │ once (e.g., pod restart, see       │
  │   7     │ 30s + jitter   │ res3 R7).                          │
  │   8+    │ 30s + jitter   │ Cap at 30s. Keep trying forever    │
  │         │ (steady state) │ (user may regain connectivity      │
  │         │                │ hours later).                      │
  └─────────┴────────────────┴────────────────────────────────────┘

  MESSAGE SEND retries have a separate cap:
    After attempt 6 (cumulative ~30s) with no success:
      state = 'failed'. UI shows "⚠️ Not delivered — tap to retry".
    User can manually retry (resets attempts to 0).

  RECONNECT retries never give up — as long as the app is open,
  keep trying every 30s. The moment connectivity returns, the
  socket connects, outbox drains, resync fills gaps.

── 4.5  REST FALLBACK (handles failure C, and WS unavailability) ───

  If the WebSocket won't establish (corporate firewall blocks WS,
  proxy mangles upgrade, or WS path is genuinely down), the client
  falls back to REST:

    POST /v1/chat/conversations/{convId}/messages
      Headers: Idempotency-Key: <client_msg_id>
      Body:    { body, media_refs, client_msg_id }

    (res3 §6.2 — this endpoint already exists.)

  Server-side idempotency (res3 §6 conventions): the Idempotency-Key
  is checked against Redis (idem:chat:{key}, TTL 24h). Duplicate →
  return cached response.

  Receiving messages without WS: LONG-POLLING.

    GET /v1/chat/conversations/{convId}/messages/poll
      ?since_msg_id=<X>&timeout=25

    Server holds the request open for up to 25s. If a new message
    arrives in that window, return immediately. Else, return empty
    after 25s; client immediately re-polls.

    Less efficient than WS (one HTTP round-trip per message-ish)
    but FUNCTIONAL. Used only when WS is unavailable.

  FALLBACK DETECTION on the client:

    • Attempt WS connect. If it fails 3 times in a row → switch to
      REST mode for this session.
    • In REST mode, periodically (every 5 min) try WS again. If it
      succeeds → switch back, resync (§4.3), resume normal
      operation.

── 4.6  END-TO-END EXAMPLE: BAD CAMPUS WIFI ───────────────────────

  Scenario: Abebe is walking across campus. Wifi drops for 40
  seconds as he passes between buildings. He sends 3 messages
  during this window.

  Timeline:

    t=0s    Abebe sends msg #1. Goes into local outbox. WS frame
            sent. No ACK (packet lost in the air).

    t=5s    ACK timeout. Retry #1 (immediate). Still no ACK.

    t=6s    Abebe sends msg #2. Goes into local outbox.

    t=6s    Retry #2 for msg #1 (1s + jitter after retry #1).

    t=8s    Wifi fully drops. TCP connection dies. Client detects:
            WS onclose fires with code 1006 (abnormal close).

    t=8s    Client starts reconnect loop. Attempt 1 fails
            (no network). Attempt 2 scheduled for t=9s.

    t=12s   Abebe sends msg #3. No network. Goes into local outbox.
            No send attempt (client knows it's offline).

    t=15s   All 3 messages show in Abebe's UI with spinners.

    t=45s   Wifi reconnects. Client's attempt N succeeds. WS opens
            to Pod #7 (different pod than before — doesn't matter).

    t=45s   SET ws_route:abebe "chat-pod-7" EX 45.

    t=45s   Client sends {"t":"sub","conv_id":"C","since_msg_id":M}.
            Pod #7 queries Cassandra, pushes any messages Abebe
            missed while offline (say, 2 messages from Hana).

    t=46s   Client drains its outbox: re-sends WS frames for
            msg #1, #2, #3 with their original client_msg_ids.

    t=46s   Server dedup: msg #1 — was it received before the drop?
            • If YES (the original WS frame made it, only the ACK
              was lost): dedup hits. Server re-sends the original
              ACK. Client marks msg #1 sent.
            • If NO (frame was lost in the air): dedup misses.
              Normal processing. Cassandra write. ACK. Delivered.

            Either way: msg #1 is sent exactly once, ACKed exactly
            once from the client's perspective.

    t=47s   All 3 messages ACKed. Spinners → checkmarks.

    t=47s   Abebe sees Hana's 2 messages that arrived while he was
            offline (from the resync).

  Net result: 40-second blackout → ~2 seconds of catch-up after
  reconnect. No message lost, no duplicate, no manual intervention.

── 4.7  WHAT THE SERVER DOES WHEN THE CLIENT IS SILENT ─────────────

  From the server's perspective:

    t=0s    Abebe's last heartbeat received.
    t=25s   Next heartbeat expected. None arrives.
    t=30s   presence:abebe expires. Abebe shows offline to others.
    t=45s   ws_route:abebe expires. Pod #1 still holds a socket
            object for Abebe, but it's dead (TCP timeout will
            eventually fire).
    t=~60s  TCP keepalive on the server side detects dead socket.
            Pod #1 cleans up: removes from in-memory subscription
            table. (ws_route already expired, nothing to DEL.)

  Messages sent TO Abebe during t=0–45s:
    • Sender's pod does MGET ws_route:abebe. During t=0–45s it
      returns "chat-pod-1". Sender PUBLISHes to pod:chat-pod-1.
    • Pod #1 receives, looks up Abebe's socket, tries to write.
      Write fails (dead socket) or succeeds-but-lost (TCP
      retransmit into the void).
    • Doesn't matter. Message is in Cassandra. Abebe's client
      will resync on reconnect.
    • After t=45s, ws_route returns null. Sender's pod skips
      real-time delivery entirely. Notification Service handles
      offline push via message.events (FCM).

  No server crash, no stuck state, no leak. TTLs clean everything.

================================================================================
§5  ONE-PAGE SUMMARY
================================================================================

┌──────────────────┬───────────────────────────────────────────────────────┐
│ FAST ACROSS      │ Directed routing: ws_route:{userId} → pod_id in       │
│ MANY SERVERS     │ Redis (TTL 45s, heartbeat-refreshed). Sender looks    │
│                  │ up recipient's pod with one MGET, publishes to that   │
│                  │ pod's Redis Pub/Sub channel. O(recipients) work per   │
│                  │ message, flat regardless of pod count. Cassandra      │
│                  │ write (durability) + one Redis MGET (routing) +       │
│                  │ one Pub/Sub hop ≈ 10ms end-to-end.                    │
├──────────────────┼───────────────────────────────────────────────────────┤
│ REDIS KEEPS      │ Four roles:                                           │
│ EVERYONE         │  1. Routing table (ws_route:{u} → pod). The           │
│ CONNECTED        │     phonebook.                                        │
│                  │  2. Pub/Sub channels (pod:{id}). The inter-pod        │
│                  │     message bus. Fire-and-forget, sub-ms.             │
│                  │  3. Dedup store (dedup:{client_msg_id} NX EX 300).    │
│                  │     Makes client retries safe.                        │
│                  │  4. (NOT Redis) Subscription state lives in pod RAM.  │
│                  │     Ephemeral to the socket; no durability needed.    │
│                  │ Total Redis footprint: ~10 MB. Redis failure → 10s    │
│                  │ of delayed delivery during failover, zero data loss.  │
├──────────────────┼───────────────────────────────────────────────────────┤
│ PRESENCE WITHOUT │ SET presence:{userId} "online" EX 30 on every         │
│ HURTING THE DB   │ heartbeat. That's the entire write path. Reads:       │
│                  │ EXISTS or MGET. Key present = online; absent =        │
│                  │ offline. TTL IS the logic — no timestamp              │
│                  │ comparison, no DB column, no index churn.             │
│                  │ 480 SET/sec writes + 2,000 MGET/sec reads = ~1% of    │
│                  │ Redis capacity. Postgres/Cassandra: zero queries.     │
│                  │ Typing indicators: same pattern, 5s TTL instead of    │
│                  │ 30s. Self-healing when user walks away.               │
├──────────────────┼───────────────────────────────────────────────────────┤
│ BAD INTERNET /   │ Client-side outbox: every message queued locally      │
│ MESSAGE FAILS    │ with a client_msg_id UUID before sending. Optimistic  │
│                  │ UI shows "sending…" immediately.                      │
│                  │                                                       │
│                  │ Retry with exponential backoff + jitter               │
│                  │ (1s → 30s cap). Server dedupes by client_msg_id       │
│                  │ (SET NX) — retries are safe.                          │
│                  │                                                       │
│                  │ On reconnect: resync protocol. Client sends           │
│                  │ {"t":"sub","since_msg_id":X}; server replays          │
│                  │ everything after X from Cassandra. Fills any gap.     │
│                  │                                                       │
│                  │ WS unavailable: REST fallback                         │
│                  │ (POST /messages + long-poll GET). Degraded but        │
│                  │ functional.                                           │
│                  │                                                       │
│                  │ 40s network blackout → ~2s catch-up on reconnect.     │
│                  │ No loss, no duplicates, no manual intervention.       │
└──────────────────┴───────────────────────────────────────────────────────┘

════════════════════════════════════════════════════════════════════════════════
END
════════════════════════════════════════════════════════════════════════════════
