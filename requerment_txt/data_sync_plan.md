# ASTU Connect — Cross-Service Data Synchronization Plan

**Concern:** Each of our services owns its own database. When data changes in one service — especially destructive changes like account deletion — every other service that holds a copy of that data must clean up its own records. There is no shared database to handle this with a SQL `CASCADE DELETE`. We have to design this ourselves.

**Document Version:** 1.0
**Date:** 2026-02-27
**Relates to:** `architecture01.md`

---

## Table of Contents

1. [The Core Problem](#1-the-core-problem)
2. [Why We Cannot Use Distributed Transactions](#2-why-we-cannot-use-distributed-transactions)
3. [The Solution: Event-Driven Saga with Guaranteed Delivery](#3-the-solution-event-driven-saga-with-guaranteed-delivery)
4. [The Outbox Pattern — Guaranteed Event Publishing](#4-the-outbox-pattern--guaranteed-event-publishing)
5. [Account Deletion: Full Walkthrough](#5-account-deletion-full-walkthrough)
6. [What Each Service Must Do on account.deletion.initiated](#6-what-each-service-must-do-on-accountdeletioninitiated)
7. [What Happens When a Service Is Down](#7-what-happens-when-a-service-is-down)
8. [Saga Orchestration and Completion Tracking](#8-saga-orchestration-and-completion-tracking)
9. [Idempotency — Handling Duplicate Events](#9-idempotency--handling-duplicate-events)
10. [Other Cross-Service Sync Scenarios](#10-other-cross-service-sync-scenarios)
11. [Data Consistency Guarantees by Operation](#11-data-consistency-guarantees-by-operation)
12. [Failure Scenarios and Mitigations](#12-failure-scenarios-and-mitigations)

---

## 1. The Core Problem

When a student's account exists, their identity is scattered across multiple service databases:

```
Auth Service DB         Profile Service DB        Feed Service DB
┌─────────────────┐     ┌──────────────────┐      ┌─────────────────┐
│ student_id: 42  │     │ student_id: 42   │      │ posts by 42     │
│ email           │     │ name, bio, avatar│      │ reactions by 42 │
│ password hash   │     │ follow graph     │      │ comments by 42  │
│ roles           │     │ block records    │      │ feed inboxes    │
└─────────────────┘     └──────────────────┘      └─────────────────┘

Chat Service DB         Community Service DB       Notification DB
┌─────────────────┐     ┌──────────────────┐      ┌─────────────────┐
│ conversations   │     │ memberships      │      │ notifications   │
│ messages by 42  │     │ posts/topics     │      │ preferences     │
│ group memberships│    │ event RSVPs      │      │ for student 42  │
└─────────────────┘     └──────────────────┘      └─────────────────┘

Search Index            Media Service DB
┌─────────────────┐     ┌──────────────────┐
│ posts indexed   │     │ uploaded assets  │
│ profile indexed │     │ by student 42    │
└─────────────────┘     └──────────────────┘
```

When student 42 deletes their account, all of this must be cleaned up. In a monolith with a single relational database, you'd write `ON DELETE CASCADE` on foreign keys and the database handles it atomically. Here, we have 7 separate databases with no shared transaction scope. We need a design that:

1. Guarantees the deletion event is eventually received by every service
2. Tolerates services being temporarily offline at the time of deletion
3. Handles the event being delivered more than once without double-deleting or corrupting data
4. Gives us visibility into which services have completed their cleanup
5. Allows the user to be immediately blocked from logging in while cleanup completes in the background

---

## 2. Why We Cannot Use Distributed Transactions

A two-phase commit (2PC) across 7 services would work like this: a coordinator contacts every service, asks them to "prepare" (lock their rows), then issues a "commit" once all have confirmed. This sounds correct but introduces severe problems:

- **Availability collapses.** If any one of the 7 services is unavailable, the entire transaction blocks. We would need all 7 services healthy simultaneously just to delete an account.
- **Lock duration grows linearly.** Rows across all databases are locked for the full round-trip across all services. Under load this creates contention and slowdowns that are unrelated to deletion.
- **It couples services tightly.** The coordinator must know about all participants. Adding a new service (e.g., a future Analytics Service) means modifying the deletion transaction coordinator.

The CAP theorem is blunt here: in a distributed system, you can have consistency or availability, not both, in the presence of a network partition. We choose availability — we accept that cleanup across services will complete eventually rather than atomically.

---

## 3. The Solution: Event-Driven Saga with Guaranteed Delivery

A **Saga** is a sequence of local transactions, one per service, that are coordinated through events rather than a shared transaction. If a step fails, compensating actions bring the system back to a consistent state.

For account deletion, the saga looks like this:

```
Step 1: Auth Service          — deactivates account immediately (blocks login)
                              — publishes account.deletion.initiated to Kafka
                              ↓
Step 2 (parallel, async):
  Profile Service             — deletes profile, follow graph, blocks
  Feed Service                — deletes posts, reactions, comments, feed entries
  Chat Service                — anonymizes/deletes messages, removes from conversations
  Community Service           — removes memberships, deletes authored topics/events
  Notification Service        — deletes notification records and preferences
  Media Service               — schedules asset deletion from object storage
  Search Service              — removes profile and post index entries
                              ↓
Step 3: Each service publishes account.deletion.completed.{service-name}
                              ↓
Step 4: Auth Service (or a Saga Coordinator) tracks completions
        — when all services confirm: marks account as fully purged
        — if any service fails to confirm: retry mechanism kicks in
```

The key insight: **the Auth Service does not wait for downstream cleanup before returning success to the user.** The account is deactivated instantly (they cannot log in again). Data removal across other services follows asynchronously. From the student's perspective, their account is gone. From the system's perspective, orphaned data is cleaned up progressively.

---

## 4. The Outbox Pattern — Guaranteed Event Publishing

### The Problem with Naive Publishing

The most obvious approach is: Auth Service deletes the account in its DB, then publishes the Kafka event. But this has a critical flaw:

```
1. Auth Service: DELETE FROM students WHERE id = 42  ✓ (DB committed)
2. Auth Service: kafka.publish("account.deletion.initiated")  ✗ (Kafka unavailable)

Result: Account is deleted in Auth DB. No other service ever finds out.
Student's data remains in Feed, Chat, Community forever.
```

The reverse is equally dangerous:

```
1. Auth Service: kafka.publish("account.deletion.initiated")  ✓
2. Auth Service: DELETE FROM students WHERE id = 42  ✗ (DB crashes)

Result: Event fired, other services start deleting data.
But Auth DB still has the account. The student's posts are gone but they can still log in.
```

Neither ordering is safe. A database write and a network publish are two separate operations — they cannot be made atomic with a normal approach.

### The Outbox Pattern

The solution: **write the event to your own database in the same transaction as your business data change.** A separate process then reliably reads from this table and publishes to Kafka. The database becomes the source of truth for "events that need to be published."

```
Auth Service Database
┌─────────────────────────────────────────────────────────────────┐
│  students table               outbox table                      │
│  ────────────────             ─────────────────────────────────│
│  id: 42  → deleted            id: uuid-abc                      │
│  status: deactivated          event_type: account.deletion.     │
│                                           initiated             │
│  ← same DB transaction →      payload: { studentId: 42, ... }  │
│                               status: PENDING                   │
│                               created_at: 2026-02-27T10:00:00Z  │
└─────────────────────────────────────────────────────────────────┘
                                        ↓
                              Outbox Relay Process
                              (polls every 100ms or uses
                               DB change-data-capture)
                                        ↓
                              Publishes to Kafka
                                        ↓
                              Marks outbox row as PUBLISHED
```

**Why this works:** If the Auth Service crashes after writing to both tables but before the relay runs, the outbox row is still there when the service recovers. The relay will pick it up and publish. The event is guaranteed to eventually reach Kafka as long as the database is recoverable — which is a much stronger guarantee than "as long as Kafka is reachable at this exact moment."

**Relay implementation options:**
- **Polling:** A background process queries `SELECT * FROM outbox WHERE status = 'PENDING'` every few hundred milliseconds. Simple, adds minor DB load.
- **Change Data Capture (CDC) with Debezium:** Reads the database's write-ahead log (WAL) directly. Zero polling overhead, sub-second latency, does not add load to the primary DB. This is the preferred approach at scale.

Every service in ASTU Connect that publishes events uses this pattern — not just Auth. The outbox table is a standard part of every service's schema.

---

## 5. Account Deletion: Full Walkthrough

### Phase 1 — Immediate Deactivation

The student submits a delete request. The Auth Service handles it in a single database transaction:

```
Transaction (Auth DB):
  1. Set students.status = 'DEACTIVATING'  (blocks login immediately)
  2. Set students.deletion_requested_at = now()
  3. Revoke all active refresh tokens for this student
  4. INSERT INTO outbox:
       event_type  = 'account.deletion.initiated'
       payload     = {
                       studentId: 42,
                       requestedAt: "2026-02-27T10:00:00Z",
                       sagaId: "saga-uuid-xyz"   ← tracks this deletion end-to-end
                     }
       status      = PENDING
Transaction commits.
```

The API responds to the client: "Your account has been scheduled for deletion." Auth rejects any future login attempts for student 42 from this point forward.

### Phase 2 — Event Relay

Within seconds, the outbox relay picks up the pending row and publishes to Kafka:

```
Kafka Topic: auth.account.deletion.initiated
Partition:   studentId % num_partitions  (consistent hashing — all events for
                                          student 42 land on the same partition,
                                          preserving order)
Message:
  {
    "eventId":         "event-uuid-123",
    "sagaId":          "saga-uuid-xyz",
    "eventType":       "account.deletion.initiated",
    "occurredAt":      "2026-02-27T10:00:00Z",
    "producerService": "auth-service",
    "version":         "1",
    "payload": {
      "studentId":     42,
      "requestedAt":   "2026-02-27T10:00:00Z"
    }
  }
```

### Phase 3 — Parallel Cleanup Across Services

Every service that holds data for student 42 has a consumer in its own Kafka consumer group on this topic. They all process concurrently and independently.

Each service follows the same internal pattern:
1. Receive the event
2. Check idempotency (have we processed this `eventId` already?)
3. Perform the cleanup in its own local database
4. Publish a completion event via its own outbox
5. Store the `eventId` in a processed-events table to prevent re-processing

### Phase 4 — Completion Tracking

Each service publishes to a completion topic when done:

```
Kafka Topic: auth.account.deletion.completed

Messages:
  { sagaId: "saga-uuid-xyz", completedBy: "feed-service",        studentId: 42 }
  { sagaId: "saga-uuid-xyz", completedBy: "chat-service",        studentId: 42 }
  { sagaId: "saga-uuid-xyz", completedBy: "community-service",   studentId: 42 }
  { sagaId: "saga-uuid-xyz", completedBy: "profile-service",     studentId: 42 }
  { sagaId: "saga-uuid-xyz", completedBy: "notification-service",studentId: 42 }
  { sagaId: "saga-uuid-xyz", completedBy: "media-service",       studentId: 42 }
  { sagaId: "saga-uuid-xyz", completedBy: "search-service",      studentId: 42 }
```

The Auth Service (or a dedicated Saga Coordinator — see Section 8) consumes these and checks them off. When all 7 are received, it marks student 42 as `status: DELETED` in its own database. At this point, the account record can be fully purged or anonymized per data retention policy.

---

## 6. What Each Service Must Do on `account.deletion.initiated`

### Profile Service
- Delete the profile record for the student
- Delete all follow relationships where the student is the follower OR the followee
- Delete all block records involving the student
- The follow graph deletion may affect other students' follower counts — update those counts in the same transaction or emit a compensating event

### Feed Service
- Soft-delete all posts authored by the student (mark `deleted_by_account_removal = true`, set content to null)
  - Why soft-delete first: hard deletes may take time if the student had many posts; soft-delete is instant and immediately hides content
  - A background job then hard-deletes rows in batches
- Delete all reactions and comments authored by the student
- Delete the student's feed inbox from Redis
- Remove the student from all fan-out target lists

### Chat Service
- Remove the student from all conversation participant lists
- For direct conversations: archive the conversation (do not delete — the other participant's message history is theirs)
- For messages authored by the deleted student: anonymize the sender field (`[deleted user]`) rather than deleting the message rows
  - Deleting messages would create gaps in other participants' conversation history, which is a poor experience
- Delete presence state from Redis for this student
- Delete unread counts for this student

### Community Service
- Remove all community memberships for the student
- For communities the student created: transfer ownership to the oldest remaining moderator, or if none exists, to a platform admin account; do not delete the community itself (other members' content lives there)
- Soft-delete all forum topics and replies authored by the student (anonymize authorship)
- Cancel all event RSVPs for the student

### Notification Service
- Delete all notification records for the student
- Delete notification preferences for the student
- Any in-flight push notifications for this student should be discarded

### Media Service
- Fetch all asset records owned by the student
- Mark them as `pending_deletion`
- A background job issues delete calls to MinIO/S3 for each asset
- Once object storage confirms deletion, remove the asset metadata record
- Note: Media deletion is decoupled from the event because object storage operations are slow and rate-limited; batch processing is safer

### Search Service
- Remove the student's profile document from the users index
- Remove all post documents authored by the student from the posts index
- This can be done as a bulk delete query by `authorId`

---

## 7. What Happens When a Service Is Down

This is the central reliability question. Here is how Kafka and the consumer group model protect us.

### Kafka's Consumer Offset Model

Kafka does not delete a message once it is consumed. It retains messages for a configured duration (in our case, **14 days** for deletion-related topics). Each consumer group independently tracks a **read offset** — a pointer to the last message it successfully processed. A service that is offline simply stops advancing its offset. Its offset is not lost.

```
auth.account.deletion.initiated topic
Offset:  0    1    2    3    4    5
         ↑                        ↑
         feed-service             notification-service
         consumer offset          consumer offset
         (online, up to date)     (service was down,
                                   behind by 4 messages)
```

When the Notification Service comes back online, Kafka delivers all messages from its last committed offset forward. It will receive and process the `account.deletion.initiated` event for student 42 even though it was published hours or days earlier.

### The 14-Day Retention Window

14 days is intentional. A service in ASTU Connect is unlikely to be down for more than a few hours for maintenance. But in a worst case (infrastructure incident, prolonged outage), 14 days gives ample recovery window before any deletion events are at risk of expiring. If a service were somehow down for longer than that, it would need to be rebuilt from a backup — at which point a manual reconciliation process applies (see Section 12).

### Dead Letter Queue (DLQ)

If a consumer processes a message but encounters an unrecoverable error (e.g., the delete query fails due to a bug, not a transient outage), it should not indefinitely retry and block the partition. The flow is:

```
Service receives event
       ↓
Attempts cleanup
       ↓
  Success? → Commit offset → Done
       ↓
  Retryable error? (network timeout, DB overloaded)
  → Retry with exponential backoff (3 attempts: 1s, 5s, 30s)
       ↓
  Permanent error? (bug, invalid data)
  → Publish message to DLQ: auth.account.deletion.DLQ
  → Commit offset (do not block the queue)
  → Alert on-call engineer
```

The Dead Letter Queue is a separate Kafka topic. Messages landing here are never silently discarded — they trigger an alert. An engineer can inspect the failed message, fix the underlying bug, and replay the DLQ message manually or with a replay tool.

### Consistency Check on Recovery

When a service restarts after an outage, before it marks itself as healthy, it runs a **reconciliation check**:

1. Query its own outbox table for any deletion sagas it started handling but never published a completion event for
2. Reprocess those saga IDs
3. Only then accept new traffic

This ensures that a crash mid-cleanup does not leave a service in a permanently inconsistent state.

---

## 8. Saga Orchestration and Completion Tracking

There are two standard approaches to running a saga: **choreography** and **orchestration**. ASTU Connect uses a hybrid.

### Choreography (Used for Most Events)

In pure choreography, each service listens for events and reacts independently. There is no central coordinator. This is how most of our cross-service sync works (profile updates, new posts, follow events). It is simple and decoupled.

The weakness: there is no single place to ask "is this saga complete?" If one service silently fails to clean up, nobody notices.

### Orchestration (Used for Account Deletion)

For account deletion — because it is irreversible and must be auditable — we introduce a lightweight **Saga Coordinator**, which is a component that lives inside the Auth Service (not a separate service):

```
Auth Service
├── HTTP handlers (login, register, delete account...)
├── Domain logic
└── Saga Coordinator (deletion sagas)
    ├── deletion_sagas table:
    │     saga_id, student_id, initiated_at, status,
    │     feed_completed, chat_completed, profile_completed,
    │     community_completed, notification_completed,
    │     media_completed, search_completed
    │
    └── Consumes: auth.account.deletion.completed topic
        On each message: checks off the corresponding service
        When all 7 are checked: marks saga as COMPLETED
                                 marks student as DELETED
```

The `deletion_sagas` table is the source of truth for the state of every in-flight account deletion. At any time, an admin can query it:

```
saga_id         | student_id | status      | feed | chat | profile | community | notif | media | search
saga-uuid-xyz   | 42         | IN_PROGRESS | ✓    | ✓    |         | ✓         | ✓     |       | ✓
```

This immediately shows that the Profile Service and Media Service have not yet confirmed. An on-call engineer can investigate without guessing.

### Timeout and Escalation

The Saga Coordinator runs a scheduled job every 15 minutes that checks for sagas that have been `IN_PROGRESS` for more than 1 hour. For each such saga:

1. Identify which services have not confirmed
2. Re-publish the `account.deletion.initiated` event specifically for those services (targeted retry)
3. If still unresolved after 24 hours: escalate to an alert requiring manual intervention

This ensures that even if a completion event is lost (e.g., a service published it but Kafka delivery failed), the saga does not stall indefinitely.

---

## 9. Idempotency — Handling Duplicate Events

Kafka guarantees **at-least-once delivery** by default. This means a consumer may receive the same event more than once (e.g., if it processes a message but crashes before committing its offset). Every consumer must therefore be idempotent — processing the same event twice must produce the same result as processing it once.

### Processed Events Table

Every service maintains a `processed_events` table:

```
processed_events
────────────────
event_id     (UUID — the eventId from the event envelope)
event_type   (e.g., 'account.deletion.initiated')
processed_at (timestamp)
```

Before doing any work on an incoming event, the consumer does:

1. Check: `SELECT 1 FROM processed_events WHERE event_id = ?`
2. If found: this event was already handled — skip it, commit the offset, move on
3. If not found: process the event, then insert into `processed_events` in the same DB transaction

This table is cleaned up periodically — records older than 30 days are deleted, since Kafka topics for deletion events are retained for only 14 days, making duplicate delivery after 30 days impossible.

### Idempotent Cleanup Operations

Even without the processed events check, each cleanup operation should be written to be safe to run twice:

- Delete operations use `DELETE WHERE ... AND deleted_at IS NULL` or `IF EXISTS` semantics
- Soft deletes use `UPDATE ... SET deleted = true WHERE id = ? AND deleted = false`
- Insert operations for cleanup records use upsert (`INSERT ... ON CONFLICT DO NOTHING`)

Belt-and-suspenders: the processed_events table prevents double processing at the consumer level, and the idempotent queries prevent corruption at the data level.

---

## 10. Other Cross-Service Sync Scenarios

Account deletion is the most complex scenario, but the same patterns apply to other cross-service data changes.

### 10.1 Profile Name or Avatar Update

A student updates their display name. Their name is denormalized in:
- Feed Service (shown on posts)
- Chat Service (shown as conversation participant)
- Search Service (indexed for search)

**Approach:** The Profile Service publishes `user.profile.updated` with the new name and avatar URL. Consumers update their local denormalized copies.

**Consistency choice:** We accept stale display names for a short window. A post authored an hour ago may show the old name for up to a few minutes after the student renames themselves. This is acceptable — it is the same tradeoff every major social platform makes. We do not block the profile update waiting for all consumers to confirm.

**We do NOT retroactively update names on old messages.** If a student changes their name from "Biruk" to "Biruk T.", messages they sent six months ago will still show "Biruk T." after the update propagates. Historical accuracy of who sent the message matters; the exact name at send time does not.

### 10.2 Post Deletion

A student deletes a single post. The Feed Service owns posts. It must:
- Mark the post as deleted in its own DB
- Publish `feed.post.deleted` to Kafka

Consumers:
- **Search Service:** removes the post from the index
- **Notification Service:** any pending notifications about this post (e.g., "X reacted to your post") become stale — mark them as expired rather than deleting them

**Feed inboxes in Redis:** The deleted post's ID may still exist in Redis sorted sets (follower feed inboxes). We do not proactively remove it from every follower's inbox (that would require touching thousands of Redis keys). Instead, when the Feed Service assembles a timeline for display, it batch-fetches post data for inbox entries and filters out any that return a `deleted = true` flag. This is the tombstone pattern — the inbox entry is stale but harmless.

### 10.3 Community Deletion

A moderator deletes an entire community. The Community Service owns it. It must:
- Mark the community as deleted
- Publish `community.deleted` to Kafka

Consumers:
- **Feed Service:** removes community posts from member feed inboxes
- **Notification Service:** expires any pending community notifications
- **Search Service:** removes the community and its posts from indexes
- **Profile Service:** no action needed (memberships are owned by Community Service)

The same saga + outbox + idempotency pattern applies here.

### 10.4 Student Blocking Another Student

Student A blocks student B. Profile Service owns blocks. It publishes `user.blocked`.

Consumers:
- **Chat Service:** prevents new messages between A and B; does NOT delete existing conversation history (the history is still valid for context)
- **Feed Service:** filters B's content out of A's feed going forward; does NOT retroactively remove B's content from A's already-rendered timeline

This is a read-time filter, not a delete operation. Consumers update local block lists and apply them during content retrieval.

---

## 11. Data Consistency Guarantees by Operation

Not every operation needs the same consistency level. This table defines what we commit to for each category:

| Operation | Consistency Level | Max Acceptable Lag | Approach |
|---|---|---|---|
| Account deactivation (login blocked) | Immediate | 0ms | Synchronous DB write in Auth Service |
| Account data removal | Eventual | Up to 1 hour | Saga + Kafka fan-out |
| Post deletion (content hidden) | Near-immediate | < 30 seconds | Soft delete + tombstone filter |
| Post removal from search index | Eventual | Up to 5 minutes | Kafka → Search consumer |
| Profile name update propagation | Eventual | Up to 2 minutes | Kafka → consumer cache invalidation |
| Follow/unfollow reflected in feed | Eventual | Up to 1 minute | Kafka → Feed fan-out list update |
| Block enforcement in Chat | Near-immediate | < 30 seconds | Kafka → Chat local block cache |
| Community deletion | Eventual | Up to 30 minutes | Saga + Kafka fan-out |

"Eventual" means the system will arrive at a consistent state, but not necessarily synchronously. The lag ranges above are design targets, not hard guarantees — they depend on Kafka consumer throughput and service health.

---

## 12. Failure Scenarios and Mitigations

### Scenario A: Kafka Is Unavailable When Deletion Is Requested

The outbox pattern handles this. Auth Service writes to its own DB (always available). The outbox relay retries publishing to Kafka continuously until Kafka recovers. The deletion event publishes as soon as Kafka is back. No data is lost.

### Scenario B: A Consumer Service Is Down for Several Hours

Kafka retains the message. When the service recovers, it resumes from its last committed offset and processes all missed events. The saga coordinator will detect this service has not confirmed within 1 hour and re-publish a targeted retry event before the service even recovers, ensuring it processes the event promptly on startup.

### Scenario C: A Consumer Service Processes the Event but Crashes Before Committing Its Offset

Kafka re-delivers the event on the next poll (at-least-once). The idempotency check (processed_events table) detects the duplicate and skips re-processing. No duplicate deletions occur.

### Scenario D: A Consumer Service Has a Bug and Consistently Fails to Process the Event

After 3 retries (exponential backoff), the message is forwarded to the Dead Letter Queue. An alert fires. The event is not lost. An engineer fixes the bug, deploys the fix, and replays the DLQ message. The service processes it successfully.

### Scenario E: The Saga Coordinator Crashes Mid-Saga

The Coordinator reads from the `deletion_sagas` table on startup. Any saga in `IN_PROGRESS` state is resumed — it re-subscribes to the completion topic and continues tracking. Because completions are idempotent (checking off a box that is already checked is harmless), duplicate completion messages are safe.

### Scenario F: A Service Is Down for Longer Than Kafka's 14-Day Retention

This is an extreme edge case — an extended outage that outlasts message retention. The process in this case:

1. Restore the service from its most recent backup
2. Run a **reconciliation query** against the Auth Service's `deletion_sagas` table to identify all sagas that completed while this service was absent
3. For each unprocessed saga: the service fetches the list of student IDs that need cleanup and executes the cleanup directly, without needing the original Kafka event
4. Publish completion confirmations for each

This reconciliation capability is an explicit operational runbook, not automated code, because it is expected to be extremely rare.

### Scenario G: Partial Completion — Some Services Confirm, One Never Does

The Saga Coordinator's 24-hour escalation alert catches this. The DLQ captures the failed events. The student's account is visible as `DEACTIVATING` in admin tooling, flagging it for human review. The student cannot log in regardless — deactivation is immediate and does not depend on downstream cleanup.

---

## Summary: The Guarantees We Make

| Guarantee | Mechanism |
|---|---|
| Events are never lost even if Kafka is temporarily down | Outbox pattern — events live in the DB first |
| Events are eventually received even if a consumer is down | Kafka offset tracking — messages replay on recovery |
| Events processed exactly once (not double-applied) | Processed events table + idempotent operations |
| Deletion progress is always visible | deletion_sagas table in Auth Service |
| A stuck saga is never silently abandoned | Saga Coordinator timeout + escalation alerts |
| A permanently failing consumer does not block others | Dead Letter Queue per consumer |
| Account access is revoked instantly | Synchronous deactivation before any async saga begins |

The combination of the Outbox Pattern, Kafka's durable offset model, idempotent consumers, and the Saga Coordinator gives us a system where a cascade delete across 7 independent databases is reliable, auditable, and resilient to the kinds of partial failures that are routine in distributed systems.

---

*Relates to: `architecture01.md` — Section 6 (Inter-Service Communication), Section 8 (Event-Driven Design)*
