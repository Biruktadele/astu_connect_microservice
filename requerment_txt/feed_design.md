# ASTU Connect — Feed Design: Fan-out Strategy and Scalability

**Question being answered:** Should we build a student's feed at the moment a post is created (fan-out on write), at the moment the student opens the app (fan-out on read), or something in between? How do we make sure the system does not collapse when a high-follower university account posts something and thousands of students get notified at once?

**Document Version:** 1.0
**Date:** 2026-02-27
**Relates to:** `architecture01.md` — Section 5.4 (Feed Service), Section 10 (Scalability)

---

## Table of Contents

1. [What the Feed Actually Is](#1-what-the-feed-actually-is)
2. [The Two Fundamental Approaches](#2-the-two-fundamental-approaches)
3. [Fan-out on Write — Deep Dive](#3-fan-out-on-write--deep-dive)
4. [Fan-out on Read — Deep Dive](#4-fan-out-on-read--deep-dive)
5. [The Problem Neither Approach Solves Alone](#5-the-problem-neither-approach-solves-alone)
6. [The ASTU Connect Solution: Hybrid Fan-out](#6-the-astu-connect-solution-hybrid-fan-out)
7. [The Celebrity Problem at ASTU — University Accounts](#7-the-celebrity-problem-at-astu--university-accounts)
8. [Keeping the Feed Fast Under Concurrent Load](#8-keeping-the-feed-fast-under-concurrent-load)
9. [What the Feed Looks Like When Assembled](#9-what-the-feed-looks-like-when-assembled)
10. [Feed Ranking](#10-feed-ranking)
11. [Tradeoff Summary](#11-tradeoff-summary)
12. [Recommendation and Phased Rollout](#12-recommendation-and-phased-rollout)

---

## 1. What the Feed Actually Is

Before comparing strategies, it helps to be precise about what the feed is at the data level.

When a student opens ASTU Connect and sees their timeline, they are looking at a **ranked, paginated list of post IDs** that were authored by accounts they follow, communities they belong to, and occasionally promoted/pinned content. The feed is not the posts themselves — it is a list of references to posts, ordered by score.

This distinction matters because it separates two independent problems:

- **The fan-out problem:** How and when do we build that list of references for each student?
- **The read problem:** Once we have the list, how do we efficiently fetch the actual post content?

Both problems need to be solved. Most of the strategy debate is about the first one.

---

## 2. The Two Fundamental Approaches

At the extremes, there are two strategies. Everything else is a point on the spectrum between them.

### Fan-out on Write (Push Model)

When a post is created, the system immediately computes which students should see it and writes a reference to the post into each of their personal feed inboxes.

```
Student A posts something
           ↓
System looks up all of A's followers (say, 200 students)
           ↓
Writes 200 "inbox entries" — one per follower
           ↓
Each follower's inbox now contains a pointer to this post
           ↓
When any follower opens their feed:
  → read their inbox (already computed)
  → fetch the actual post data for those IDs
  → display
```

The work happens at **write time**. Reading the feed is cheap because the heavy lifting is already done.

### Fan-out on Read (Pull Model)

When a student opens their feed, the system dynamically constructs it by looking at who they follow and fetching recent posts from each of them.

```
Student B opens their feed
           ↓
System fetches the list of everyone B follows
           ↓
For each followee, queries recent posts
           ↓
Merges and ranks all of those posts in real time
           ↓
Returns the assembled timeline to B
```

The work happens at **read time**. Writing a post is cheap because nothing happens beyond storing the post itself. Reading is expensive because the feed is assembled from scratch each time.

---

## 3. Fan-out on Write — Deep Dive

### How it works in detail

When student A (200 followers) creates a post, the Feed Service:

1. Saves the post to PostgreSQL — the canonical record
2. Publishes a `feed.post.created` event to Kafka
3. A **fan-out worker** (a Kafka consumer) picks up the event
4. The worker looks up student A's follower list from the Profile Service (or a local cache of it)
5. For each follower, the worker writes an entry into that follower's feed inbox stored in Redis as a sorted set:

```
Redis key:   feed:inbox:{followerId}
Type:        Sorted Set
Member:      {postId}
Score:       {ranking_score}   (typically a combination of timestamp + engagement boost)
Max size:    1,000 entries per inbox (oldest entries are evicted as new ones arrive)
```

When a follower opens their feed:
1. Fetch the top N entries from their sorted set inbox — a single Redis command, sub-millisecond
2. Bulk-fetch post data from PostgreSQL for those N post IDs — a single `SELECT WHERE id IN (...)` query
3. Return the assembled list

### Pros

- **Reads are extremely fast.** The feed inbox is a pre-sorted list in memory. There are no joins, no cross-account queries, no dynamic computation at read time.
- **Read latency is predictable.** Every student's feed read is the same operation regardless of how many people they follow.
- **The database does not spike on read.** Heavy read traffic does not translate to heavy DB load because Redis absorbs it.
- **Scales well with concurrent readers.** Thousands of students opening the app simultaneously each trigger only a Redis read and a small Postgres batch fetch.

### Cons

- **Write amplification.** One post creates N inbox writes, where N is the follower count. A student with 500 followers causes 500 Redis writes per post they publish. This is fine at normal scale.
- **High-follower accounts are dangerous.** If the ASTU Registrar account has 15,000 followers and posts an exam schedule, fan-out on write would trigger 15,000 Redis writes and 15,000 Kafka messages in a burst. This is the celebrity problem — covered in detail in Section 7.
- **Inboxes can go stale.** If a student unfollows someone, their posts remain in the inbox until naturally evicted by newer content. This is manageable with tombstone filtering (discussed in Section 9).
- **Storage cost.** Each follower has a Redis sorted set capped at 1,000 entries. For 15,000 students that is up to 15,000 sorted sets. Redis handles this comfortably — sorted sets are compact structures.

---

## 4. Fan-out on Read — Deep Dive

### How it works in detail

Student B follows 80 people. When they open their feed:

1. Fetch the 80 followee IDs from the follow graph
2. For each followee, query the posts table: `SELECT * FROM posts WHERE author_id IN (...) AND created_at > {cutoff} ORDER BY created_at DESC LIMIT 50`
3. Merge all results in memory
4. Rank and return the top N

### Pros

- **No write amplification.** A post is stored exactly once regardless of follower count. The ASTU Registrar posting to 15,000 followers costs the same as a first-year student posting to 3 followers.
- **Always fresh.** Because the feed is assembled on demand, it reflects the exact current state of who you follow and what they have posted.
- **Unfollows are instant.** If you unfollow someone, they disappear from your feed immediately on the next read — no stale inbox entries to clean up.
- **Simpler write path.** Post creation is just one DB insert and one Kafka event. No fan-out worker needed.

### Cons

- **Read latency is high and unpredictable.** A student following 300 people triggers a query touching 300 accounts' post data. This involves either a very wide `IN` clause or multiple sequential queries. Both options are slow at scale.
- **The database takes the hit at read time.** If 5,000 students open the app simultaneously at 8:00 AM, the database receives 5,000 complex read queries at the same moment. This is a read storm problem.
- **Latency grows with following count.** A student following 5 people gets a fast feed. A student following 300 people gets a slow feed. This is an inconsistent and poor user experience.
- **Caching is hard.** Because the feed is personalized and dynamic, it is difficult to cache effectively. Any cache entry is stale the moment someone you follow creates a new post.

---

## 5. The Problem Neither Approach Solves Alone

| Problem | Fan-out on Write | Fan-out on Read |
|---|---|---|
| Fast reads for normal students | Solves it | Does not solve it |
| Survivable writes from high-follower accounts | Does not solve it | Solves it |
| Read storm when thousands log in at once | Solves it | Makes it worse |
| Write storm from university-wide announcements | Makes it worse | Solves it |
| Feed freshness after unfollow | Requires cleanup | Naturally fresh |
| Implementation simplicity | More complex | Simpler |

No single strategy handles every scenario at ASTU's scale. The university context introduces a specific tension that makes this clearer than on a general-purpose social platform: **ASTU has institutional accounts (Registrar, Departments, Student Union) that nearly everyone follows, and these accounts post high-value, time-sensitive content (exam schedules, registration deadlines) at the exact moments when the entire student body is most likely to log in simultaneously.**

A pure fan-out on write fails when the Registrar posts the final exam schedule — a single post that must fan out to 15,000 inboxes instantaneously, on a day when all 15,000 students are anxiously checking the app.

A pure fan-out on read fails for the same scenario from the opposite direction — 15,000 students all requesting their feed at once, each triggering a complex query.

---

## 6. The ASTU Connect Solution: Hybrid Fan-out

The solution is to apply the right strategy per account type, not one strategy for all accounts.

### The Rule

```
If the post author has FEWER than 500 followers → Fan-out on Write
If the post author has 500 or MORE followers    → Fan-out on Read (pull at read time)
```

The 500-follower threshold is the initial value. It should be tuned based on observed write throughput and Redis memory usage once the platform is live.

### How It Works End-to-End

**Write path (fan-out on write, normal student):**

```
Student with 120 followers posts → Fan-out worker pushes to 120 Redis inboxes
```

**Write path (fan-out on read, high-follower account):**

```
Registrar account (15,000 followers) posts → Post saved to DB. That's it.
No fan-out worker runs. No inbox writes.
```

**Read path (assembling the feed for student B):**

```
Student B opens their feed
       ↓
Step 1: Fetch B's pre-computed inbox from Redis
        (contains posts from normal accounts B follows)
       ↓
Step 2: Identify which high-follower accounts B follows
        (B follows the Registrar, Dept of Software Engineering, Student Union)
       ↓
Step 3: Fetch recent posts from those high-follower accounts directly from PostgreSQL
        (a targeted query: WHERE author_id IN (registrar_id, dept_id, union_id)
         AND created_at > {cutoff})
       ↓
Step 4: Merge the Redis inbox results and the pulled posts
       ↓
Step 5: Re-rank the merged list
       ↓
Return to client
```

Step 3 is deliberately narrow. Student B may follow 3 high-follower accounts. That query touches 3 accounts — not 300. The cost is bounded and predictable.

### Why 500 as the Threshold

- A student with 499 followers causing 499 inbox writes is manageable — Kafka consumer workers process this asynchronously in the background without the posting student waiting.
- Above 500 followers, write amplification starts compounding. At 5,000 followers, a single post from a fan-out strategy floods a Kafka partition with 5,000 messages and triggers 5,000 Redis writes in a tight burst.
- Most students at ASTU will never reach 500 followers. The accounts that do (department pages, official university accounts) are a small, identifiable set where pull-on-read is entirely appropriate.

---

## 7. The Celebrity Problem at ASTU — University Accounts

This deserves its own section because it is the single biggest scalability risk in the feed system.

### Who the "Celebrities" Are

At ASTU, high-follower accounts are not influencers — they are institutional:

| Account Type | Estimated Followers | Posting Frequency | Post Impact |
|---|---|---|---|
| ASTU Registrar | ~15,000 (nearly all students) | Low — but critical timing | Exam schedules, deadlines |
| Department pages (per dept.) | 500–3,000 | Medium | Course updates, events |
| Student Union | ~8,000 | Medium | Campus events, elections |
| Library / Admin offices | ~2,000 | Low | Resource updates |

### The Thundering Herd Scenario

Consider this realistic scenario:

> It is the day before exam week. The Registrar posts the final exam schedule at 9:00 AM. Within 10 minutes, 12,000 students open the app to check the schedule.

Under pure fan-out on write:
- The Registrar's post triggers 15,000 inbox writes
- Those 15,000 writes compete with the 12,000 incoming read requests for Redis bandwidth
- Redis write latency spikes, which delays feed assembly for everyone

Under the hybrid model:
- The Registrar's post is saved to PostgreSQL. Nothing else happens at write time.
- When the 12,000 students read their feeds, each one makes a small targeted pull for Registrar posts
- Those are simple indexed reads on a small set of author IDs — PostgreSQL handles them easily, especially with a read replica and a short-TTL cache on the Registrar's recent posts

### Caching High-Follower Account Posts

Because high-follower accounts' posts are pulled at read time by many students, we apply a specific caching layer for them:

```
Redis key:    feed:hf-posts:{authorId}
Type:         List or Sorted Set
Content:      Last 50 post IDs from this high-follower author, pre-fetched
TTL:          60 seconds
Invalidation: On new post from this author (Kafka event triggers cache bust)
```

When student B's feed assembly step reaches "pull posts from high-follower accounts," it hits this Redis cache first. In the thundering herd scenario, 12,000 students all pull the Registrar's recent posts — but they all hit the same Redis cache entry, not PostgreSQL 12,000 times. PostgreSQL is queried at most once every 60 seconds for that author's recent posts, regardless of concurrent read volume.

This cache is populated proactively when a high-follower account posts — a background process writes the new post into the cache immediately after the post is saved to DB.

---

## 8. Keeping the Feed Fast Under Concurrent Load

Several mechanisms work together to keep feed reads fast when thousands of students are using the platform simultaneously.

### 8.1 Redis Sorted Sets for Inboxes

Each student's feed inbox is a Redis sorted set. Reading the top 20 items is an `ZREVRANGE` operation — O(log N + M) where N is the set size (capped at 1,000) and M is the number of items requested. Even with thousands of concurrent reads, Redis handles this at sub-millisecond latency per operation. Redis is single-threaded per node but processes commands at hundreds of thousands of operations per second.

### 8.2 Asynchronous Fan-out Workers

The fan-out workers that push post references into follower inboxes are Kafka consumers — they run asynchronously, completely decoupled from the student's post creation request. When student A posts:

1. Post is saved to PostgreSQL
2. Event is published to Kafka
3. API returns "201 Created" to student A immediately
4. Fan-out workers process the event in the background (typically within 1–3 seconds for a student with a few hundred followers)

Student A never waits for fan-out to complete. This means the feed is **eventually consistent** — a follower may not see the new post the instant it is created. They will see it within seconds. For a campus social platform, this is entirely acceptable.

### 8.3 Fan-out Worker Horizontal Scaling

Fan-out workers are independent Kafka consumer pods. They can be scaled horizontally by adding more replicas. The Kafka topic for post creation uses enough partitions (24, as defined in `architecture01.md`) that many workers can consume in parallel without blocking each other.

During a burst — many posts arriving at once — the Kafka topic absorbs the spike. Workers drain it at their own throughput rate. The queue grows temporarily, then empties. No messages are dropped. No service crashes.

### 8.4 Bounded Inbox Size

Each Redis feed inbox is capped at 1,000 entries. When a new entry is added and the inbox is full, the lowest-scored entry is evicted. This is a sliding window of the student's most relevant recent content.

Without this cap, a student who joined years ago and follows hundreds of accounts would have an inbox that grows without bound, making reads progressively slower. The cap ensures read performance stays constant.

### 8.5 Pagination with Cursors

The feed is never loaded all at once. Clients request pages of 20 posts. The cursor is the score of the last item on the current page — the next page query starts from there. This keeps individual requests lightweight regardless of how large the inbox is.

### 8.6 Read Replicas for Post Data Fetching

After the inbox provides the list of post IDs, the system bulk-fetches post content from PostgreSQL. This query hits a **read replica**, not the primary. Read replicas absorb all feed-related reads. The primary only handles writes (new posts, reactions, comments). This separation allows reads and writes to scale independently.

### 8.7 Post Data Caching

Frequently-read posts (recently created, trending, pinned announcements) are cached in Redis with a short TTL (30 seconds to 2 minutes depending on post age and engagement). The bulk-fetch step checks this cache first before querying PostgreSQL.

```
Feed assembly bulk-fetch:
For each post ID in the inbox page:
  1. Check Redis cache: GET post:data:{postId}
  2. Cache hit → use cached data
  3. Cache miss → add to list of DB IDs to fetch

Batch query PostgreSQL for cache-miss IDs
Populate cache for fetched posts
Return assembled list
```

In practice, during high-traffic periods, the most popular posts (e.g., the Registrar's exam schedule announcement) will be served entirely from cache for most students.

---

## 9. What the Feed Looks Like When Assembled

This section describes what actually happens when student B requests their feed, combining all the mechanisms above.

```
Student B requests GET /api/v1/feed?cursor=null&limit=20

Step 1 — Inbox read (Redis, sub-millisecond)
  ZREVRANGEBYSCORE feed:inbox:studentB +inf -inf LIMIT 0 50
  Returns: [postId_A, postId_C, postId_F, postId_G, ...]  (50 candidates, pre-scored)

Step 2 — High-follower pull (Redis cache → PostgreSQL read replica)
  B follows: Registrar, Dept of Software Engineering
  Check Redis: GET feed:hf-posts:registrar_id
  Check Redis: GET feed:hf-posts:dept_se_id
  Returns: [postId_R1, postId_R2, postId_D1]  (recent posts from institutional accounts)

Step 3 — Merge
  Combined candidate list: [postId_A, postId_R1, postId_C, postId_D1, postId_F, postId_G, postId_R2, ...]

Step 4 — Filter
  Remove any post IDs where:
    - post.deleted = true         (tombstone filtering)
    - post.author is in B's block list
    - post has already been seen in a prior page (cursor deduplication)

Step 5 — Bulk-fetch post data (Redis cache + PostgreSQL read replica)
  For remaining post IDs: fetch content, author display name, reaction counts, comment counts
  Most popular posts served from Redis cache, rest from DB

Step 6 — Rank
  Apply ranking score to the merged + filtered + fetched list
  Sort descending by score

Step 7 — Return top 20
  Cursor for next page = score of item 20
```

This entire sequence completes in well under 100ms under normal load. The Redis operations are sub-millisecond. The PostgreSQL bulk-fetch is a single indexed query. The merge and rank is an in-memory sort on at most ~53 items.

---

## 10. Feed Ranking

A purely chronological feed is the simplest implementation and is appropriate for Phase 1. A ranked feed, introduced in Phase 3, improves relevance. The ranking score for each feed item is a weighted formula applied at feed assembly time.

### Ranking Formula

```
score = recency_score
      + (relationship_strength × 0.3)
      + (engagement_velocity    × 0.2)
      + (content_type_boost     × 0.15)
      + (interaction_history    × 0.1)
```

**Recency score** is the primary driver — it is a decaying value based on post age. A post from 5 minutes ago scores far higher than one from 2 days ago. This ensures the feed feels live.

**Relationship strength** gives a small boost to posts from accounts the student regularly interacts with (comments on, reacts to). Calculated as a moving average of interaction events stored per (studentId, authorId) pair in Redis.

**Engagement velocity** boosts posts that are accumulating reactions and comments faster than average. This surfaces content that is resonating with the campus community. Computed from reaction counts stored as Redis counters.

**Content type boost** gives a fixed additive score to certain post types that are especially relevant in a university context:
- Exam announcements: +15
- Registration deadline notices: +15
- Event posts: +5
- Academic content tagged by a professor: +10
- General posts: 0

**Interaction history** gives a small boost to posts from authors whose content this student has previously engaged with.

### Important: Scoring Happens at Read Time, Not Write Time

Ranking scores are not pre-computed and stored. They are calculated in memory when the feed is assembled, using:
- The post's timestamp (already in the post record)
- Reaction counts from Redis counters (current, not at-write-time)
- Interaction history from a small Redis hash per student

This means the score of a post can change between page loads as it gains reactions. A post that was ranked 8th when you first loaded your feed might be ranked 2nd an hour later because it went viral on campus. This is intentional and desirable behavior.

---

## 11. Tradeoff Summary

| Dimension | Fan-out on Write | Fan-out on Read | Hybrid (Recommended) |
|---|---|---|---|
| Feed read latency | Very low (pre-computed) | High (computed on request) | Very low for normal accounts, low for institutional |
| Post write cost | High (N inbox writes) | Minimal (1 DB write) | Low for normal, minimal for high-follower |
| High-follower write storm | System at risk | No risk | No risk (pull-on-read for them) |
| Concurrent read storm | Well-protected | Vulnerable | Well-protected (Redis cache for HF posts) |
| Feed freshness | Slight delay (seconds) | Immediate | Slight delay for normal, immediate for HF posts |
| Stale inbox entries (after unfollow) | Yes, until eviction | No | Yes, for normal accounts (filtered at read time) |
| Implementation complexity | Medium | Low | Medium-high |
| Right for ASTU scale? | Partially | Partially | Yes |

---

## 12. Recommendation and Phased Rollout

### Phase 1 — Chronological Fan-out on Write (Simple Start)

Build the simplest correct version first. All accounts use fan-out on write. No ranking — purely chronological.

This is appropriate while the student count and follower graphs are small. It proves the feed infrastructure works, the Redis inboxes behave correctly, and Kafka fan-out workers process events reliably.

The threshold check (fan-out on write vs. pull) is present in the codebase from day one — it just always evaluates to "fan-out on write" because the threshold is set very high initially.

### Phase 2 — Enable the Hybrid Threshold

Once high-follower institutional accounts are active on the platform, lower the threshold to 500. Accounts above it automatically shift to pull-on-read. Introduce the Redis cache for high-follower account posts.

Monitor:
- Redis memory usage (should stay flat or grow slowly — inboxes are bounded)
- Feed read latency percentiles (p95, p99) — target under 150ms end-to-end
- Fan-out worker Kafka consumer lag — should drain within 5 seconds of a post event

### Phase 3 — Feed Ranking

Replace the chronological sort with the weighted ranking formula described in Section 10. Roll this out incrementally — serve ranked feeds to a percentage of students first and measure session engagement (do they read more posts? scroll further?) before full rollout.

At this phase, the threshold for high-follower accounts may need adjustment based on real traffic data. Start at 500 and tune upward or downward based on observed write amplification.

---

*Relates to: `architecture01.md` Sections 5.4, 10.2, 10.3 | `data_sync_plan.md` Section 10.2 (Post Deletion)*
