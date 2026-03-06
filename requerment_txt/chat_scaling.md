# ASTU Connect — Chat Scaling Plan

**Questions being answered:**
- How do we keep messages fast when we are running many Chat Service servers at once?
- How do we use Redis to keep every student connected to the right server?
- How do we show who is online without destroying the database?
- What happens when a student has a bad connection and their message does not go through?

**Document Version:** 1.0
**Date:** 2026-02-27
**Relates to:** `architecture01.md` — Section 5.5 (Chat Service)

---

## Table of Contents

1. [The Fundamental Problem with Chat at Scale](#1-the-fundamental-problem-with-chat-at-scale)
2. [WebSocket Connections and Why They Are Special](#2-websocket-connections-and-why-they-are-special)
3. [Scaling Across Multiple Servers](#3-scaling-across-multiple-servers)
4. [How Redis Holds Everything Together](#4-how-redis-holds-everything-together)
5. [Online Presence — Showing Who Is Active Without Killing the Database](#5-online-presence--showing-who-is-active-without-killing-the-database)
6. [The Full Message Delivery Flow](#6-the-full-message-delivery-flow)
7. [Unreliable Connections — What Happens When a Message Does Not Go Through](#7-unreliable-connections--what-happens-when-a-message-does-not-go-through)
8. [Client-Side Reliability Protocol](#8-client-side-reliability-protocol)
9. [Message Delivery States](#9-message-delivery-states)
10. [Group Chats — Extra Complexity](#10-group-chats--extra-complexity)
11. [Failure Scenarios and Mitigations](#11-failure-scenarios-and-mitigations)
12. [Capacity and Limits](#12-capacity-and-limits)

---

## 1. The Fundamental Problem with Chat at Scale

HTTP is a request-response protocol. The client asks, the server answers, the connection closes. This works fine for fetching a feed or loading a profile. It does not work for chat.

In chat, the server needs to push a message to a client the moment it arrives — without the client asking first. The client needs to be permanently reachable. The connection must stay open.

This is why chat uses **WebSockets** — a persistent, bidirectional connection between the client and server that stays open for as long as the student is in the app. The server can push a message at any moment. The client can send a message without the overhead of opening a new connection each time.

The complication: unlike stateless HTTP handlers that can be spread across a hundred servers with no coordination (any server can answer any request), **WebSocket connections are stateful**. A student's connection lives on exactly one server. If student A is on Server 1 and sends a message to student B who is on Server 7, Server 1 has to get that message to Server 7 somehow.

This is the core scaling challenge for chat, and everything in this document is about solving it.

---

## 2. WebSocket Connections and Why They Are Special

A WebSocket connection is a long-lived TCP socket. Once established, both sides can send frames to the other without waiting. The connection stays open until one side closes it or the network drops it.

For ASTU Connect, the lifecycle looks like this:

```
Student opens the app
         ↓
Client sends HTTP Upgrade request to API Gateway
         ↓
API Gateway verifies JWT, then upgrades the connection to WebSocket
and proxies it to a Chat Service instance
         ↓
Chat Service instance holds the open connection
Records: "student 42 is connected to me (instance chat-pod-3)"
         ↓
Student uses the app normally — connection stays open
         ↓
Any message for student 42 must be delivered through chat-pod-3
         ↓
Student closes app / connection times out
Chat Service removes the record
```

Each Chat Service pod can hold approximately **10,000 concurrent WebSocket connections** before memory and CPU become constraints. With 5,000 concurrent students at peak, three or four pods is sufficient. We deploy more as the student base grows.

The problem: with four pods, a message sender on pod-1 may need to deliver to a recipient on pod-3. Pod-1 does not have a direct pipe to pod-3. They need a shared coordination layer.

---

## 3. Scaling Across Multiple Servers

### Why You Cannot Just Add More Servers Naively

If we simply put a load balancer in front of four Chat Service pods and route connections randomly, we create an immediate problem:

```
Student A  ──── pod-1
Student B  ──── pod-3

A sends a message to B.
pod-1 receives the message.
pod-1 has no idea B is on pod-3.
pod-1 cannot deliver the message to B.
```

The naive fix — direct pod-to-pod communication — does not scale. With N pods, each pod would need to maintain connections to every other pod. N=4 is manageable. N=20 becomes a web of 190 connections. N=50 is 1,225 connections. This is a full mesh topology and it breaks under any meaningful scale.

### The Kafka Pub/Sub Router

The solution is to route inter-pod messages through Kafka rather than directly. No pod talks to another pod. Every pod publishes outbound messages to Kafka and subscribes to receive inbound messages for their connected clients.

```
      pod-1                   Kafka                    pod-3
        │                       │                        │
A sends │                       │                        │
message │──publish──────────────►│                        │
to B    │  chat.messages topic   │──deliver to pod-3──────►│
        │                       │   (pod-3 subscribed)   │──push to B via WS
        │                       │                        │
```

Every pod subscribes to the same `chat.messages` topic. When a message arrives on that topic, each pod checks: "is the intended recipient connected to me?" If yes, deliver it via WebSocket. If no, ignore it.

This looks inefficient — every pod receives every message — but in practice the volume per pod is low. Kafka delivers each message partition to a consumer group, and each pod handles only the partitions assigned to it. We partition the chat topic by `conversationId`, so messages in the same conversation always land on the same consumer group partition, ensuring ordering is preserved.

There is a more targeted alternative: instead of broadcasting to all pods, Redis can tell the sending pod exactly which pod the recipient is on, and the message can be published to a pod-specific sub-topic. This reduces unnecessary consumption. We implement this optimization in Phase 2 (see Section 12).

---

## 4. How Redis Holds Everything Together

Redis is the shared memory of the Chat Service. Every pod reads from and writes to the same Redis cluster. It is the source of truth for three things: who is connected, which pod they are on, and what their current state is.

### 4.1 Connection Registry

When a student connects via WebSocket, their pod writes a single Redis key:

```
Key:    chat:conn:{studentId}
Value:  {
          instanceId:   "chat-pod-3",
          connectedAt:  "2026-02-27T09:14:00Z",
          deviceType:   "mobile"
        }
TTL:    90 seconds (refreshed every 30 seconds by a heartbeat from the pod)
```

When a student disconnects cleanly, the pod deletes this key. If the pod crashes or the student's connection drops without a clean close (common on mobile networks), the TTL ensures the key expires automatically within 90 seconds rather than lingering as a ghost entry forever.

**Why TTL-based expiry matters for ASTU:** Mobile students on campus wifi frequently have their connections silently dropped by the network without sending a WebSocket close frame. Without TTL expiry, the registry would fill up with stale "online" records for students who left hours ago.

### 4.2 Routing Table

When pod-1 receives a message destined for student B, it looks up the connection registry before deciding whether to publish to Kafka at all:

```
GET chat:conn:{studentB_id}

If key exists:
  → student B is online
  → instanceId tells us which pod they are on
  → if instanceId == our own pod: deliver directly via local WebSocket map
  → if instanceId == different pod: publish to Kafka, that pod will deliver

If key does not exist:
  → student B is offline
  → save message to Cassandra (already done)
  → publish chat.message.sent to Kafka for Notification Service to send push notification
```

This single Redis lookup at send time routes the message correctly without any pod needing to know the topology of other pods.

### 4.3 Unread Message Counts

Every time a message is sent to a student, their unread count for that conversation is incremented. These counts drive the badge numbers shown in the app UI.

```
Redis key:  chat:unread:{studentId}:{conversationId}
Type:       Integer counter
Operation:  INCR on new message
            SET to 0 when student marks conversation as read
```

Storing these in Redis rather than PostgreSQL is essential. Reading someone's unread count happens every time the app opens and on every notification. If 5,000 students open the app simultaneously and each triggers a count query to PostgreSQL, the database takes 5,000 reads at once for data that changes constantly. Redis handles this trivially — INCR and GET on an integer are among the fastest operations Redis supports.

### 4.4 Typing Indicators

"Student X is typing..." is a transient state. It must never be stored in a database — it has no persistence value and changes dozens of times per minute.

```
Redis key:  chat:typing:{conversationId}:{studentId}
Value:      1
TTL:        5 seconds (auto-expires if the typing event stops)
```

When a student types, the client sends a typing event over the WebSocket. The pod sets this key. Other participants in the conversation poll their pod for conversation state updates (or receive a push from the pod via WebSocket). The 5-second TTL means if the student stops typing without explicitly sending a "stopped typing" event — which is common — the indicator disappears automatically.

---

## 5. Online Presence — Showing Who Is Active Without Killing the Database

### The Naive Approach and Why It Fails

The obvious approach: when a student connects, write `UPDATE students SET online = true, last_seen = now() WHERE id = ?`. When they disconnect, set `online = false`.

Problems:
- On a campus social platform, students connect and disconnect constantly — switching between wifi and cellular, locking their phones, multitasking. This could mean hundreds of `UPDATE` queries per minute against the PostgreSQL students table.
- "Last seen" timestamps update continuously. PostgreSQL is not designed for high-frequency updates to hot rows.
- Reading presence for a list of students (e.g., "show me which of my 50 chat contacts are online") means a `SELECT WHERE id IN (...)` query on a table being written to constantly. Locking contention becomes a problem.

### The Correct Approach: Redis as the Presence System

Presence is a **live, volatile state** — it belongs in Redis, not a relational database. PostgreSQL stores permanent facts. Presence is not a permanent fact; it is a transient observation.

#### Two Tiers of Presence

We distinguish between two different things users care about:

**Tier 1 — Active now (online indicator)**
The green dot. Is this student reachable right now?

```
Key:    chat:conn:{studentId}          (described in Section 4.1)
Logic:  If this key exists → online
        If this key does not exist → offline or unknown
TTL:    90 seconds, refreshed by heartbeat every 30 seconds
```

No database involved. A single Redis GET per student.

**Tier 2 — Last active (last seen timestamp)**
"Last seen 2 hours ago." Relevant when the student is offline.

```
Key:    chat:last_seen:{studentId}
Value:  Unix timestamp of last heartbeat or disconnect
TTL:    7 days (after which we stop showing a specific time)
```

This key is written when the student disconnects and periodically refreshed during active sessions. It is written to Redis, not PostgreSQL. An async job reconciles these values to PostgreSQL in batches (every 15 minutes) for any long-term storage requirements, but the live query always reads from Redis.

#### Heartbeat Protocol

Every 30 seconds, each Chat Service pod sends a heartbeat ping over every open WebSocket connection. If the client responds, the pod refreshes the `chat:conn:{studentId}` key's TTL for another 90 seconds. If the client does not respond within 10 seconds, the pod treats the connection as dead, deletes the key, and closes the socket.

```
Timeline of a dropped mobile connection:

T=0:    Student's wifi drops silently (no TCP RST, no WebSocket close frame sent)
T=30s:  Pod sends heartbeat ping → no response
T=40s:  Pod times out, deletes chat:conn:{studentId}, closes the socket
T=40s:  Student shows as "offline" in other students' UIs
T=40s:  chat:last_seen:{studentId} is set to T=40s timestamp
```

From other students' perspective, the student goes offline within 40 seconds of losing connectivity. On a campus with generally decent wifi, this window is acceptable.

#### Bulk Presence Reads — "Who in My Contacts Is Online?"

When a student opens their contacts or DM list, the client needs to know which of their contacts are currently online. This is a bulk presence read — potentially dozens of lookups at once.

The naive approach: issue one Redis GET per contact. For 50 contacts, that is 50 round-trips. Slow.

The correct approach: Redis `MGET` (multi-get) — one command, up to hundreds of keys, one round-trip:

```
MGET chat:conn:{id1} chat:conn:{id2} chat:conn:{id3} ... chat:conn:{id50}

Returns: [data, nil, data, nil, data, ...]
         present value = online
         nil = offline
```

50 presence checks in one Redis command, sub-millisecond. No database involved, no matter how many students make this request simultaneously.

#### Presence Privacy

Not all students want to share their online status. The platform supports a preference:

```
Redis key:  chat:presence_visible:{studentId}
Value:      "1" (visible) or "0" (hidden)
```

Before returning presence data for student X to student Y, the server checks this key. If hidden, student X always appears offline to everyone except in their own view. This check is also a Redis GET — no database query.

---

## 6. The Full Message Delivery Flow

This is what actually happens from the moment a student taps "send" to the moment the recipient sees the message.

```
SENDER SIDE
───────────
1. Student A types a message and taps Send
2. Client generates a client-side message ID (UUID) — used for deduplication
3. Client sends over WebSocket:
   {
     clientMsgId:    "client-uuid-abc",
     conversationId: "conv-123",
     content:        "Did you get the exam schedule?",
     sentAt:         "2026-02-27T09:15:00Z"
   }

CHAT SERVICE — RECEIVING POD (pod-1, where A is connected)
───────────────────────────────────────────────────────────
4. pod-1 receives the frame
5. Validates: Is A a participant of conv-123?  (check local cache, fallback to PostgreSQL)
6. Assigns a server-side message ID (UUID) and a server timestamp
7. Persists to Cassandra:
   (conversationId=conv-123, timestamp=server_ts, messageId=server-uuid, senderId=A, content=...)
8. Acknowledges to sender A immediately:
   { clientMsgId: "client-uuid-abc", serverMsgId: "server-uuid-xyz", status: "saved" }
   ↑ This ACK is sent before delivery to the recipient.
     A knows their message is safely stored regardless of what happens next.

ROUTING AND DELIVERY
────────────────────
9.  pod-1 looks up recipient(s) of conv-123
    For a DM: just student B
    For a group: all participants except A

10. For each recipient, checks Redis:
    GET chat:conn:{studentB_id}

    Case A: B is online on pod-1 (same pod)
    → Deliver directly via local WebSocket map. Done. Fast path.

    Case B: B is online on pod-3 (different pod)
    → Publish to Kafka: chat.messages topic, partition=hash(conversationId)
    → pod-3 is subscribed, receives the message, delivers to B via WebSocket

    Case C: B is offline (key does not exist in Redis)
    → Message already in Cassandra — B will receive it on next load
    → Publish chat.message.sent to Kafka for Notification Service
    → Notification Service sends push notification to B's device

RECIPIENT SIDE
──────────────
11. B receives the message frame via WebSocket
12. B's client sends a delivery acknowledgment back to pod-3:
    { serverMsgId: "server-uuid-xyz", status: "delivered" }
13. pod-3 updates delivery status in Redis:
    SET chat:delivery:{serverMsgId} "delivered"
14. pod-3 notifies pod-1 (via Kafka) that delivery is confirmed
15. pod-1 pushes delivery status update to A:
    A's UI shows the single-tick → double-tick transition

READ RECEIPT
────────────
16. B opens the conversation and reads the message
17. B's client sends: { conversationId: "conv-123", readUpTo: "server-uuid-xyz" }
18. Chat Service updates B's last_read_at in PostgreSQL
19. Decrements chat:unread:{B}:{conv-123} counter in Redis to 0
20. Notifies A that B has read the message (if A is still online)
    → A's UI shows the read receipt tick
```

The critical design choice in step 8: **the server acknowledges the sender before delivery to the recipient.** This separates "your message is saved" from "your message has been delivered." The sender gets immediate confirmation that their message is not lost. Delivery is a second, asynchronous step.

---

## 7. Unreliable Connections — What Happens When a Message Does Not Go Through

Bad mobile connections are the norm on a university campus — hundreds of students in the same building competing for wifi, 3G/4G that cuts out between classes, elevator dead zones. The chat system must handle all of these gracefully.

We categorize connection problems into three types and handle each differently.

---

### Type 1 — Message Sent but No Server ACK (Connection Lost Before Confirmation)

Student A sends a message. The WebSocket frame leaves the client. Before the server ACK (step 8 above) arrives back, A's connection drops.

**A does not know if the message was saved.**

```
Client state:
  message "client-uuid-abc" in status: PENDING_ACK
  (shown with a spinner/clock icon in the UI)

A's connection is re-established (see Section 8 on reconnection)

On reconnect, client sends:
  { action: "check_pending", clientMsgIds: ["client-uuid-abc"] }

Server responds:
  { clientMsgId: "client-uuid-abc", status: "saved", serverMsgId: "server-uuid-xyz" }
  OR
  { clientMsgId: "client-uuid-abc", status: "not_found" }

If "saved": client updates local state, shows message as sent
If "not_found": client automatically re-sends the message once
```

**Deduplication:** The client-generated `clientMsgId` is stored server-side alongside the server message record for 24 hours. If the re-send triggers a duplicate insertion, the server detects the matching `clientMsgId`, does not create a second message, and returns the existing `serverMsgId`. A appears once in the conversation, not twice.

---

### Type 2 — Connection Lost After ACK (Message Saved, But Not Yet Delivered)

A's message is saved to Cassandra. The server has ACKed. Then B's connection drops before delivery.

This is handled by the offline delivery path already described in step 10, Case C. B reconnects, fetches conversation history from Cassandra, and sees the message. They never experienced a gap — the message was in persistent storage the whole time.

---

### Type 3 — Extended Offline Period (Student Has No Connection for Minutes or Hours)

A student loses connectivity entirely — wifi down in a lecture hall, leaves campus, phone battery dies. This is not a momentary blip; they are fully offline.

Any messages sent to them during this period:
1. Are stored in Cassandra immediately when sent (by the sender's pod)
2. Generate a push notification via FCM/APNs (for their mobile device)
3. Are waiting in Cassandra when the student reconnects

On reconnect, the client requests missed messages:

```
Client sends on reconnect:
  { action: "sync", conversations: [
      { conversationId: "conv-123", lastSeenMsgId: "server-uuid-001" },
      { conversationId: "conv-456", lastSeenMsgId: "server-uuid-099" }
  ]}

Server responds with all messages after the given ID for each conversation,
pulled from Cassandra ordered by timestamp.
```

The client does not need to re-request message history from scratch each time — it tells the server the last message it has, and the server sends only the delta. This is efficient on both mobile data and Cassandra read throughput.

---

## 8. Client-Side Reliability Protocol

The client is an active participant in message reliability — it is not a passive receiver. The client maintains a local queue of messages and their delivery states.

### Client Message State Machine

```
User taps send
      ↓
   QUEUED  (message is in the local outbox, not yet sent over the wire)
      ↓
  WebSocket sends the frame
      ↓
 PENDING_ACK  (frame sent, waiting for server confirmation — shown with clock icon)
      ↓
  Server ACK received ("saved")
      ↓
    SENT  (confirmed saved on server — shown with single tick)
      ↓
  Recipient delivery ACK received
      ↓
  DELIVERED  (shown with double tick)
      ↓
  Recipient read receipt received
      ↓
    READ  (shown with filled double tick or read receipt indicator)
```

If the message stays in `PENDING_ACK` for more than **10 seconds** without a server ACK, the client treats the connection as degraded and transitions the message to `FAILED_PENDING_RETRY`. It shows a warning indicator ("tap to retry") and automatically attempts a re-send when the connection is restored.

### Reconnection Backoff

When the WebSocket connection drops, the client does not immediately hammer the server with reconnect attempts. It uses exponential backoff with jitter:

```
Attempt 1:  wait 1 second  + random(0–500ms)
Attempt 2:  wait 2 seconds + random(0–500ms)
Attempt 3:  wait 4 seconds + random(0–500ms)
Attempt 4:  wait 8 seconds + random(0–500ms)
Attempt 5+: wait 30 seconds (cap)
```

The jitter (random offset) is important. Without it, if 1,000 students all lose connection at the same moment (a campus-wide wifi blip), they would all attempt to reconnect in synchronized waves, creating a thundering herd of simultaneous connection requests against the Chat Service. The jitter spreads those reconnects across a window of several seconds, reducing the peak load to something manageable.

### Message Queue Persistence

The client's local outbox queue is persisted to device storage (IndexedDB on web, SQLite on mobile). This means if the app is closed while a message is in `PENDING_ACK` or `QUEUED` state, the message is not lost. When the app reopens, the queue is loaded and pending messages are re-attempted.

---

## 9. Message Delivery States

This is the full picture of delivery state from the system's perspective.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  State           │ Where tracked         │ What it means                    │
├──────────────────┼───────────────────────┼──────────────────────────────────┤
│ QUEUED           │ Client local storage  │ Not yet sent over the wire       │
│ PENDING_ACK      │ Client local storage  │ Sent, no server confirmation yet │
│ SAVED            │ Cassandra + Redis ACK │ Persisted, awaiting delivery     │
│ DELIVERED        │ Redis (short-TTL)     │ Recipient's device received it   │
│ READ             │ PostgreSQL (durable)  │ Recipient opened the conversation│
└──────────────────┴───────────────────────┴──────────────────────────────────┘
```

**Why delivery status is in Redis and read status is in PostgreSQL:**

Delivery confirmations are transient, high-volume, and short-lived. Once both sides have acknowledged delivery, the confirmation data has no long-term value. Redis with a short TTL is appropriate.

Read receipts, however, are semantically meaningful and durable. "Did they read my message?" is a question users come back to later. Read status is also used to compute unread counts across sessions. It belongs in PostgreSQL where it survives restarts and is queryable over time.

---

## 10. Group Chats — Extra Complexity

Group chats (up to 200 participants) introduce two additional problems: **fan-out at delivery time** and **read receipt complexity**.

### Group Message Fan-out

When student A sends a message to a group of 50 students, the Chat Service must deliver it to all 49 other participants. Each may be on a different pod.

The process at the receiving pod:

```
Message arrives from Kafka (or directly, if sent locally)
       ↓
Fetch list of 49 recipient student IDs for this conversationId
(cached in memory per pod, refreshed from PostgreSQL every 60 seconds)
       ↓
For each recipient:
  Check Redis: GET chat:conn:{recipientId}
       ↓
  Online on this pod → deliver via local WebSocket
  Online on other pod → already handled by Kafka broadcast
  Offline → already in Cassandra, push via Notification Service
```

The participant list for a group is cached in memory on each pod. We do not hit PostgreSQL for every message in an active group — that would be untenable at high message volume. The cache is invalidated when membership changes (someone joins or leaves), which the Community Service signals via a Kafka event.

### Group Read Receipts

Storing "who has read up to which message" for a 50-person group would mean one database write per participant per message they read. For an active group exchanging 100 messages per hour with 50 participants, that is 5,000 read receipt writes per hour for one conversation.

The design simplification: **group chats show unread count per participant, not individual read receipts per message per person.** The UI shows "50 unread" rather than a per-message "read by: A, B, C...". Individual read receipts are reserved for direct (1-on-1) messages only.

```
For DMs:         Full per-message read receipts (PostgreSQL, durable)
For group chats: Per-participant unread count only (Redis counter)
```

This reduces the write volume for group read tracking from thousands of row inserts to simple Redis INCR/DECR operations.

---

## 11. Failure Scenarios and Mitigations

### Scenario A: A Chat Service Pod Crashes

All WebSocket connections on that pod are dropped. The Redis `chat:conn:{studentId}` keys for those students have a 90-second TTL — they expire naturally. Clients detect the dropped connection and begin reconnecting with exponential backoff. They reconnect to any available pod (load balancer distributes new connections). On reconnect, they sync missed messages from Cassandra using the delta sync protocol.

No messages are lost — they are in Cassandra. Delivery may be delayed by up to 30 seconds (reconnect time + sync). This is acceptable.

### Scenario B: Redis Cluster Node Fails

Redis Cluster uses primary/replica pairs. If a primary fails, its replica is automatically promoted within a few seconds. During this election window (up to 15 seconds), presence lookups may return stale or empty results. The impact:

- Some messages may take the offline delivery path (Cassandra + push notification) instead of the real-time path, even if the recipient is technically online
- Typing indicators may not propagate
- Unread counts may lag

All of these self-correct once the cluster is restored. No messages are lost. Real-time delivery briefly degrades to near-real-time (push notification delivery instead of WebSocket delivery). This is acceptable.

### Scenario C: Kafka Is Temporarily Unavailable

Messages sent during a Kafka outage:
- Are still saved to Cassandra by the receiving pod (this does not go through Kafka)
- Cannot be delivered to recipients on other pods (Kafka is the inter-pod bus)
- Recipients on the same pod as the sender are still delivered in real time (local delivery does not use Kafka)

When Kafka recovers, pending messages are published and delivered. The gap in delivery is bounded by the duration of the outage. For the Notification Service (push notifications for offline users), messages queue up and are processed when Kafka is available — push notifications may be delayed but not lost.

### Scenario D: Cassandra Write Fails

If Cassandra is unavailable when a message is sent:
1. The Chat Service returns an error to the sender (no ACK is issued)
2. The client's message stays in `PENDING_ACK` → eventually transitions to `FAILED_PENDING_RETRY`
3. The client retries when the connection is re-established or after backoff

Messages are never delivered if they have not been persisted first. We do not ACK a message to the sender until Cassandra confirms the write. This is the guarantee: **if you see a single tick, your message is in durable storage.**

---

## 12. Capacity and Limits

### Connection Capacity

```
Per pod:          ~10,000 concurrent WebSocket connections
Initial pods:     3 (30,000 connection capacity — well above peak load)
Peak estimate:    ~5,000 concurrent users
Headroom ratio:   6x (comfortable margin before scaling is needed)
Auto-scaling:     Kubernetes HPA adds pods when active connection count
                  exceeds 70% of pod capacity
```

### Message Throughput

```
Expected peak:    ~5,000 messages/minute
Per-pod rate:     ~1,700 messages/minute at 3 pods
Cassandra write:  ~83 writes/second peak (well within Cassandra's design range
                  of hundreds of thousands of writes/second per node)
```

### Redis Memory Estimates for Presence

```
Per student:
  chat:conn:{id}        ~100 bytes
  chat:last_seen:{id}   ~50 bytes
  chat:unread:{id}:*    ~50 bytes per conversation (avg 5 active convs = 250 bytes)

For 20,000 students (all registered):
  ~400 bytes × 20,000 = ~8 MB

For 5,000 online simultaneously:
  chat:conn keys: ~500 KB active

Redis memory for presence: negligible (well under 100 MB total)
```

### Kafka Partition Sizing for Chat

```
Topic: chat.messages
Partitions: 48

At peak 5,000 messages/minute = ~83 messages/second
48 partitions = ~1.7 messages/second per partition
Each partition processed by one consumer per consumer group
Well within comfortable Kafka throughput — partitions have headroom
for 10–50× growth before repartitioning is needed
```

### The Threshold for Adding More Pods

Monitor these metrics and scale when thresholds are reached:

| Metric | Scale-out threshold |
|---|---|
| Active WebSocket connections per pod | > 7,000 (70% of 10K) |
| Message processing latency (p95) | > 200ms end-to-end |
| Kafka consumer lag on chat.messages | > 5,000 messages behind |
| Redis memory utilization | > 75% of cluster capacity |

---

*Relates to: `architecture01.md` Section 5.5 (Chat Service), Section 10.2 (Scalability) | `data_sync_plan.md` Section 6 (Chat Service cleanup on account deletion)*
