================================================================================
ASTU CONNECT — THE BASICS EXPLAINED
A plain-language walkthrough of how the platform works
================================================================================

This document answers four questions:
  1. What are the main parts of the system?
  2. Where do we store our data?
  3. How do the pieces talk to each other?
  4. How do we keep it fast?

No jargon where we can avoid it. Every technical term is explained the
first time it appears.

--------------------------------------------------------------------------------
PART 1 — THE MAIN PARTS OF THE SYSTEM
--------------------------------------------------------------------------------

Think of ASTU Connect as a small city. Instead of one giant building
that does everything, we have several smaller buildings, each with one
job. If one building gets crowded, we build a copy of it next door.
If one catches fire, the others keep working.

These "buildings" are called SERVICES. Here are ours:

  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │   📱 STUDENT'S PHONE / LAPTOP                                   │
  │                    │                                            │
  │                    ▼                                            │
  │   ┌──────────────────────────────────────┐                      │
  │   │          API GATEWAY                 │                      │
  │   │  "The front desk" — checks who you   │                      │
  │   │  are, then sends you to the right    │                      │
  │   │  service. Also blocks spammers.      │                      │
  │   └──────────────┬───────────────────────┘                      │
  │                  │                                              │
  │      ┌───────────┼────────────┐                                 │
  │      ▼           ▼            ▼                                 │
  │  ┌────────┐  ┌────────┐  ┌───────────┐                          │
  │  │  FEED  │  │  CHAT  │  │ COMMUNITY │                          │
  │  └────────┘  └────────┘  └───────────┘                          │
  │                                                                 │
  │  Helpers used by all three:                                     │
  │  ┌──────────┐  ┌──────────────┐  ┌───────┐  ┌────────┐          │
  │  │ IDENTITY │  │ NOTIFICATION │  │ MEDIA │  │ SEARCH │          │
  │  └──────────┘  └──────────────┘  └───────┘  └────────┘          │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

THE THREE CORE SERVICES

  FEED SERVICE — everything about posts
    What it does: create posts, add comments, like/react, build your
                  home timeline (the scrolling list of posts you see
                  when you open the app).
    Analogy:      the campus bulletin board.

  CHAT SERVICE — everything about messaging
    What it does: 1-on-1 chats, group chats, "is typing…", online
                  status, read receipts.
    Analogy:      the campus phone system.

  COMMUNITY SERVICE — everything about groups
    What it does: create communities (CS Department, Drama Club,
                  Dorm Block C), join/leave, assign admins and
                  moderators, post inside a community, remove bad
                  posts.
    Analogy:      the student clubs office.

THE HELPER SERVICES

  IDENTITY — verifies you're a real ASTU student, gives you a login
             token, stores who follows whom.
  NOTIFICATION — sends push notifications and emails ("Abebe liked
                 your post", "New message from Hana").
  MEDIA — handles photo and video uploads. Files go to cloud storage,
          not into our databases.
  SEARCH — lets you search posts, people, and communities.

WHY SPLIT IT UP LIKE THIS?

  • Each team can work on one service without stepping on another
    team's code.
  • If chat gets 10× busier than feed, we scale only chat. We don't
    pay to scale everything.
  • A bug in Community can't crash Chat — they're separate programs
    running in separate containers.

INSIDE EACH SERVICE: THE "CLEAN ARCHITECTURE" ONION

  Every service is built in layers, like an onion. The center never
  changes. The outside is easy to swap.

      ┌──────────────────────────────────────────────┐
      │  OUTSIDE: Web handlers, database drivers     │  ← easy to swap
      │  ┌────────────────────────────────────────┐  │
      │  │  MIDDLE: Use cases (CreatePost,        │  │
      │  │          SendMessage, JoinCommunity)   │  │
      │  │  ┌──────────────────────────────────┐  │  │
      │  │  │  CENTER: Business rules          │  │  │  ← never changes
      │  │  │  (Post, Message, Community —     │  │  │
      │  │  │   what they ARE and what they    │  │  │
      │  │  │   can do)                        │  │  │
      │  │  └──────────────────────────────────┘  │  │
      │  └────────────────────────────────────────┘  │
      └──────────────────────────────────────────────┘

  The center (business rules) has ZERO knowledge of databases,
  HTTP, or Kafka. It's pure logic: "a post must have an author",
  "you can't join a community you're banned from", "a message
  can't be empty".

  The outside layer is where we plug in the actual database, the
  actual web framework, the actual message queue. If we decide to
  switch from Postgres to a different database, we rewrite ONLY the
  outside layer. The business rules stay untouched.

  This is why it's maintainable: the important logic is protected
  from infrastructure churn.

--------------------------------------------------------------------------------
PART 2 — WHERE WE STORE THE DATA
--------------------------------------------------------------------------------

THE GOLDEN RULE: EACH SERVICE OWNS ITS OWN DATABASE.

  No service is allowed to reach into another service's database.
  Ever. If Feed needs to know a user's name, it either:
    (a) asks the Identity service over the network, or
    (b) keeps its own local copy that gets updated automatically.

  Why so strict? Because shared databases become a tangled mess.
  Once two services share tables, you can't change one without
  breaking the other. Separate databases keep services truly
  independent.

WE USE DIFFERENT DATABASES FOR DIFFERENT JOBS

  This is called "polyglot persistence" — a fancy way of saying
  "use the right tool for each job instead of forcing one tool to
  do everything".

  ┌─────────────┬──────────────────┬──────────────────────────────┐
  │   SERVICE   │   DATABASE       │   WHY THIS ONE               │
  ├─────────────┼──────────────────┼──────────────────────────────┤
  │             │                  │                              │
  │   FEED      │   PostgreSQL     │  Posts & comments are        │
  │             │   (main store)   │  relational — a comment      │
  │             │                  │  belongs to a post, a post   │
  │             │                  │  has many reactions.         │
  │             │                  │  Postgres is rock-solid for  │
  │             │                  │  this.                       │
  │             │                  │                              │
  │             │   + Redis        │  Your home timeline is just  │
  │             │   (timelines)    │  a sorted list of post IDs.  │
  │             │                  │  Redis keeps this in MEMORY  │
  │             │                  │  so reading your feed is     │
  │             │                  │  instant. No disk access.    │
  │             │                  │                              │
  ├─────────────┼──────────────────┼──────────────────────────────┤
  │             │                  │                              │
  │   CHAT      │   Cassandra      │  Chat history is enormous    │
  │             │   (messages)     │  and append-only (you add    │
  │             │                  │  messages, you rarely edit   │
  │             │                  │  them). Cassandra is built   │
  │             │                  │  for exactly this: billions  │
  │             │                  │  of time-ordered rows,       │
  │             │                  │  spread across many machines,│
  │             │                  │  fast writes, fast reads by  │
  │             │                  │  conversation.               │
  │             │                  │                              │
  │             │   + Redis        │  "Is Abebe online?" and      │
  │             │   (presence)     │  "Who's typing?" — these     │
  │             │                  │  change every few seconds    │
  │             │                  │  and don't need to survive   │
  │             │                  │  a restart. Perfect for      │
  │             │                  │  Redis with a short expiry.  │
  │             │                  │                              │
  ├─────────────┼──────────────────┼──────────────────────────────┤
  │             │                  │                              │
  │ COMMUNITY   │   PostgreSQL     │  Communities have rules and  │
  │             │                  │  relationships: members have │
  │             │                  │  roles, roles have           │
  │             │                  │  permissions, moderation     │
  │             │                  │  actions reference users and │
  │             │                  │  posts. Classic relational   │
  │             │                  │  data. Postgres handles it   │
  │             │                  │  well and the write volume   │
  │             │                  │  is moderate.                │
  │             │                  │                              │
  │             │   + Redis        │  "Is user X a member of      │
  │             │   (cache)        │  community Y?" gets asked    │
  │             │                  │  constantly. Cache the       │
  │             │                  │  answer.                     │
  │             │                  │                              │
  └─────────────┴──────────────────┴──────────────────────────────┘

SHARED STORAGE (used by everyone, owned by no one)

  • OBJECT STORAGE (S3 or MinIO)
    All photos and videos go here. Databases only store the
    ADDRESS of the file, never the file itself. Databases are
    terrible at storing large binary blobs; object storage is
    built for it.

  • ELASTICSEARCH
    The search index. When you type in the search bar, this is
    what answers. It's kept up to date automatically by
    listening to events (see Part 3).

  • KAFKA
    The "event log" — a durable record of everything that
    happens. More on this in Part 3.

--------------------------------------------------------------------------------
PART 3 — HOW THE PIECES TALK TO EACH OTHER
--------------------------------------------------------------------------------

Two ways services communicate. We use both, for different reasons.

── WAY 1: DIRECT CALL (synchronous) ────────────────────────────────

  Like a phone call. Service A calls Service B, waits for an
  answer, then continues.

  When we use it:
    • A student tries to create a community. Before allowing it,
      Community Service calls Identity Service: "is this a real
      ASTU student?" It needs the answer RIGHT NOW before
      proceeding.

  When we AVOID it:
    • Anything that doesn't need an immediate answer.

  Why avoid it? Because if Service B is slow or down, Service A
  is stuck waiting. One slow service can make the whole app feel
  slow. So we keep direct calls to a minimum and always add:
    - a timeout (give up after 200ms)
    - a fallback (if Identity is down, use our local cached copy
      of the user's info instead of failing)

── WAY 2: EVENTS THROUGH KAFKA (asynchronous) ──────────────────────

  Like a bulletin board. Service A pins a note: "Hey everyone, a
  post was just created." Then Service A walks away — it doesn't
  wait. Any service that cares reads the note later and reacts.

  This is our DEFAULT. It's how most communication happens.

  HOW IT WORKS IN PRACTICE — Example: Tigist creates a post

    Step 1: Tigist taps "Post" on her phone
    Step 2: Request hits the API Gateway → routed to Feed Service
    Step 3: Feed Service runs the CreatePost use case:
              - validates the post (not empty, not too long)
              - saves it to Postgres
              - pins a note to Kafka: "post.created — postId 123,
                author tigist, timestamp now"
    Step 4: Feed Service replies to Tigist: "Done!" (fast, ~50ms)

    Meanwhile, in the background, other services read the note:

      → FAN-OUT WORKER reads it and thinks: "Tigist has 200
        followers. Let me add post 123 to each of their
        timelines in Redis." (This is why followers see the
        post in their feed.)

      → NOTIFICATION SERVICE reads it and thinks: "Tigist
        tagged @bereket in this post. Send Bereket a push
        notification."

      → SEARCH SERVICE reads it and thinks: "Index this post's
        text so it shows up in search results."

    Tigist didn't wait for any of this. Her "Post" button
    returned in 50ms. The background work happens over the
    next 1-2 seconds, invisibly.

  ANOTHER EXAMPLE — Dawit joins the "CS Department" community

    Step 1: Dawit taps "Join"
    Step 2: Community Service validates (not banned, not at
            capacity) → saves membership to Postgres → pins a
            note to Kafka: "community.member.joined — user
            dawit, community cs-dept"
    Step 3: Reply to Dawit: "Welcome!" (fast)

    In the background:
      → CHAT SERVICE reads the note: "Dawit joined cs-dept.
        Add him to the CS Department group chat."
      → FEED SERVICE reads the note: "Dawit joined cs-dept.
        Backfill the last 20 CS Department posts into his
        home timeline so he sees activity immediately."

  WHY THIS IS POWERFUL

    • Feed Service doesn't know or care that Chat, Search, and
      Notification exist. It just announces what happened.
      Tomorrow we could add an Analytics Service that also
      listens — and we wouldn't change a single line in Feed.

    • If Notification Service crashes for an hour, posts still
      work. The notes pile up in Kafka. When Notification comes
      back, it catches up. Nothing is lost.

    • Each service moves at its own pace. Fast services aren't
      slowed down by slow ones.

--------------------------------------------------------------------------------
PART 4 — HOW WE KEEP IT FAST
--------------------------------------------------------------------------------

Speed comes from five techniques. We use all of them together.

── TECHNIQUE 1: RUN MANY COPIES ────────────────────────────────────

  Feed Service isn't one program on one machine. It's 5 (or 10,
  or 50) identical copies running in parallel. The API Gateway
  spreads requests across them.

  Busy exam week? The system notices requests piling up and
  automatically starts more copies. Quiet weekend? It shuts some
  down to save money.

  This works because Feed and Community are STATELESS — any copy
  can handle any request. They don't remember anything between
  requests; everything is in the database.

  Chat is trickier because it holds open WebSocket connections
  (the live pipe that delivers messages instantly). A student is
  connected to ONE specific Chat copy. So when a message arrives
  for that student, we look up which copy they're connected to
  (stored in Redis) and forward it there.

── TECHNIQUE 2: CACHE EVERYTHING HOT ───────────────────────────────

  "Hot" data = data that's read constantly.

  Three layers of caching, from fastest to slowest:

    LAYER 1 — In the service's own memory (nanoseconds)
      "Is user X a member of community Y?" — asked on every
      single community request. Keep the answer in RAM for 5
      seconds. Most requests never leave the service.

    LAYER 2 — Redis (microseconds)
      Shared across all copies of a service. Your timeline, hot
      community metadata, presence info. If Layer 1 misses, we
      check here.

    LAYER 3 — The actual database (milliseconds)
      Only hit this if both caches miss. And when we do, we
      fill the caches on the way back so the next request is
      fast.

  Result: 95%+ of reads never touch the database.

── TECHNIQUE 3: PRE-COMPUTE THE FEED ───────────────────────────────

  The naive way to build a home timeline:
    "Find everyone I follow, get their recent posts, sort by
     time, return the top 50."

  This is a heavy database query. Doing it every time 12,000
  students refresh their feed would destroy the database.

  Our way — PUSH MODEL (fan-out on write):
    When Tigist posts, a background worker immediately adds the
    post ID to the Redis timeline of every follower. When a
    follower opens the app, their timeline is ALREADY BUILT —
    just read the list from Redis. No computation needed.

  Problem: what if someone has 5,000 followers (Student Union
  president)? Writing to 5,000 Redis lists per post is a lot.

  Solution — HYBRID MODEL:
    • Normal users (< 1,000 followers): push their posts to
      followers' timelines. (Fast, cheap.)
    • "Celebrity" users (≥ 1,000 followers): DON'T push. Instead,
      when someone opens their feed, we merge:
        (a) their pre-built Redis timeline, PLUS
        (b) a quick query: "recent posts from the celebrity
            accounts I follow"
      Merged and sorted in memory. Still fast, because there are
      very few celebrity accounts.

  This caps the work no matter how popular someone gets.

── TECHNIQUE 4: DON'T MAKE THE USER WAIT ───────────────────────────

  As shown in Part 3: when you post, we save it and reply
  IMMEDIATELY. Pushing to follower timelines, sending
  notifications, indexing for search — all of that happens in the
  background via Kafka.

  The user's experience: tap → 50ms → done.
  The system's experience: 2 more seconds of background work
  that nobody is waiting on.

── TECHNIQUE 5: FAIL GRACEFULLY, NOT CATASTROPHICALLY ──────────────

  Speed isn't just about being fast when everything works. It's
  about not being SLOW when something breaks.

  • CIRCUIT BREAKERS: If Identity Service starts failing,
    services stop calling it for 30 seconds and use cached data
    instead. No pile-up of doomed requests.

  • RATE LIMITING: Each user gets a budget (e.g., 60 writes per
    minute). A buggy client hammering the API gets throttled
    before it affects anyone else.

  • KAFKA AS A BUFFER: If the fan-out worker falls behind during
    a traffic spike, posts still succeed — they're safely in
    Postgres. Timelines just update a few seconds late. Better
    than the whole app freezing.

  • IDEMPOTENCY: If your phone retries a "send message" request
    because of a flaky connection, the server recognizes it's a
    duplicate and doesn't send the message twice.

--------------------------------------------------------------------------------
QUICK REFERENCE — THE WHOLE THING ON ONE PAGE
--------------------------------------------------------------------------------

  MAIN PARTS
    3 core services:     Feed, Chat, Community
    4 helper services:   Identity, Notification, Media, Search
    1 front door:        API Gateway
    1 event highway:     Kafka

  DATA STORAGE
    Feed       → Postgres (posts) + Redis (timelines)
    Chat       → Cassandra (messages) + Redis (presence)
    Community  → Postgres (groups/roles) + Redis (cache)
    Everyone   → S3 for files, Elasticsearch for search
    Rule:      Each service owns its DB. No sharing.

  COMMUNICATION
    Direct calls  → only when you MUST wait for an answer
                    (always with timeout + fallback)
    Kafka events  → everything else (the default)
                    Announce what happened, let others react

  SPEED
    1. Run many copies of each service
    2. Cache aggressively (memory → Redis → database)
    3. Pre-build timelines, hybrid push/pull for celebrities
    4. Do heavy work in the background, reply to users fast
    5. Degrade gracefully when parts fail

================================================================================
END
================================================================================
