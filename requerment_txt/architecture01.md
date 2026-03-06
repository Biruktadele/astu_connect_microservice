# ASTU Connect — Microservices Architecture Design

**Platform:** Social platform for Addis Ababa Science and Technology University (ASTU) students
**Architecture Style:** Microservices with Clean Architecture per service
**Document Version:** 1.0
**Date:** 2026-02-27

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architectural Principles](#2-architectural-principles)
3. [Service Decomposition](#3-service-decomposition)
4. [Clean Architecture Per Service](#4-clean-architecture-per-service)
5. [Service Descriptions](#5-service-descriptions)
   - 5.1 [API Gateway](#51-api-gateway)
   - 5.2 [Identity & Auth Service](#52-identity--auth-service)
   - 5.3 [User Profile Service](#53-user-profile-service)
   - 5.4 [Feed Service](#54-feed-service)
   - 5.5 [Chat Service](#55-chat-service)
   - 5.6 [Community Service](#56-community-service)
   - 5.7 [Notification Service](#57-notification-service)
   - 5.8 [Media Service](#58-media-service)
   - 5.9 [Search Service](#59-search-service)
6. [Inter-Service Communication](#6-inter-service-communication)
7. [Data Architecture](#7-data-architecture)
8. [Event-Driven Design](#8-event-driven-design)
9. [Infrastructure & Deployment](#9-infrastructure--deployment)
10. [Scalability Strategy](#10-scalability-strategy)
11. [Security Architecture](#11-security-architecture)
12. [Observability & Monitoring](#12-observability--monitoring)
13. [Implementation Roadmap](#13-implementation-roadmap)

---

## 1. System Overview

ASTU Connect is a campus-bound social platform serving ASTU's student population. It provides three core product surfaces:

| Surface | Purpose |
|---|---|
| **Feed** | A ranked, personalized content timeline — posts, announcements, academic updates |
| **Chat** | Real-time direct messages and group conversations between students |
| **Community** | Interest-based or department-based groups with forums, events, and resources |

These three surfaces are intentionally separated into independent microservices. Each service owns its data, can be deployed independently, scales on its own axis, and can fail without bringing down the entire platform.

### High-Level System Diagram

```
                         ┌─────────────────────────────────────────┐
                         │              Client Layer                │
                         │  Web App (React)  │  Mobile App (React  │
                         │                   │  Native / Flutter)  │
                         └──────────────────┬──────────────────────┘
                                            │  HTTPS / WSS
                         ┌──────────────────▼──────────────────────┐
                         │              API Gateway                 │
                         │  (Auth verification, routing, rate-     │
                         │   limiting, WebSocket upgrade)          │
                         └──┬──────────┬──────────┬────────────────┘
                            │          │          │
           ┌────────────────▼─┐  ┌─────▼────┐  ┌─▼──────────┐
           │  Identity/Auth   │  │  Feed    │  │   Chat     │
           │  Service         │  │  Service │  │   Service  │
           └──────────────────┘  └──────────┘  └────────────┘
                            │          │          │
           ┌────────────────▼─┐  ┌─────▼────┐  ┌─▼──────────┐
           │  User Profile    │  │Community │  │Notification│
           │  Service         │  │ Service  │  │  Service   │
           └──────────────────┘  └──────────┘  └────────────┘
                            │          │          │
           ┌────────────────▼─┐  ┌─────▼────┐
           │  Media Service   │  │  Search  │
           │                  │  │  Service │
           └──────────────────┘  └──────────┘
                            │
           ┌────────────────▼──────────────────────────────┐
           │              Message Broker (Kafka)            │
           │  (Async event bus connecting all services)    │
           └───────────────────────────────────────────────┘
```

---

## 2. Architectural Principles

These principles govern every design decision in ASTU Connect.

### 2.1 Single Responsibility Per Service
Each microservice is responsible for one bounded context. The Feed Service does not manage user identities. The Chat Service does not decide what content appears in the feed. Boundaries are enforced at the API and data layer.

### 2.2 Database Per Service (Polyglot Persistence)
No two services share a database instance or schema. Each service selects the storage technology best suited to its access patterns. This eliminates the coupling that shared databases create.

### 2.3 API-First Design
Services communicate through well-defined contracts (REST or gRPC for synchronous, event schemas for asynchronous). Internal implementation is invisible to callers.

### 2.4 Eventual Consistency Over Distributed Transactions
Distributed ACID transactions across services create tight coupling and reduce availability. ASTU Connect accepts eventual consistency where real-time accuracy is not critical (e.g., like counts, follower counts). Services publish domain events and subscribers update their own local state.

### 2.5 Fail-Fast with Graceful Degradation
A service failure must not cascade. The API Gateway and client layer implement circuit breakers. If the Feed Service is unavailable, users can still access Chat and Communities.

### 2.6 Clean Architecture Within Each Service
Each service is internally layered: Domain → Application → Infrastructure → Interface. Business logic in the Domain and Application layers has zero dependency on frameworks, databases, or transport protocols.

---

## 3. Service Decomposition

The platform is decomposed into 9 services based on bounded context analysis.

```
┌─────────────────────────────────────────────────────────────────┐
│                      Service Inventory                          │
├────────────────────┬────────────────┬───────────────────────────┤
│ Service            │ Primary Domain │ Scale Axis                │
├────────────────────┼────────────────┼───────────────────────────┤
│ API Gateway        │ Routing/Auth   │ Horizontal (stateless)    │
│ Identity/Auth      │ AuthN & AuthZ  │ Horizontal + cache        │
│ User Profile       │ Student data   │ Horizontal + read replicas│
│ Feed               │ Content/posts  │ Horizontal + sharding     │
│ Chat               │ Messaging      │ Horizontal (WebSocket)    │
│ Community          │ Groups/events  │ Horizontal                │
│ Notification       │ Alerts/push    │ Horizontal + queue        │
│ Media              │ Files/CDN      │ CDN + object storage      │
│ Search             │ Discovery      │ Horizontal search cluster │
└────────────────────┴────────────────┴───────────────────────────┘
```

---

## 4. Clean Architecture Per Service

Every service follows Clean Architecture (also called Hexagonal or Ports-and-Adapters architecture). The dependency rule is strictly enforced: outer layers depend on inner layers, never the reverse.

```
┌──────────────────────────────────────────────────────────┐
│                   Interface Layer                        │
│  HTTP Controllers, gRPC handlers, WebSocket handlers,    │
│  Event consumers/producers, CLI commands                 │
│  ↓ depends on ↓                                         │
├──────────────────────────────────────────────────────────┤
│                 Application Layer                        │
│  Use cases / Application services                        │
│  Orchestrates domain objects, calls ports (interfaces)   │
│  ↓ depends on ↓                                         │
├──────────────────────────────────────────────────────────┤
│                   Domain Layer                           │
│  Entities, Value Objects, Aggregates, Domain Events,     │
│  Repository interfaces (ports), Domain Services          │
│  NO external dependencies                                │
├──────────────────────────────────────────────────────────┤
│                Infrastructure Layer                      │
│  Database adapters, HTTP clients, Message broker         │
│  adapters, cache adapters, third-party SDKs              │
│  Implements ports defined in Domain layer                │
└──────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

**Domain Layer**
- Contains the pure business rules of the bounded context.
- Entities carry identity (e.g., `Post`, `Message`, `Community`).
- Value Objects are immutable descriptors (e.g., `StudentId`, `PostContent`, `Timestamp`).
- Aggregates enforce invariants and are the transaction boundary.
- Repository interfaces declare how aggregates are persisted — no SQL, no ORM here.
- Domain Events describe facts that happened (e.g., `PostCreated`, `MessageSent`).

**Application Layer**
- Use cases (e.g., `CreatePostUseCase`, `SendMessageUseCase`) orchestrate domain objects.
- Does not contain business logic — delegates to domain entities.
- Depends only on domain interfaces (ports). Never directly imports infrastructure.
- Handles cross-cutting concerns like transaction management through ports.

**Infrastructure Layer**
- Provides concrete implementations of domain ports.
- Contains: ORM/query code, Redis cache clients, S3/MinIO clients, Kafka producers/consumers, HTTP clients for calling other services.
- Can be swapped without touching Domain or Application layers.

**Interface Layer**
- Translates external requests into application layer calls.
- Translates application responses into HTTP/gRPC/WS responses.
- Maps DTOs from/to domain objects. Domain objects never leak out of this boundary.

---

## 5. Service Descriptions

### 5.1 API Gateway

**Role:** Single entry point for all client traffic. Not a business service — it is pure infrastructure.

**Responsibilities:**
- TLS termination
- JWT validation (verifies token signature, expiry, issuer — does NOT authorize)
- Request routing to downstream services based on path prefix
- WebSocket connection upgrade and proxying to Chat Service
- Rate limiting per student identity (e.g., 100 requests/minute for normal endpoints, 5 requests/minute for auth endpoints)
- Request/response logging with correlation IDs
- Circuit breaker for each downstream service
- Response caching for public/read-heavy endpoints (e.g., trending feed)

**Does NOT do:** Business logic, data storage, service-to-service calls.

**Routing Table Example:**

```
/api/v1/auth/*        → Identity/Auth Service
/api/v1/users/*       → User Profile Service
/api/v1/feed/*        → Feed Service
/api/v1/chat/*        → Chat Service  (HTTP for history)
/ws/chat              → Chat Service  (WebSocket upgrade)
/api/v1/communities/* → Community Service
/api/v1/notifications/* → Notification Service
/api/v1/media/*       → Media Service
/api/v1/search/*      → Search Service
```

**Technology:** Kong Gateway or a custom lightweight gateway (e.g., using Go with gorilla/mux). Redis for rate-limit counters.

---

### 5.2 Identity & Auth Service

**Bounded Context:** Authentication, authorization, session management.

**Core Domain Concepts:**
- `Student` — a registered ASTU student account with verified university email
- `Credential` — hashed password associated with a student
- `Session` — a JWT pair (access token + refresh token)
- `Role` — student, moderator, admin
- `Permission` — fine-grained access rules (e.g., `community:create`, `post:delete_any`)

**Key Use Cases:**
- Register with ASTU email (`.edu.et` domain verification)
- Login → issue JWT access token (15-min TTL) + refresh token (7-day TTL, stored in DB)
- Refresh token rotation — old refresh token is invalidated on use
- Logout → revoke refresh token
- Forgot password → time-limited reset token via email
- Assign/revoke roles (admin use case)

**Data Storage:**
- **PostgreSQL** — student accounts, credentials (bcrypt), roles, refresh token records
- **Redis** — token blocklist (for immediate revocation of access tokens before expiry), short-lived OTP/reset codes

**Inter-Service Contract:**
Other services validate JWT signatures independently using the public key published by the Auth Service at a well-known JWKS endpoint. They do not call the Auth Service on every request (avoids a synchronous dependency for every API call). Only the API Gateway validates tokens at ingress.

**Events Published:**
- `student.registered` — triggers welcome notification, profile creation
- `student.deactivated` — triggers downstream cleanup

---

### 5.3 User Profile Service

**Bounded Context:** Student profile data, follow/friend graph.

**Core Domain Concepts:**
- `Profile` — displayable student data: name, bio, department, year, avatar URL
- `FollowRelationship` — directed edge from follower → followee
- `Block` — a student blocking another (suppresses content and messages)

**Key Use Cases:**
- Create/update profile
- Get profile by student ID
- Follow / unfollow a student
- Get followers / following list
- Block / unblock a student
- Get mutual follows (for "people you may know" suggestions)

**Data Storage:**
- **PostgreSQL** — profile records, block records
- **Neo4j (or PostgreSQL with adjacency list)** — follow graph. Neo4j is preferred if social graph queries (e.g., "2nd-degree connections", "mutual friends") become critical. For initial scale, PostgreSQL with a self-referencing `follows` table and proper indexing is sufficient.
- **Redis** — cached profile reads (profile data changes infrequently; a 60-second TTL cache reduces DB load significantly at high traffic)

**Events Published:**
- `user.followed` → consumed by Feed Service (to update followee's follower list for feed ranking)
- `user.unfollowed` → consumed by Feed Service
- `user.blocked` → consumed by Chat Service (to prevent messages), Feed Service (to hide content)
- `profile.updated` → consumed by Search Service (to re-index)

**API Shape (REST):**
```
GET    /users/:id                  — get profile
PUT    /users/:id                  — update profile
GET    /users/:id/followers        — list followers
GET    /users/:id/following        — list following
POST   /users/:id/follow           — follow user
DELETE /users/:id/follow           — unfollow user
POST   /users/:id/block            — block user
```

---

### 5.4 Feed Service

**Bounded Context:** Post creation, distribution, and ranked timeline retrieval.

**Core Domain Concepts:**
- `Post` — a unit of content authored by a student. Types: text, image, link, poll, announcement.
- `FeedItem` — a ranked entry in a student's personal timeline
- `Reaction` — a student's emoji reaction to a post (like, love, etc.)
- `Comment` — a reply thread on a post
- `FeedRankingScore` — computed weight used to order a student's timeline

**Key Use Cases:**
- Create a post
- Delete/edit a post
- React to a post
- Comment on a post
- Fetch personalized feed (paginated)
- Fetch public/global feed (for discovery)
- Pin a post (moderator use case)

**Feed Generation Strategy (Fan-out on Write + Pull Hybrid):**

A pure fan-out-on-write (push) model pre-computes and pushes every new post to the feed inbox of every follower. This is fast for reads but expensive for high-follower accounts. A pure pull model recomputes on every read, which is expensive for reads. ASTU Connect uses a hybrid:

- **Students with fewer than 500 followers** → fan-out on write. When they post, the Feed Service writes a `FeedItem` record to each follower's feed inbox (stored in Redis sorted set, scored by timestamp + relevance boost).
- **High-follower accounts (e.g., department admins, official pages)** → pull on read. Their posts are stored and fetched at read time, merged with the pre-computed feed inbox.
- **Feed inbox** is stored in Redis as a sorted set (`feed:{userId}`) with a max size of 1,000 items. On read, the inbox is fetched, then post data is bulk-fetched from the Posts DB.

**Data Storage:**
- **PostgreSQL** — canonical post records (source of truth), reactions, comments, post metadata
- **Redis** — feed inboxes (sorted sets), reaction counts (counters), trending post scores
- **Elasticsearch** — post content indexed for the Search Service (Feed Service publishes events; Search Service consumes and indexes)

**Ranking Factors for Feed:**
1. Recency (primary sort)
2. Relationship strength (posts from close connections score higher)
3. Engagement velocity (posts gaining reactions quickly get a boost)
4. Post type (announcements/academic posts get a relevance boost for ASTU context)
5. User interaction history (posts from accounts the student regularly engages with rank higher)

**Events Consumed:**
- `user.followed` / `user.unfollowed` — update fan-out target lists
- `user.blocked` — filter blocked users' posts from feed

**Events Published:**
- `post.created` → consumed by Notification Service (notify followers), Search Service (index)
- `post.deleted` → consumed by Search Service (de-index)
- `post.reacted` → consumed by Notification Service

---

### 5.5 Chat Service

**Bounded Context:** Real-time and asynchronous messaging between students.

**Core Domain Concepts:**
- `Conversation` — a container for messages, either a DirectConversation (2 participants) or GroupConversation (up to 200 participants)
- `Message` — a unit of content within a conversation. Types: text, image, file, reaction, system event.
- `Participant` — a member of a conversation with metadata (joined_at, last_read_at, is_admin)
- `ReadReceipt` — records when a participant last read messages in a conversation
- `DeliveryStatus` — sent → delivered → read

**Key Use Cases:**
- Start a direct conversation
- Create a group conversation
- Send a message
- Receive messages in real-time (WebSocket)
- Fetch conversation history (paginated, cursor-based)
- Mark messages as read
- Edit/delete a message
- Add/remove participants from group
- Send file/image attachments (delegates to Media Service for upload URL)

**Real-Time Architecture:**

```
Client A ──WebSocket── Chat Service Instance 1
                              │
                         Kafka Topic:
                       chat.messages
                              │
                    Chat Service Instance 2 ──WebSocket── Client B
```

WebSocket connections are maintained per Chat Service instance. When Client A sends a message to Client B, and they are connected to different service instances, the Chat Service publishes the message to a Kafka topic (`chat.messages.{conversationId}`). All instances subscribe and fan-out to their locally connected clients. This is the pub-sub fan-out pattern for WebSocket scaling.

For clients that are offline, messages are stored in the database and delivered when they reconnect or via the Notification Service (push notification).

**Connection State:** The Chat Service tracks which student is connected to which instance using Redis. Key: `chat:presence:{userId}` → value: instanceId. This allows the API Gateway to route reconnecting clients to the correct instance (sticky sessions optional) and allows the service to know whether a client is online for delivery status.

**Data Storage:**
- **Cassandra (or ScyllaDB)** — message storage. Chat has an extreme write-to-read ratio and a clear access pattern: "fetch last N messages for conversation X." Cassandra's wide-column model with `(conversationId, timestamp)` as the partition/clustering key is ideal. It avoids the read-amplification of relational joins and scales horizontally with consistent low-latency writes.
- **PostgreSQL** — conversation metadata, participants, group settings (low write volume, relational queries needed)
- **Redis** — presence tracking, unread counts, WebSocket instance routing

**Events Published:**
- `chat.message.sent` → consumed by Notification Service (push notification for offline users)
- `chat.group.created` → consumed by Notification Service

---

### 5.6 Community Service

**Bounded Context:** Student-created groups, department channels, forum discussions, events.

**Core Domain Concepts:**
- `Community` — a named group with a purpose, membership rules (open/invite-only/approval), and associated content spaces. Examples: "ASTU Chess Club", "Software Engineering '25", "Campus Events".
- `Member` — a student's membership in a community, with a role (member, moderator, admin)
- `Topic` — a forum thread within a community. Has posts (discussion replies).
- `Event` — a scheduled occurrence within a community (time, location, RSVP list)
- `Announcement` — a pinned high-priority post within a community, authored by moderators

**Key Use Cases:**
- Create a community
- Join / leave a community
- Post a topic / reply to a topic
- Create an event, RSVP to an event
- Promote/demote members (moderator)
- Approve join requests (private communities)
- Get recommended communities (based on department, interests)

**Data Storage:**
- **PostgreSQL** — communities, membership records, events, announcements. Relational integrity is important here (memberships, RSVP constraints, moderation logs).
- **Redis** — cached member count, hot community data (top communities by activity)
- **Elasticsearch** — communities indexed by name, description, tags for search

**Events Published:**
- `community.post.created` → consumed by Feed Service (distribute to community members' feeds), Notification Service
- `community.event.created` → consumed by Notification Service (notify members)
- `community.member.joined` → consumed by Notification Service, Feed Service
- `community.created` → consumed by Search Service (index)

**Relationship to Feed Service:**
When a student creates a post within a community, the Community Service emits a `community.post.created` event. The Feed Service consumes this and fans it out to all community members' feed inboxes — it does not call the Community Service directly. This keeps the two services decoupled.

---

### 5.7 Notification Service

**Bounded Context:** Delivering alerts to students across multiple channels.

**Core Domain Concepts:**
- `Notification` — a persisted alert for a student (type, message, link, read status, timestamp)
- `NotificationPreference` — a student's per-channel, per-type delivery settings
- `DeliveryChannel` — in-app, push (FCM/APNs), email

**Key Use Cases:**
- Receive domain events from all services and translate them into notifications
- Deliver in-app notifications (stored in DB, fetched by client on load and via WebSocket push)
- Deliver push notifications to mobile clients (via FCM for Android, APNs for iOS)
- Deliver email notifications (for critical events: password reset, account events)
- Mark notifications as read
- Get unread notification count
- Update notification preferences

**Architecture:**
The Notification Service is a pure consumer. It subscribes to Kafka topics from Feed, Chat, Community, and Auth services. It does not expose write APIs to other services — all input comes through the event bus. This makes it easy to add new notification triggers without modifying the source services.

**Data Storage:**
- **PostgreSQL** — persisted notification records, notification preferences
- **Redis** — unread notification count per user (fast increment/read for badge counts)
- **Message Queue (Kafka)** — event ingestion. A separate internal queue handles delivery retries for push/email channels.

**Push Delivery Flow:**
```
Kafka Event (e.g., post.reacted)
       ↓
Notification Service (consumer)
       ↓
Resolve target student IDs
       ↓
Check NotificationPreferences
       ↓
  ┌────┴────┐
  │         │
In-app    Push/Email
(store)   (FCM/APNs/SMTP)
```

---

### 5.8 Media Service

**Bounded Context:** Upload, storage, processing, and delivery of binary assets (images, files, videos).

**Core Domain Concepts:**
- `Asset` — a stored binary file with metadata (uploader, type, size, URL, processing status)
- `UploadSession` — a pre-signed, short-lived authorization to upload directly to object storage

**Key Use Cases:**
- Generate a pre-signed upload URL for direct client-to-storage upload (avoids routing large files through the application tier)
- Confirm an upload and trigger processing (image compression, thumbnail generation)
- Serve asset URLs (via CDN)
- Delete an asset (e.g., when a post is deleted)

**Upload Flow (Direct Upload to Object Storage):**
```
Client                Media Service              Object Storage (MinIO/S3)
  │                         │                            │
  │── POST /media/upload ──>│                            │
  │                         │─ generate pre-signed URL ─>│
  │<─── pre-signed URL ─────│                            │
  │                                                      │
  │────── PUT <file bytes> ──────────────────────────────>│
  │<──── 200 OK ────────────────────────────────────────│
  │                         │                            │
  │── POST /media/confirm ─>│                            │
  │                         │─ trigger async processing  │
  │<─── asset metadata ─────│                            │
```

This pattern prevents the application servers from becoming a bottleneck for large file uploads.

**Data Storage:**
- **MinIO (self-hosted) or S3-compatible storage** — binary file storage
- **PostgreSQL** — asset metadata records, processing status
- **CDN (Cloudflare or nginx with caching headers)** — serves static assets close to users

---

### 5.9 Search Service

**Bounded Context:** Full-text discovery of posts, users, communities, and events.

**Core Domain Concepts:**
- `SearchIndex` — a named index of documents for each entity type
- `SearchQuery` — a query with filters, facets, and pagination

**Key Use Cases:**
- Search posts by keyword
- Search users by name or department
- Search communities by name or tag
- Search events by title or date range
- Autocomplete for user/community names

**Architecture:**
The Search Service is a read-only query service for clients. It does not own any source-of-truth data. It maintains its indexes by consuming events from other services:

| Event Consumed | Action |
|---|---|
| `post.created` | Index post content |
| `post.deleted` | Remove from index |
| `profile.updated` | Re-index user profile |
| `community.created` | Index community |
| `community.updated` | Re-index community |
| `event.created` | Index event |

**Data Storage:**
- **Elasticsearch** — the search index. One index per entity type with appropriate analyzers (supports English and Amharic tokenization for bilingual content).

---

## 6. Inter-Service Communication

ASTU Connect uses two communication patterns, selected per use case.

### 6.1 Synchronous (REST / gRPC) — For Request/Response Flows

Used when a service needs an immediate answer to continue processing, and when the request originates from a client-facing interaction.

**When to use:**
- Client → API Gateway → Service: all user-facing reads and writes
- Service A needs data from Service B to complete a business operation (e.g., Feed Service needs current profile data to render a post)

**Technology choice:**
- **REST (JSON over HTTP)** for client-facing APIs (ease of tooling, browser compatibility)
- **gRPC (Protobuf over HTTP/2)** for internal service-to-service calls where performance and schema contracts matter (lower overhead, built-in schema, streaming support)

**Design rules:**
- Services must tolerate downstream failures (circuit breaker + fallback)
- Synchronous calls must never form cycles
- Services must NOT call each other for every request if the data changes infrequently — use a local cache with an event-invalidation pattern instead

### 6.2 Asynchronous (Kafka Events) — For Decoupled Side Effects

Used when one service needs to notify others of something that happened, without waiting for a response.

**When to use:**
- Side effects that don't block the primary user action (sending a notification, updating a search index, fan-out to feed inboxes)
- Cross-service data replication (profile name denormalized into the Post document)
- Any operation where eventual consistency is acceptable

**Technology:** Apache Kafka — chosen for durability, replay capability, consumer group semantics (multiple services can independently consume the same event), and high throughput suitable for campus-scale traffic.

**Topic Naming Convention:**
```
{service}.{entity}.{event_verb}

Examples:
  auth.student.registered
  feed.post.created
  feed.post.deleted
  chat.message.sent
  community.member.joined
  user.profile.updated
  user.followed
```

**Event Schema:**
Every event follows a common envelope:
```json
{
  "eventId": "uuid-v4",
  "eventType": "feed.post.created",
  "occurredAt": "2026-02-27T10:30:00Z",
  "producerService": "feed-service",
  "version": "1",
  "payload": { ... }
}
```

### 6.3 Communication Matrix

```
                 ┌──────────────────────────────────────────────────────────────┐
                 │                   Consumer                                   │
  Producer       │ Gateway  Auth  Profile  Feed  Chat  Community  Notif  Search │
  ─────────────────────────────────────────────────────────────────────────────
  Auth           │ JWKS     -     event    -     -     -          event  -      │
  Profile        │ -        -     -        event event -          -      event  │
  Feed           │ -        -     gRPC     -     -     -          event  event  │
  Chat           │ -        -     gRPC     -     -     -          event  -      │
  Community      │ -        -     gRPC     event -     -          event  event  │
  Notification   │ -        -     -        -     -     -          -      -      │
  Media          │ -        -     -        -     -     -          -      -      │
  └──────────────────────────────────────────────────────────────────────────────┘

  event = Kafka async event
  gRPC  = synchronous internal call
  JWKS  = public key endpoint (HTTP GET, cached)
```

---

## 7. Data Architecture

### 7.1 Storage Technology Assignments

| Service | Storage Technology | Justification |
|---|---|---|
| Identity/Auth | PostgreSQL + Redis | Relational integrity for accounts; Redis for token blocklist and OTPs |
| User Profile | PostgreSQL + Redis | Relational data; Redis for read cache |
| Feed | PostgreSQL + Redis | Posts in Postgres; feed inboxes and counters in Redis sorted sets |
| Chat | Cassandra + PostgreSQL + Redis | High-write messages in Cassandra; conversation metadata in Postgres; presence in Redis |
| Community | PostgreSQL + Redis | Relational memberships and events; Redis for hot counts |
| Notification | PostgreSQL + Redis | Persisted notifications in Postgres; unread counts in Redis |
| Media | MinIO/S3 + PostgreSQL | Binary files in object storage; metadata in Postgres |
| Search | Elasticsearch | Purpose-built for full-text search |

### 7.2 Key Data Flow: Post Creation End-to-End

```
1. Client sends POST /api/v1/feed/posts
2. API Gateway verifies JWT, routes to Feed Service
3. Feed Service:
   a. Validates request
   b. Creates Post aggregate in domain
   c. Persists to PostgreSQL (posts table)
   d. Publishes `feed.post.created` event to Kafka
   e. Returns 201 Created with post data to client
4. Kafka consumers (async, non-blocking to client):
   a. Feed Service (fan-out worker): writes FeedItems to follower feed inboxes in Redis
   b. Notification Service: creates notifications for followers, sends push
   c. Search Service: indexes post in Elasticsearch
```

### 7.3 Key Data Flow: Chat Message End-to-End

```
1. Client A sends message via WebSocket to Chat Service
2. Chat Service:
   a. Validates sender is a participant of the conversation
   b. Persists message to Cassandra
   c. Publishes `chat.message.sent` to Kafka
   d. Looks up Client B's presence in Redis
   e. If Client B is online on same instance: push directly via WebSocket
   f. If Client B is online on different instance: Kafka fan-out triggers push on that instance
3. Kafka consumer (Notification Service):
   a. If Client B is offline: send push notification via FCM/APNs
```

### 7.4 Denormalization Strategy

In a microservices system, joins across service databases are not possible. Data that is needed by multiple services is selectively denormalized:

| Data | Owner | Denormalized In | Sync Mechanism |
|---|---|---|---|
| Student display name | Profile Service | Feed posts, Chat messages (at write time) | Embed at creation time; accept stale for old content |
| Student avatar URL | Profile Service | Feed posts, Chat message sender info | Cache with TTL; event-driven invalidation on `profile.updated` |
| Community name | Community Service | Notification payloads | Embedded in event payload at publish time |
| Post author info | Feed Service | Search index | Consumed from `feed.post.created` event payload |

---

## 8. Event-Driven Design

### 8.1 Kafka Topic Architecture

```
Kafka Cluster
├── Topic: auth.student.registered        (partitions: 6)
├── Topic: auth.student.deactivated       (partitions: 3)
├── Topic: user.profile.updated           (partitions: 6)
├── Topic: user.followed                  (partitions: 12)
├── Topic: user.unfollowed                (partitions: 12)
├── Topic: user.blocked                   (partitions: 6)
├── Topic: feed.post.created              (partitions: 24)  ← high volume
├── Topic: feed.post.deleted              (partitions: 12)
├── Topic: feed.post.reacted              (partitions: 24)  ← high volume
├── Topic: chat.message.sent              (partitions: 48)  ← highest volume
├── Topic: chat.group.created             (partitions: 6)
├── Topic: community.created              (partitions: 6)
├── Topic: community.post.created         (partitions: 12)
├── Topic: community.member.joined        (partitions: 12)
└── Topic: community.event.created        (partitions: 6)
```

Partitions are set based on projected throughput. `chat.message.sent` has the most partitions because message volume is the highest and must support multiple parallel consumer instances.

### 8.2 Consumer Groups

Each consuming service has its own consumer group per topic it subscribes to. This ensures:
- Each service independently tracks its read offset
- A slow consumer (e.g., Search Service) does not block a fast consumer (e.g., Feed fan-out)
- Events can be replayed per consumer group independently

```
Topic: feed.post.created
├── Consumer Group: feed-fanout-worker     (Feed Service fan-out)
├── Consumer Group: notification-service
└── Consumer Group: search-indexer
```

### 8.3 Idempotency

Event consumers must be idempotent — processing the same event twice must not produce incorrect results. Strategies:
- Use `eventId` (UUID) as an idempotency key; consumers maintain a short-lived set of processed event IDs in Redis (TTL: 24 hours)
- Write operations use upsert semantics where possible
- Notification Service checks if a notification with the same `(studentId, eventId)` already exists before inserting

---

## 9. Infrastructure & Deployment

### 9.1 Container Orchestration

All services run as Docker containers orchestrated by **Kubernetes**. Each service has:
- A Kubernetes `Deployment` with multiple replicas
- A `Service` resource for internal DNS-based discovery
- A `HorizontalPodAutoscaler` (HPA) configured on CPU/RPS metrics

### 9.2 Namespace Layout

```
Kubernetes Cluster
├── Namespace: astu-gateway          (API Gateway)
├── Namespace: astu-auth             (Identity/Auth)
├── Namespace: astu-profile          (User Profile)
├── Namespace: astu-feed             (Feed)
├── Namespace: astu-chat             (Chat)
├── Namespace: astu-community        (Community)
├── Namespace: astu-notification     (Notification)
├── Namespace: astu-media            (Media)
├── Namespace: astu-search           (Search)
└── Namespace: astu-infra            (Kafka, Redis cluster, DBs)
```

### 9.3 Service Mesh

A service mesh (**Istio** or **Linkerd**) is deployed to provide:
- Mutual TLS (mTLS) for all service-to-service communication (zero-trust networking)
- Automatic retry and circuit breaker configuration via mesh policies (not hardcoded in application)
- Distributed tracing injection (adds trace headers automatically)
- Traffic policies (e.g., canary deployments, A/B testing of Feed ranking algorithms)

### 9.4 CI/CD Pipeline

```
Developer pushes code
        ↓
Git Branch → Pull Request
        ↓
CI Pipeline (GitHub Actions / GitLab CI):
  1. Unit tests (domain and application layer tests)
  2. Integration tests (using Docker Compose with test databases)
  3. Contract tests (Pact — verify producer/consumer event schemas match)
  4. Build Docker image
  5. Push to container registry (with commit SHA tag)
        ↓
CD Pipeline (ArgoCD — GitOps):
  1. Update Kubernetes manifests in infra repo with new image tag
  2. ArgoCD detects drift and syncs to cluster
  3. Rolling deployment (zero downtime)
  4. Automated smoke tests post-deploy
  5. Automatic rollback if health checks fail
```

### 9.5 Environment Strategy

| Environment | Purpose | Notes |
|---|---|---|
| Development | Local developer testing | Docker Compose with all services and dependencies |
| Staging | Pre-production integration | Mirrors production config; uses anonymized data |
| Production | Live ASTU student traffic | Kubernetes on bare-metal or cloud |

---

## 10. Scalability Strategy

### 10.1 Expected Load Profile

ASTU has approximately 15,000–20,000 students. Realistic concurrent active users during peak (e.g., exam announcements, registration period):
- **Concurrent users:** ~3,000–5,000
- **Feed reads:** ~10,000 requests/minute
- **Chat messages:** ~5,000 messages/minute
- **Notifications dispatched:** ~20,000/minute (fan-out multiplier)

### 10.2 Per-Service Scaling Strategy

**Feed Service:**
- Feed inbox reads are served entirely from Redis — O(log N) on a sorted set, horizontally scalable
- Post writes go to PostgreSQL; read replicas serve timeline assembly
- Fan-out workers (Kafka consumers) scale independently of the API-facing pods
- High-follower accounts use pull-on-read, capping write amplification

**Chat Service:**
- WebSocket connections are the primary constraint; each pod handles ~10,000 persistent connections
- Horizontal scaling of pods increases connection capacity linearly
- Cassandra scales horizontally for write throughput with consistent-hashing ring partitioning
- Redis Cluster for presence data (6-node minimum in production)

**Community Service:**
- Membership queries are the most frequent; read replicas on PostgreSQL handle this
- Community feed aggregation is offloaded to Kafka fan-out, not computed on read

**Search Service:**
- Elasticsearch cluster scales with additional data nodes
- Queries are read-only from the application perspective; index updates come from Kafka
- Query caching (Elasticsearch request cache) for common searches (e.g., "software engineering community")

### 10.3 Caching Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Caching Layers                         │
├──────────────┬──────────────────────────────────────────────┤
│ Layer        │ What is cached                              │
├──────────────┼──────────────────────────────────────────────┤
│ CDN          │ Static assets, media files, public API      │
│              │ responses (e.g., trending feed snapshot)    │
├──────────────┼──────────────────────────────────────────────┤
│ API Gateway  │ Public read endpoints (60s TTL)             │
│ response     │ e.g., GET /communities/trending             │
│ cache        │                                             │
├──────────────┼──────────────────────────────────────────────┤
│ Service-     │ Per-service application cache in Redis      │
│ level Redis  │ Profiles, post data, community metadata     │
│              │ Feed inboxes (sorted sets)                  │
│              │ Unread counts, presence state               │
├──────────────┼──────────────────────────────────────────────┤
│ DB read      │ PostgreSQL read replicas per service        │
│ replicas     │ Cassandra multi-AZ replication              │
└──────────────┴──────────────────────────────────────────────┘
```

### 10.4 Database Sharding

At ASTU's projected scale (20K students), sharding is not immediately necessary. However, the architecture is designed to allow it:

- **Feed Posts (PostgreSQL):** Partition by `created_at` (range partitioning by month). Old posts move to cold storage partitions.
- **Chat Messages (Cassandra):** Naturally partitioned by `conversationId`. New partitions are added by expanding the Cassandra ring.
- **Follow Graph:** If Neo4j is adopted, its native horizontal scaling applies. For PostgreSQL adjacency lists, shard by `follower_id % N`.

---

## 11. Security Architecture

### 11.1 Authentication Flow

```
1. Student logs in → Auth Service issues JWT (RS256, signed with private key)
2. JWT contains: { sub: studentId, roles: [...], exp: now+15min, iss: "astu-connect-auth" }
3. Client stores access token (memory) and refresh token (httpOnly cookie)
4. Every request includes Authorization: Bearer <access_token>
5. API Gateway validates JWT using Auth Service's public key (fetched from JWKS endpoint, cached)
6. Gateway injects verified studentId and roles as headers for downstream services
7. Downstream services trust these headers — they do NOT validate the JWT again
```

### 11.2 Authorization

- **Coarse-grained (Gateway level):** Certain routes require specific roles (e.g., admin routes require `role: admin`)
- **Fine-grained (Service level):** Business rules are enforced in the Application layer of each service. Examples:
  - Feed Service: only the post author can delete their own post (unless requester has `role: moderator`)
  - Community Service: only community admins can remove members
  - Chat Service: only conversation participants can read messages

### 11.3 ASTU-Specific Access Control

- Registration requires a valid ASTU email (`@astu.edu.et`). The Auth Service verifies this via an email verification flow.
- This prevents non-students from creating accounts, keeping the platform campus-bounded.
- Future: integration with ASTU's student information system (SIS) for automatic account provisioning/deprovisioning when students graduate or withdraw.

### 11.4 Data Security

- All data in transit: TLS 1.3 minimum (enforced at API Gateway and service mesh mTLS)
- All data at rest: database-level encryption for PostgreSQL and Cassandra
- Media files: stored with server-side encryption in MinIO/S3
- Passwords: bcrypt with cost factor 12 (never stored plaintext)
- PII isolation: Student profile data (name, department, email) is owned exclusively by the Profile Service. Other services store only `studentId`. Denormalized display names are considered non-sensitive.

### 11.5 Rate Limiting

```
Endpoint Category          │ Limit
───────────────────────────┼────────────────────────────
POST /auth/login           │ 5 requests/min per IP
POST /auth/register        │ 3 requests/min per IP
POST /feed/posts           │ 20 requests/min per student
POST /chat/messages        │ 60 messages/min per student
GET  /feed                 │ 60 requests/min per student
GET  /search               │ 30 requests/min per student
```

Rate limit counters are stored in Redis with a sliding window algorithm.

---

## 12. Observability & Monitoring

### 12.1 Three Pillars

**Logs**
- All services emit structured JSON logs (key-value pairs, not free-text)
- Every log entry includes: `service`, `traceId`, `spanId`, `studentId` (if authenticated), `level`, `message`, `timestamp`
- Centralized log aggregation: Loki (lightweight) or Elasticsearch
- Log visualization: Grafana

**Metrics**
- Every service exposes a `/metrics` endpoint in Prometheus format
- Key metrics per service:
  - HTTP request rate, latency (p50/p95/p99), error rate (RED metrics)
  - Business metrics: posts created/min, messages sent/min, active WebSocket connections
  - Infrastructure metrics: DB connection pool utilization, Redis hit/miss ratio, Kafka consumer lag
- Metrics collection: Prometheus
- Dashboards: Grafana

**Traces**
- Distributed tracing with OpenTelemetry (OTEL SDK in each service)
- Trace context propagated via HTTP headers (`traceparent`, `tracestate`)
- Service mesh (Istio/Linkerd) injects trace headers automatically
- Trace backend: Jaeger (self-hosted) or Tempo
- Enables root-cause analysis of slow or failed requests across service boundaries

### 12.2 Alerting

| Alert | Condition | Severity |
|---|---|---|
| High error rate | >1% of requests return 5xx for >2 min | Critical |
| Slow feed latency | p95 latency > 500ms for >5 min | Warning |
| Kafka consumer lag | Consumer group lag > 10,000 messages | Warning |
| WebSocket connection drop | Active connections drop >20% in 1 min | Critical |
| DB connection exhaustion | Connection pool >90% utilized | Warning |
| Auth service down | Health check failing | Critical |

### 12.3 Health Checks

Every service exposes:
- `GET /health/live` — liveness probe (is the process running?)
- `GET /health/ready` — readiness probe (is the service ready to serve traffic? DB connected? Cache connected?)

Kubernetes uses these probes to route traffic only to healthy pods and restart unhealthy ones.

---

## 13. Implementation Roadmap

The platform is built in three phases, each delivering functional value while progressively adding scale and features.

### Phase 1 — Core Foundation

**Goal:** A functional ASTU Connect with authentication, basic feed, and profile management.

**Services to build:** API Gateway, Identity/Auth Service, User Profile Service, Feed Service (basic, no fan-out), Media Service

**Infrastructure:** PostgreSQL per service, Redis (single instance), basic Kafka cluster (3 brokers), Docker Compose for local development, Kubernetes for staging/production

**Key Deliverables:**
- Student registration with ASTU email verification
- Login and JWT-based auth
- Create/view posts (chronological feed, no ranking)
- Follow other students
- Upload images to posts
- Basic profile pages

---

### Phase 2 — Communication & Community

**Goal:** Add real-time chat and community features.

**Services to build:** Chat Service, Community Service, Notification Service

**Infrastructure additions:** Cassandra cluster (3 nodes), WebSocket support at Gateway, FCM/APNs push integration, Search Service (Elasticsearch)

**Key Deliverables:**
- Direct and group messaging with real-time delivery
- Community creation, membership, forum topics
- Events within communities
- In-app and push notifications
- Full-text search for posts, users, communities

---

### Phase 3 — Scale & Intelligence

**Goal:** Production hardening, feed ranking, and performance optimization.

**Additions:**
- Feed ranking algorithm (replace chronological with scored ranking)
- Fan-out optimization (hybrid push/pull based on follower count)
- Redis Cluster (replace single Redis instance)
- Cassandra expansion for chat message volume
- Service mesh deployment (Istio/Linkerd) for mTLS and observability
- Comprehensive monitoring dashboards and alerting
- Content moderation hooks (flagging system, moderator tools in Community Service)
- Rate limiting refinement based on real traffic data
- CDN integration for media assets

---

## Appendix: Service Boundary Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Service          │ Owns                    │ Does NOT own              │
├───────────────────┼─────────────────────────┼───────────────────────────┤
│ Identity/Auth     │ Credentials, sessions   │ Profile data, content     │
│ User Profile      │ Student info, follows   │ Auth tokens, content      │
│ Feed              │ Posts, reactions,       │ User identity, chat       │
│                   │ feed inboxes            │ messages, memberships     │
│ Chat              │ Conversations,          │ Posts, communities,       │
│                   │ messages, presence      │ user profiles             │
│ Community         │ Groups, memberships,    │ Direct messages, global   │
│                   │ events, topics          │ feed, user identity       │
│ Notification      │ Notification records,   │ Source data of any kind   │
│                   │ delivery preferences    │                           │
│ Media             │ File storage, CDN URLs  │ Business context of files │
│ Search            │ Search indexes          │ Source-of-truth data      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

*Document authored for ASTU Connect backend architecture planning. This is a living document — revisit section 10 (Scalability) and section 13 (Roadmap) as actual traffic data becomes available.*
