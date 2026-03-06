# ASTU Connect — Architecture One-Pager

## The Main Parts

The platform is split into **9 independent services**, each doing one job:

| Service | What it does |
|---|---|
| **API Gateway** | Front door — checks your login token, decides which service handles your request |
| **Auth** | Login, signup (ASTU email only), issues JWT tokens |
| **Profile** | Student info, who follows whom, who's blocked |
| **Feed** | Posts, likes, comments, your personalized timeline |
| **Chat** | DMs and group chats, real-time over WebSocket |
| **Community** | Clubs, department groups, events, forum threads |
| **Notification** | Push alerts, in-app badges, email alerts |
| **Media** | Image/file uploads, served via CDN |
| **Search** | Find posts, people, communities |

Each is its own deployable unit — if Chat goes down, Feed and Communities keep working.

---

## Where Data Lives

**Right tool for each job — no service shares a database with another.**

| Data | Stored in | Why |
|---|---|---|
| Accounts, profiles, communities, posts | **PostgreSQL** | Relational data, needs transactions |
| Chat messages | **Cassandra** | Millions of writes, simple reads — built for this |
| Feed inboxes, counters, who's-online, cache | **Redis** | In-memory = instant reads |
| Images & files | **MinIO / S3 + CDN** | Object storage, served at the edge |
| Search index | **Elasticsearch** | Full-text search |

---

## How They Talk

Two modes:

**1. Synchronous (request → wait → response)**
Client → Gateway → Service via **REST**. Service → Service via **gRPC** (rarely — only when one service *needs* an answer right now).

**2. Asynchronous (fire → forget)**
Everything else goes through **Kafka**. When something happens, the service publishes an event (`post.created`, `message.sent`, `user.followed`) and whoever cares listens.

```
Student creates a post
      ↓
Feed Service saves it → returns "OK" immediately
      ↓
Publishes post.created to Kafka
      ↓
┌─────────────┬──────────────┬─────────────┐
│ Fan-out     │ Notification │ Search      │
│ worker adds │ Service      │ Service     │
│ it to       │ alerts       │ indexes     │
│ follower    │ followers    │ it          │
│ inboxes     │              │             │
└─────────────┴──────────────┴─────────────┘
```

The user never waits for side effects. They post and move on.

---

## How It Stays Fast Under Load

Target: **~5,000 concurrent students** at peak (exam week, registration).

**1. Pre-compute feeds, don't build them on request**
When you post, a background worker pushes it into every follower's inbox (a Redis sorted set). When someone opens their feed, we just read their inbox — no joins, no aggregation, O(log N) lookup. For high-follower accounts (department pages), we pull at read time instead to avoid write explosions.

**2. Cache everything that doesn't change every second**
Profiles, community metadata, post content — all sit in Redis with short TTLs. Most reads never touch Postgres.

**3. Spread WebSocket connections across many Chat pods**
Each pod holds ~10K connections. Redis tracks who's on which pod. Messages between pods route via Kafka pub/sub.

**4. Let Cassandra eat the chat write volume**
Messages are append-only and partitioned by conversation — Cassandra scales this linearly by adding nodes.

**5. Auto-scale the stateless stuff**
Every service runs as multiple replicas behind Kubernetes. Traffic spikes → more pods spin up automatically.

**6. Keep big files off the app servers**
Uploads go directly from the client to object storage via pre-signed URLs. Downloads come from a CDN. The app never touches the bytes.

**7. Rate limit at the gateway**
Stops any single student (or bug) from flooding a service before it reaches the backend.

---

*Full spec: `architecture01.md`*
