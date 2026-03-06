════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — EVENT SYSTEM REFACTORING FOR PRODUCTION
Common event definition, compatibility rules, outbox pattern, replay & retention
════════════════════════════════════════════════════════════════════════════════

Builds on: res3 §8 (Kafka Topics & Event Schemas)
Scope:     Harden the event backbone so zero events are lost, schemas evolve
           safely, consumers can be rebuilt from history, and every team follows
           the same rules.

================================================================================
TABLE OF CONTENTS
================================================================================

  §1  Choosing the Common Event Definition Format
  §2  The Unified Event Envelope (Avro)
  §3  Schema Evolution — Compatibility Rules
  §4  Topic Naming Convention
  §5  Topic Versioning & Migration Protocol
  §6  Partition Key Strategy & Ordering Guarantees
  §7  The Transactional Outbox Pattern — Full Design
  §8  Outbox Per Service — Postgres & Cassandra Variants
  §9  Event Replay — Strategy, Retention, and Rebuild
  §10 Summary & Decision Record

================================================================================
§1  CHOOSING THE COMMON EVENT DEFINITION FORMAT
================================================================================

We evaluated three options. The choice affects every producer and consumer,
so we score against production criteria.

┌─────────────────────┬──────────────┬──────────────┬──────────────────────────┐
│ Criterion           │ JSON Schema  │ Apache Avro  │ Protocol Buffers (Proto) │
├─────────────────────┼──────────────┼──────────────┼──────────────────────────┤
│ Schema registry     │ Confluent SR │ Confluent SR │ Confluent SR (protobuf   │
│ integration         │ (supported)  │ (native,     │ serde) OR Buf Schema     │
│                     │              │ first-class) │ Registry                 │
│                     │              │              │                          │
│ Compatibility       │ JSON Schema  │ FULL,        │ Source-level compat via  │
│ checking            │ draft 2020-  │ BACKWARD,    │ buf breaking. No native  │
│ (automated)         │ 12 diff is   │ FORWARD,     │ wire-level compat check  │
│                     │ fragile;     │ BACKWARD_    │ in Confluent SR for      │
│                     │ Confluent SR │ TRANSITIVE   │ proto; Buf fills the gap │
│                     │ support is   │ — all built  │ but adds another tool.   │
│                     │ newer and    │ into the     │                          │
│                     │ less battle- │ registry.    │                          │
│                     │ tested.      │ Battle-      │                          │
│                     │              │ tested.      │                          │
│                     │              │              │                          │
│ Wire size           │ Largest.     │ Compact      │ Compact binary. ~Same    │
│                     │ Field names  │ binary. No   │ size as Avro.            │
│                     │ repeated in  │ field names  │                          │
│                     │ every msg.   │ on wire.     │                          │
│                     │              │              │                          │
│ Ser/deser speed     │ Slowest.     │ Fast.        │ Fastest.                 │
│                     │ JSON parse   │              │                          │
│                     │ overhead.    │              │                          │
│                     │              │              │                          │
│ Human readability   │ Excellent.   │ Needs tool   │ Needs tool to decode.    │
│ (debug/ops)         │ Plain text.  │ to decode.   │ .proto files are         │
│                     │              │ .avsc files  │ readable.                │
│                     │              │ are readable.│                          │
│                     │              │              │                          │
│ Default values &    │ Schema       │ Defaults in  │ Every field has an       │
│ evolution support    │ defaults are │ schema. New  │ implicit zero default.   │
│                     │ advisory,    │ fields MUST  │ No null distinction.     │
│                     │ not enforced │ have default │ Removing fields is       │
│                     │ on deser.    │ → old reader │ trickier (reserved).     │
│                     │              │ safely       │                          │
│                     │              │ ignores.     │                          │
│                     │              │              │                          │
│ Polyglot support    │ Every lang.  │ Java/Python/ │ Every lang (grpc-        │
│                     │              │ Go/JS/Rust   │ ecosystem).              │
│                     │              │ (official +  │                          │
│                     │              │ community).  │                          │
│                     │              │              │                          │
│ Ecosystem fit with  │ Good (we     │ Excellent    │ Excellent for gRPC;      │
│ Kafka + Confluent   │ already use  │ (Confluent's │ for Kafka it works but   │
│ SR                  │ JSON in res3)│ home turf).  │ Avro has deeper support. │
│                     │              │              │                          │
│ Schema as           │ Partial.     │ Yes. .avsc   │ Yes. .proto checked      │
│ code artifact       │              │ checked into │ into repo.               │
│                     │              │ repo.        │                          │
└─────────────────────┴──────────────┴──────────────┴──────────────────────────┘

DECISION: APACHE AVRO

  Rationale:
    1. Confluent Schema Registry has the deepest, most battle-tested
       compatibility enforcement for Avro. BACKWARD_TRANSITIVE
       compatibility mode does exactly what we need (§3) and has been
       production-proven at very large scale.
    2. Compact wire format. Our Kafka throughput is modest (§4 of res3:
       ~640 KB/s peak), so size isn't critical, but compactness reduces
       network tax and log storage.
    3. Default values are enforced at deserialization, which is the key
       mechanism that makes adding a new field safe for old consumers.
       JSON Schema's defaults are advisory; Proto's zero-value defaults
       conflate "field not set" with "field set to zero". Avro is the
       cleanest for event evolution.
    4. We already use gRPC (Proto) for internal sync APIs. Using Avro
       for async events gives us a clean boundary:
         – gRPC / Proto  = synchronous request/response contracts
         – Kafka / Avro   = asynchronous event contracts
       This avoids confusion about which .proto definitions are APIs
       and which are events.

  Trade-off acknowledged:
    – We lose human-readable messages on the wire. Mitigation: we
      will deploy Kafka-UI / AKHQ which uses the Schema Registry to
      deserialize messages in the browser for debugging. We also
      require every event type to have a JSON-equivalent example in
      the schema repo README for documentation.

  Alternative rejected — JSON Schema:
    Our res3 draft used JSON. For a prototype that's fine. For
    production we need automated compatibility enforcement at the
    registry level. Confluent SR's JSON Schema support is less mature
    and the diff semantics of JSON Schema (additionalProperties,
    oneOf, patternProperties) make automated compat checking fragile.

  Alternative rejected — Protobuf:
    Strong candidate. We rejected it because (a) mixing .proto for
    gRPC and .proto for Kafka events in the same repo muddies
    ownership, (b) Confluent SR proto compat checks are newer than
    Avro checks, and (c) Proto's lack of null-vs-default distinction
    complicates representing "field was not present in old schema".

================================================================================
§2  THE UNIFIED EVENT ENVELOPE (Avro)
================================================================================

Every event on every topic uses the same outer envelope. The envelope
is itself an Avro record. The payload is a UNION type specific to the
topic.

── 2.1 ENVELOPE SCHEMA (.avsc) ─────────────────────────────────────

  {
    "type": "record",
    "name": "EventEnvelope",
    "namespace": "com.astuconnect.events",
    "fields": [
      {
        "name": "event_id",
        "type": "string",
        "doc": "UUIDv7 — sortable by creation time."
      },
      {
        "name": "event_type",
        "type": "string",
        "doc": "Dot-separated: <domain>.<action>. E.g. post.created."
      },
      {
        "name": "event_version",
        "type": "int",
        "doc": "Schema version of the payload. Starts at 1."
      },
      {
        "name": "occurred_at",
        "type": {
          "type": "long",
          "logicalType": "timestamp-millis"
        },
        "doc": "When the domain event occurred (not when it was published)."
      },
      {
        "name": "producer",
        "type": "string",
        "doc": "Service name that produced this event. E.g. feed-service."
      },
      {
        "name": "correlation_id",
        "type": "string",
        "doc": "Propagated from the originating HTTP/gRPC request for tracing."
      },
      {
        "name": "causation_id",
        "type": ["null", "string"],
        "default": null,
        "doc": "event_id of the event that caused this event (for event chains)."
      },
      {
        "name": "payload",
        "type": "bytes",
        "doc": "Avro-encoded payload. Schema subject = <topic>-<event_type>-value."
      }
    ]
  }

  KEY DESIGN DECISIONS IN THE ENVELOPE:

    • payload is `bytes`, not an inline nested record.
      WHY: This lets the envelope schema stay stable (never changes)
      while individual payload schemas evolve independently. The
      Schema Registry subject for the payload is separate from the
      envelope subject. A consumer can deserialize the envelope with
      one schema, extract event_type, and then deserialize only the
      payload bytes it understands — skipping unknown event types
      gracefully.

    • causation_id (new vs res3).
      WHY: When Feed receives post.created and emits N
      timeline.write commands, each command carries
      causation_id = the post.created event_id. This lets us
      trace event chains in debugging and detect replay loops.

    • occurred_at is the DOMAIN time (when the user action happened),
      NOT the Kafka publish time. Kafka's built-in timestamp is the
      publish time. Having both lets us detect publish lag.

── 2.2 PAYLOAD EXAMPLE: post.created (v1) ──────────────────────────

  {
    "type": "record",
    "name": "PostCreatedV1",
    "namespace": "com.astuconnect.events.feed",
    "fields": [
      { "name": "post_id",        "type": "string"               },
      { "name": "author_id",      "type": "string"               },
      { "name": "community_id",   "type": ["null", "string"],
                                   "default": null                },
      { "name": "body_preview",   "type": "string",
        "doc": "First 280 chars."                                 },
      { "name": "has_media",      "type": "boolean"              },
      { "name": "media_refs",     "type": { "type": "array",
                                    "items": "string" },
                                   "default": []                  },
      { "name": "created_at",     "type": { "type": "long",
                                    "logicalType": "timestamp-millis" } }
    ]
  }

  Subject in Schema Registry: post.events-post.created-value
  Compatibility mode: BACKWARD_TRANSITIVE (see §3)

── 2.3 FULL PAYLOAD SCHEMA INVENTORY ───────────────────────────────

  ┌─────────────────────────────────────────┬──────────────┬───────────────┐
  │ Schema (namespace.Name)                 │ SR subject   │ Current ver   │
  ├─────────────────────────────────────────┼──────────────┼───────────────┤
  │ c.a.events.EventEnvelope                │ (shared)     │ 1             │
  │ c.a.events.identity.UserCreatedV1       │ user.events  │ 1             │
  │                                         │ -user.created│               │
  │                                         │ -value       │               │
  │ c.a.events.identity.UserUpdatedV1       │ (similar)    │ 1             │
  │ c.a.events.identity.UserFollowedV1      │              │ 1             │
  │ c.a.events.identity.UserUnfollowedV1    │              │ 1             │
  │ c.a.events.identity.UserBlockedV1       │              │ 1             │
  │ c.a.events.identity.UserUnblockedV1     │              │ 1             │
  │ c.a.events.feed.PostCreatedV1           │ post.events  │ 1             │
  │                                         │ -post.created│               │
  │                                         │ -value       │               │
  │ c.a.events.feed.PostDeletedV1           │ (similar)    │ 1             │
  │ c.a.events.feed.CommentCreatedV1        │ comment.evts │ 1             │
  │ c.a.events.feed.CommentDeletedV1        │              │ 1             │
  │ c.a.events.feed.ReactionSetV1           │ reaction.evts│ 1             │
  │ c.a.events.feed.ReactionRemovedV1       │              │ 1             │
  │ c.a.events.feed.TimelineWriteV1         │ feed.fanout  │ 1             │
  │                                         │ .cmd-*-value │               │
  │ c.a.events.chat.MessageSentV1           │ message.evts │ 1             │
  │ c.a.events.chat.MessageReadV1           │              │ 1             │
  │ c.a.events.chat.ConversationCreatedV1   │              │ 1             │
  │ c.a.events.community.CommunityCreatedV1 │ community    │ 1             │
  │                                         │ .events-*    │               │
  │ c.a.events.community.MemberJoinedV1     │              │ 1             │
  │ c.a.events.community.MemberLeftV1       │              │ 1             │
  │ c.a.events.community.RoleChangedV1      │              │ 1             │
  │ c.a.events.community.PostCreatedV1      │              │ 1             │
  │ c.a.events.community.PostRemovedV1      │              │ 1             │
  │ c.a.events.community.JoinRequestedV1    │              │ 1             │
  └─────────────────────────────────────────┴──────────────┴───────────────┘

  All .avsc files live in a shared Git repository:
    astu-connect/event-schemas/
      ├── envelope/
      │     └── EventEnvelope.avsc
      ├── identity/
      │     ├── UserCreatedV1.avsc
      │     ├── UserUpdatedV1.avsc
      │     └── ...
      ├── feed/
      │     ├── PostCreatedV1.avsc
      │     ├── PostDeletedV1.avsc
      │     └── ...
      ├── chat/
      │     ├── MessageSentV1.avsc
      │     └── ...
      ├── community/
      │     ├── CommunityCreatedV1.avsc
      │     └── ...
      └── ci/
            ├── register-schemas.sh
            └── compat-check.sh

  CI pipeline:
    On PR to event-schemas repo:
      1. avro-tools compile all .avsc → catch syntax errors.
      2. For each schema, call Schema Registry's compatibility
         check endpoint:
           POST /compatibility/subjects/{subject}/versions/latest
         If INCOMPATIBLE → PR blocked.
      3. On merge to main → register new version in SR.
      4. Publish generated language bindings (Java classes, Go
         structs, TypeScript interfaces) to internal package
         registry. Services import these as a dependency.

================================================================================
§3  SCHEMA EVOLUTION — COMPATIBILITY RULES
================================================================================

── 3.1 COMPATIBILITY MODE: BACKWARD_TRANSITIVE ─────────────────────

  We enforce BACKWARD_TRANSITIVE on every payload subject in the
  Schema Registry.

  What this means:

    BACKWARD = a NEW consumer (using the NEW schema) can read
               messages produced with ANY OLDER schema.

    TRANSITIVE = this holds across ALL previous versions, not just
                 the immediately preceding one. So v3 consumers
                 can read v1 messages directly, not just v2.

  Why this mode:

    In our system, consumers are deployed BEFORE producers (see §5
    migration protocol). A new consumer must read both old and new
    messages. BACKWARD ensures this. TRANSITIVE ensures it even if
    we skip versions during a fast iteration cycle.

    We don't need FORWARD compatibility (old consumer reads new
    messages) because we control deployment order. If we ever need
    it (e.g., gradual canary rollout of producers), we can upgrade
    to FULL_TRANSITIVE on a per-subject basis.

── 3.2 ALLOWED AND FORBIDDEN CHANGES ──────────────────────────────

  ┌─────────────────────────────────────┬──────────────┬──────────────────────┐
  │ Change                              │ Allowed?     │ Why                  │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Add a new field WITH a default      │ YES          │ Old messages lack    │
  │ value                               │              │ the field; consumer  │
  │                                     │              │ fills default.       │
  │                                     │              │ BACKWARD safe.       │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Add a new OPTIONAL field (union     │ YES          │ Same mechanism.      │
  │ with null, default null)            │              │ Default = null.      │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Remove a field that HAS a default   │ YES          │ New consumer schema  │
  │                                     │              │ doesn't expect it;   │
  │                                     │              │ Avro reader skips    │
  │                                     │              │ unknown fields.      │
  │                                     │ (with care)  │ Must ensure no       │
  │                                     │              │ consumer still needs │
  │                                     │              │ it. See §5 migration │
  │                                     │              │ protocol.            │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Remove a field that has NO default  │ NO           │ Old messages contain │
  │                                     │ (FORBIDDEN)  │ the field but new    │
  │                                     │              │ schema can't read it │
  │                                     │              │ without a default.   │
  │                                     │              │ First add a default, │
  │                                     │              │ then remove in a     │
  │                                     │              │ later version.       │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Rename a field                      │ NO           │ Avro matches by name.│
  │                                     │ (FORBIDDEN)  │ Rename = remove old +│
  │                                     │              │ add new. Must use    │
  │                                     │              │ aliases instead.     │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Change field type                   │ ONLY if Avro │ int → long is OK.    │
  │                                     │ promotion    │ string → int is NOT. │
  │                                     │ rules allow  │ See Avro spec §4.    │
  │                                     │ (int→long,   │                      │
  │                                     │  float→      │                      │
  │                                     │  double,     │                      │
  │                                     │  bytes→      │                      │
  │                                     │  string)     │                      │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Add a value to an enum              │ YES          │ Must add at the END  │
  │                                     │ (with care)  │ and ensure consumers │
  │                                     │              │ have a fallback for  │
  │                                     │              │ unknown values.      │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Remove a value from an enum         │ NO           │ Old messages may     │
  │                                     │ (FORBIDDEN)  │ contain that value.  │
  │                                     │              │ Stop producing it;   │
  │                                     │              │ keep it in schema.   │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Change the partition key semantics  │ NO           │ Breaks ordering.     │
  │                                     │ (FORBIDDEN)  │ Requires new topic   │
  │                                     │              │ (see §5).            │
  ├─────────────────────────────────────┼──────────────┼──────────────────────┤
  │ Change the event_type string for    │ NO           │ Consumers route by   │
  │ an existing event                   │ (FORBIDDEN)  │ event_type. Changing │
  │                                     │              │ it = new event type. │
  └─────────────────────────────────────┴──────────────┴──────────────────────┘

── 3.3 THE TWO-PHASE REMOVAL PROTOCOL ─────────────────────────────

  You can't remove a required field in one step. You must:

    Phase 1: Add a default value to the field. Register schema.
             Deploy consumers that no longer depend on the field.
             Wait until ALL consumers are on the new code.

    Phase 2: Remove the field from the schema. Register. Deploy
             producers that no longer set it.

  Between phases, there's a "deprecation window" (minimum 2 sprint
  cycles / 4 weeks) during which the field exists with a default.
  CI tracks deprecated fields via a `deprecated_fields.json` in the
  schema repo.

── 3.4 CI ENFORCEMENT ─────────────────────────────────────────────

  Every PR to the event-schemas repo runs:

    1. `avro-tools compile` — syntax check.
    2. Confluent SR REST API `/compatibility/subjects/{s}/versions/latest`
       — automated BACKWARD_TRANSITIVE check.
    3. Custom lint:
         • Every new field MUST have a `"default"` or be a union
           with null (default null).
         • No field names use reserved words (reserved by Avro or
           by our envelope).
         • `event_type` string matches the file path convention
           (identity/UserCreated → user.created).
         • Schema `doc` field is non-empty on every field.
    4. On merge: register in SR, publish language bindings.

================================================================================
§4  TOPIC NAMING CONVENTION
================================================================================

── 4.1 NAMING PATTERN ──────────────────────────────────────────────

  Pattern:

    <domain>.<category>[.v<N>]

  Where:
    <domain>    = the bounded context that OWNS and PRODUCES to this
                  topic. One of: user, post, comment, reaction,
                  message, community, feed (for internal commands).
    <category>  = "events" for domain events, "cmd" for internal
                  commands (CQRS-style; only consumed within the same
                  bounded context or by designated workers).
    .v<N>       = ONLY appended when a breaking migration forces a
                  new topic (see §5). Absent = v1 (the original).

  Examples:
    user.events              ← Identity service produces
    post.events              ← Feed service produces
    comment.events           ← Feed service produces
    reaction.events          ← Feed service produces
    message.events           ← Chat service produces
    community.events         ← Community service produces
    feed.fanout.cmd          ← Feed service produces (internal)
    post.events.v2           ← hypothetical breaking migration

── 4.2 RULES ───────────────────────────────────────────────────────

  R1. One producer per topic.
      Only the owning service writes to a topic. If two services
      need to emit similar events, they use separate topics (this
      hasn't arisen; if it does, it's a bounded-context smell).

  R2. Topic names are lowercase, dot-separated.
      No underscores, no hyphens, no camelCase in topic names.
      (Dots are conventional in Kafka and map naturally to SR
      subject naming.)

  R3. Internal command topics include "cmd" in the name.
      This distinguishes them from events. Commands are imperative
      ("do this"), events are past-tense ("this happened").
      Commands may be retried safely (idempotent by event_id).

  R4. Dead letter topics:
      Every consumer group has a DLT:
        <consumer-group>.dlt
      E.g., feed-fanout-worker.dlt, notification-service.dlt.
      Messages that fail processing after max retries land here
      for manual inspection.

  R5. No topic auto-creation.
      auto.create.topics.enable = false on all brokers. Topics are
      created via Terraform/Helm, reviewed in PR, with explicit
      partition count, replication factor, and retention.

── 4.3 SCHEMA REGISTRY SUBJECT NAMING ─────────────────────────────

  We use TopicRecordNameStrategy (Confluent SR setting):

    Subject = <topic>-<record-name>

  This allows multiple event types on a single topic (e.g.,
  user.events carries UserCreatedV1, UserUpdatedV1, etc.), each
  with its own compatibility timeline.

  Examples:
    user.events-com.astuconnect.events.identity.UserCreatedV1
    user.events-com.astuconnect.events.identity.UserUpdatedV1
    post.events-com.astuconnect.events.feed.PostCreatedV1

================================================================================
§5  TOPIC VERSIONING & MIGRATION PROTOCOL
================================================================================

Two kinds of schema changes:

  COMPATIBLE CHANGE (the normal case)
    Add/remove optional fields per §3 rules. Same topic.
    Same event_type string. Bump event_version integer in
    envelope. Register new schema version in SR. Deploy
    consumers first, then producers.

  INCOMPATIBLE / BREAKING CHANGE (rare, requires new topic)
    Examples: change partition key semantics, restructure the
    payload fundamentally, change serialization format.

    Migration protocol:

    Step 1: Create the new topic with .v<N+1> suffix.
              E.g., post.events.v2 (24 partitions, RF=3).

    Step 2: Deploy DUAL-WRITING producer.
              The producing service writes to BOTH old and new
              topics for every event. The transactional outbox
              (§7) supports multiple destination topics per event.

    Step 3: Deploy new consumers on the new topic.
              Each consumer group creates a new group on the
              v2 topic, starting from `earliest`.

    Step 4: Verify new consumers are caught up and correct.
              Compare consumer-group lag on v2 = 0.
              Smoke test downstream behaviour.

    Step 5: Switch remaining old consumers to new topic.
              One consumer group at a time. Monitor for errors
              after each switch.

    Step 6: Stop dual-write.
              Producer writes only to v2.

    Step 7: Deprecate old topic.
              Stop producing. Wait for retention to expire
              (or until all old consumer offsets are committed
              past the last message). Delete topic.

  TIMELINE RULES FOR MIGRATION
    • Step 2→3 must be atomic in a single deployment cycle.
    • Minimum soak time between steps: 48 hours.
    • Step 7 deletion: no earlier than 2× the old topic's retention
      period after the last message was produced.
    • All migration steps are tracked in a shared MIGRATIONS.md in
      the event-schemas repo. Each migration has an owner, dates,
      and status.

================================================================================
§6  PARTITION KEY STRATEGY & ORDERING GUARANTEES
================================================================================

── 6.1 CORE PRINCIPLE ──────────────────────────────────────────────

  Kafka guarantees ordering ONLY within a single partition.
  Our partition key strategy ensures that events about the SAME
  ENTITY land on the same partition, so consumers see them in
  order.

── 6.2 PARTITION KEY TABLE ─────────────────────────────────────────

  ┌───────────────────────┬──────────────────┬───────┬──────────────────────┐
  │ Topic                 │ Partition key     │ Parts │ Ordering guarantee   │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ user.events           │ user_id          │  12   │ All events for one   │
  │                       │                  │       │ user are ordered.    │
  │                       │                  │       │ Follow/unfollow for  │
  │                       │                  │       │ the same user arrive │
  │                       │                  │       │ in sequence.         │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ post.events           │ post_id          │  24   │ Created before       │
  │                       │                  │       │ deleted for the same │
  │                       │                  │       │ post. Consumers      │
  │                       │                  │       │ never see delete     │
  │                       │                  │       │ before create.       │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ comment.events        │ post_id          │  24   │ All comments on one  │
  │                       │ (NOT comment_id) │       │ post are ordered.    │
  │                       │                  │       │ Allows consumers to  │
  │                       │                  │       │ maintain per-post    │
  │                       │                  │       │ comment count        │
  │                       │                  │       │ accurately.          │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ reaction.events       │ post_id          │  24   │ Same reasoning:      │
  │                       │                  │       │ per-post reaction    │
  │                       │                  │       │ count consistency.   │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ message.events        │ conversation_id  │  48   │ Messages within a    │
  │                       │                  │       │ conversation are     │
  │                       │                  │       │ ordered. read events │
  │                       │                  │       │ for the same conv    │
  │                       │                  │       │ are ordered.         │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ community.events      │ community_id     │  12   │ Joined before left.  │
  │                       │                  │       │ Created before any   │
  │                       │                  │       │ member events.       │
  ├───────────────────────┼──────────────────┼───────┼──────────────────────┤
  │ feed.fanout.cmd       │ target_user_id   │  48   │ All timeline writes  │
  │                       │                  │       │ for one user land on │
  │                       │                  │       │ one partition →      │
  │                       │                  │       │ processed by one     │
  │                       │                  │       │ worker → no race on  │
  │                       │                  │       │ Redis ZADD/ZREM for  │
  │                       │                  │       │ that user's timeline.│
  └───────────────────────┴──────────────────┴───────┴──────────────────────┘

── 6.3 WHY POST_ID (NOT AUTHOR_ID) FOR POST EVENTS ────────────────

  A prolific author posting 5 times/second would cause a hotspot if
  author_id were the key (all 5 events on one partition). post_id
  distributes evenly because every post gets a unique UUID.

  Trade-off: events from the same author are NOT ordered across
  posts. This is acceptable — no consumer needs cross-post ordering
  for one author. The fan-out worker processes each post
  independently.

── 6.4 PARTITION COUNT SIZING RATIONALE ────────────────────────────

  • 12 partitions for low-volume topics (user.events ~5 msg/s,
    community.events ~12 msg/s). 12 allows up to 12 parallel
    consumer instances — enough headroom.
  • 24 partitions for medium-volume topics (post/comment/reaction).
  • 48 partitions for high-volume topics (message.events ~500 msg/s,
    feed.fanout.cmd ~3000 msg/s). 48 allows up to 48 worker
    instances for maximum parallel processing.

  Rule: we will NOT change partition count after topic creation.
  Kafka's repartitioning changes the key→partition mapping and
  breaks ordering guarantees mid-stream. If we need more partitions,
  we create a new topic (.v2) and migrate (§5).

── 6.5 CROSS-TOPIC ORDERING ───────────────────────────────────────

  We do NOT guarantee ordering across topics.

  Example: community.member.joined (on community.events) and the
  resulting timeline.write commands (on feed.fanout.cmd) may arrive
  at their respective consumers in any relative order.

  Consumers that depend on cross-topic causality must handle it:
    Strategy: IDEMPOTENT + RETRY.
      If Feed's consumer of community.member.joined tries to
      backfill posts but the community's posts haven't arrived in
      post.events yet — it still works because backfill reads from
      Postgres (the source of truth), not from events.

  No cross-topic transactions. Each consumer is self-contained.

================================================================================
§7  THE TRANSACTIONAL OUTBOX PATTERN — FULL DESIGN
================================================================================

── 7.1 THE PROBLEM ─────────────────────────────────────────────────

  Without an outbox, a service does two things on a write:
    1. Write to its database.
    2. Publish an event to Kafka.

  These are two separate systems. Three failure modes exist:

    (a) DB write succeeds, Kafka publish fails → event lost.
        Consumers never learn about the change. Data diverges.

    (b) Kafka publish succeeds, DB write fails → phantom event.
        Consumers react to something that didn't actually happen.

    (c) Both succeed, but the Kafka publish is slow → the HTTP
        response is delayed by Kafka latency. Under Kafka backlog
        or broker issues, user-facing latency spikes.

  All three are unacceptable in production.

── 7.2 THE SOLUTION — TRANSACTIONAL OUTBOX ─────────────────────────

  Instead of publishing directly to Kafka, the service writes the
  event to an OUTBOX TABLE in the SAME database, in the SAME
  transaction as the business write.

    ┌──────────────────────────────────────────────────────────────┐
    │ SINGLE DATABASE TRANSACTION                                  │
    │                                                              │
    │   INSERT INTO posts (id, author_id, body, ...)               │
    │     VALUES (...);                                            │
    │                                                              │
    │   INSERT INTO outbox (event_id, event_type, partition_key,   │
    │     topic, payload, created_at)                               │
    │     VALUES ('uuid-v7', 'post.created', <post_id>,            │
    │       'post.events', <avro-bytes>, NOW());                   │
    │                                                              │
    │   COMMIT;                                                    │
    │                                                              │
    └──────────────────────────────────────────────────────────────┘

  A separate process — the OUTBOX RELAY — reads unpublished rows
  from the outbox table and publishes them to Kafka:

    ┌──────────┐    poll     ┌──────────┐    produce   ┌─────────┐
    │  Outbox  │ ──────────► │  Outbox  │ ───────────► │  Kafka  │
    │  Table   │             │  Relay   │              │  Topic  │
    │ (in DB)  │ ◄────────── │ (process)│              │         │
    └──────────┘  mark sent  └──────────┘              └─────────┘

  Result:
    • If the DB transaction fails, neither the business write NOR
      the event row exists. No phantom event.
    • If the DB transaction succeeds, the event row is guaranteed
      to exist. The relay will eventually publish it. No lost event.
    • The HTTP response returns immediately after COMMIT. Kafka
      latency is completely off the user-facing path.

── 7.3 OUTBOX TABLE SCHEMA (Postgres — Feed, Community, Identity) ──

  CREATE TABLE outbox (
      event_id        UUID PRIMARY KEY,       -- UUIDv7
      event_type      TEXT NOT NULL,           -- e.g. 'post.created'
      event_version   INT NOT NULL DEFAULT 1,
      topic           TEXT NOT NULL,           -- e.g. 'post.events'
      partition_key   TEXT NOT NULL,           -- e.g. the post_id
      payload         BYTEA NOT NULL,          -- Avro-serialised payload
      correlation_id  TEXT,
      causation_id    TEXT,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      published_at    TIMESTAMPTZ,            -- NULL = not yet published
      retry_count     INT NOT NULL DEFAULT 0
  );

  CREATE INDEX idx_outbox_unpublished
      ON outbox (created_at ASC)
      WHERE published_at IS NULL;

  Notes:
    • The partial index (WHERE published_at IS NULL) makes polling
      fast: it only scans unpublished rows, which should be a tiny
      fraction of the table.
    • Old published rows are cleaned up by a nightly job:
      DELETE FROM outbox WHERE published_at < NOW() - INTERVAL '7 days';

── 7.4 OUTBOX TABLE SCHEMA (Cassandra — Chat Service) ──────────────

  Cassandra doesn't support multi-table transactions. The Chat
  service handles this differently:

  Option A — Lightweight Transaction (LWT) batch.
    Cassandra supports BATCH statements across tables in the same
    partition if all writes are to the same partition key. But our
    outbox and messages table have different partition keys
    (conversation_id vs a synthetic outbox partition).

  Option B — Write to outbox FIRST, process later.
    Chat writes the event to an outbox table (partitioned by a
    time-bucket shard), then writes the message to the messages
    table. If the message write fails, the relay will attempt to
    publish an event for a non-existent message. The consumer
    (Notification) is designed to handle "message not found" by
    skipping (idempotent).

  CHOSEN: Option B with a safety net.

  CREATE TABLE outbox_chat (
      shard           INT,                  -- 0..15 (time-bucket)
      created_at      TIMEUUID,             -- clustering key
      event_id        TEXT,
      event_type      TEXT,
      topic           TEXT,
      partition_key   TEXT,
      payload         BLOB,
      correlation_id  TEXT,
      causation_id    TEXT,
      published       BOOLEAN,              -- false initially
      PRIMARY KEY ((shard), created_at)
  ) WITH CLUSTERING ORDER BY (created_at ASC)
    AND default_time_to_live = 604800;      -- 7-day auto-expire

  Notes:
    • 16 shards allow 16 parallel relay workers.
    • TTL auto-expires published rows; no manual cleanup needed.
    • The relay sets `published = true` after successful Kafka ACK.
      On Cassandra, the update is idempotent.

── 7.5 OUTBOX RELAY — IMPLEMENTATION DETAILS ──────────────────────

  THE RELAY IS A SEPARATE PROCESS (sidecar or standalone deployment).
  It does NOT run inside the application server. This keeps the
  application simple and allows independent scaling of relay throughput.

  Two relay strategies:

  STRATEGY A: POLLING (chosen for initial rollout — simpler)

    Loop:
      1. SELECT event_id, topic, partition_key, event_type,
                event_version, payload, correlation_id, causation_id,
                created_at
           FROM outbox
          WHERE published_at IS NULL
          ORDER BY created_at ASC
          LIMIT 100
          FOR UPDATE SKIP LOCKED;

         (FOR UPDATE SKIP LOCKED: multiple relay replicas can poll
          concurrently without stepping on each other. Each replica
          grabs a disjoint batch.)

      2. For each row:
           a. Build EventEnvelope (Avro).
           b. Produce to Kafka (topic, key = partition_key, value).
           c. Await ACK (acks=all).

      3. UPDATE outbox SET published_at = NOW()
          WHERE event_id IN (...);

      4. COMMIT.

      5. If batch was full (100 rows), immediately loop.
         If batch was empty, sleep 50ms then loop.

    Guarantees:
      • AT-LEAST-ONCE delivery. If the relay crashes between step 2c
        and step 3, the row is still unpublished. Next poll re-reads
        and re-publishes. Consumers MUST be idempotent (they already
        are — see below).
      • ORDERED per partition key within a batch (we ORDER BY
        created_at). Across batches, Kafka's per-partition ordering
        handles it because the partition key is the same entity ID.

  STRATEGY B: CHANGE DATA CAPTURE (future upgrade)

    Use Debezium to stream the Postgres WAL → Kafka. Every INSERT
    into the outbox table is captured and routed to the target topic.
    Advantages: lower latency (~10ms vs ~50ms polling), no SKIP
    LOCKED overhead. Disadvantages: operational complexity (Debezium
    connectors, WAL retention, connector state management).

    We will migrate from polling to CDC per-service when polling
    latency becomes a measurable bottleneck. The switch is
    transparent to the application code: the outbox table stays
    the same; only the relay process changes.

  RELAY CONFIGURATION
    ┌──────────────────────────┬────────────┬──────────────────────────┐
    │ Parameter                │ Default    │ Notes                    │
    ├──────────────────────────┼────────────┼──────────────────────────┤
    │ poll_interval_ms         │ 50         │ Sleep between empty      │
    │                          │            │ polls.                   │
    │ batch_size               │ 100        │ Rows per poll cycle.     │
    │ max_retries_per_event    │ 10         │ After 10 failures,       │
    │                          │            │ move to DLT.             │
    │ retry_backoff_base_ms    │ 500        │ Exponential backoff:     │
    │                          │            │ 500, 1000, 2000, ...     │
    │ cleanup_retention_days   │ 7          │ DELETE published rows    │
    │                          │            │ older than this.         │
    │ kafka_producer_acks      │ all        │ Non-negotiable.          │
    │ kafka_producer_idempotent│ true       │ Prevents duplicate msgs  │
    │                          │            │ from producer retries.   │
    └──────────────────────────┴────────────┴──────────────────────────┘

── 7.6 CONSUMER IDEMPOTENCY ───────────────────────────────────────

  Because the outbox guarantees AT-LEAST-ONCE (not exactly-once),
  every consumer must handle duplicate events gracefully.

  Strategies per consumer:

    FEED FAN-OUT WORKER
      ZADD is idempotent by nature: adding the same (postId, score)
      to a sorted set multiple times is a no-op.

    NOTIFICATION SERVICE
      Maintains a Redis set `notif:processed:{event_id}` with TTL
      24h. Before processing, check if event_id exists. If yes, skip.

    SEARCH INDEXER
      Elasticsearch index operations are idempotent when using a
      deterministic document ID (= post_id / community_id). Reindexing
      the same document with the same content is a no-op.

    COMMUNITY SERVICE (consuming user.events)
      Upserts local user_snapshots by user_id. Upsert is idempotent.

    CHAT SERVICE (consuming community.member.joined)
      Before adding a user to a group chat, checks if they're
      already a member. If yes, skip.

    GENERAL RULE: every consumer's processing function must be safe
    to call twice with the same event_id without side effects.
    This is tested in each consumer's integration test suite.

================================================================================
§8  OUTBOX PER SERVICE — SUMMARY
================================================================================

  ┌─────────────────────┬──────────┬──────────────┬──────────────────────────┐
  │ Service             │ DB type  │ Outbox table │ Relay strategy           │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Feed Service        │ Postgres │ outbox       │ Polling (FOR UPDATE      │
  │                     │          │              │ SKIP LOCKED). 2 relay    │
  │                     │          │              │ replicas.                │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Identity Service    │ Postgres │ outbox       │ Polling. 1 relay replica │
  │                     │          │              │ (low volume: ~5 evt/s).  │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Community Service   │ Postgres │ outbox       │ Polling. 1 relay replica │
  │                     │          │              │ (low volume: ~12 evt/s). │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Chat Service        │ Cassandra│ outbox_chat  │ Polling (per-shard).     │
  │                     │          │ (16 shards)  │ 4 relay replicas, each   │
  │                     │          │              │ handling 4 shards.       │
  │                     │          │              │ ~500 evt/s.              │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Notification Svc    │ —        │ N/A          │ Pure consumer. Does not  │
  │                     │          │              │ produce events.          │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Search Indexer      │ —        │ N/A          │ Pure consumer.           │
  ├─────────────────────┼──────────┼──────────────┼──────────────────────────┤
  │ Media Service       │ —        │ N/A          │ Does not produce domain  │
  │                     │          │              │ events (media operations │
  │                     │          │              │ are synchronous only).   │
  └─────────────────────┴──────────┴──────────────┴──────────────────────────┘

================================================================================
§9  EVENT REPLAY — STRATEGY, RETENTION, AND REBUILD
================================================================================

── 9.1 WHY REPLAY MATTERS ─────────────────────────────────────────

  Consumers build local projections (read models) from events:
    • Feed builds author_snapshots from user.updated events.
    • Feed fan-out builds Redis timelines from post.created events.
    • Chat builds local block-lists from user.blocked events.
    • Search builds Elasticsearch indexes from post/community events.

  If a consumer's projection becomes corrupted (bug, data loss,
  schema migration gone wrong), we need to REBUILD IT by replaying
  events from the beginning.

── 9.2 RETENTION POLICY ────────────────────────────────────────────

  ┌───────────────────────┬─────────────┬──────────────────────────────────┐
  │ Topic                 │ Retention   │ Rationale                        │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ user.events           │ INFINITE    │ Low volume (~5 msg/s). 30k       │
  │                       │ (compact)   │ users lifetime. Use LOG           │
  │                       │             │ COMPACTION: Kafka keeps the       │
  │                       │             │ LATEST event per key (user_id).   │
  │                       │             │ Full user state is always         │
  │                       │             │ replayable.                       │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ community.events      │ INFINITE    │ Low volume. Log compaction by     │
  │                       │ (compact)   │ community_id. Latest state of     │
  │                       │             │ each community always available.  │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ post.events           │ 30 days     │ Medium volume. 30 days allows     │
  │                       │ (delete)    │ full rebuild of Search index and  │
  │                       │             │ fan-out state. Beyond 30 days,    │
  │                       │             │ rebuild from Postgres snapshot.   │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ comment.events        │ 14 days     │ Comments are secondary; Search    │
  │                       │ (delete)    │ can reindex from Postgres.        │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ reaction.events       │ 7 days      │ Only consumer is Notification.    │
  │                       │ (delete)    │ No projection needs full replay.  │
  │                       │             │ Reaction counts are in Feed DB.   │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ message.events        │ 14 days     │ Only consumer is Notification.    │
  │                       │ (delete)    │ Chat history is in Cassandra.     │
  │                       │             │ 14 days allows redelivery of      │
  │                       │             │ missed notifications.             │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ feed.fanout.cmd       │ 3 days      │ Internal command. If fan-out      │
  │                       │ (delete)    │ worker falls behind by >3 days,   │
  │                       │             │ we rebuild timelines from         │
  │                       │             │ Postgres (RebuildTimeline RPC),   │
  │                       │             │ not by replaying commands.        │
  ├───────────────────────┼─────────────┼──────────────────────────────────┤
  │ *.dlt (dead letters)  │ 30 days     │ Long enough for investigation.    │
  │                       │ (delete)    │                                   │
  └───────────────────────┴─────────────┴──────────────────────────────────┘

  LOG COMPACTION (for user.events and community.events):

    Kafka log compaction keeps the last message per key and discards
    older messages with the same key. This means:
      • The topic is effectively a snapshot of the latest state of
        every user / community.
      • A new consumer starting from offset 0 gets the FULL current
        state without reading billions of historical events.
      • Old events (e.g., "user changed name from A to B, then from
        B to C") are collapsed into just "user's name is C".

    Config:
      cleanup.policy       = compact
      min.compaction.lag.ms = 86400000  (24h — keep recent events
                              uncompacted for consumers that need
                              the delta, like Notification)
      delete.retention.ms  = 604800000 (7d — tombstones for deleted
                              entities remain for 7d so consumers
                              can process deletions)

── 9.3 REPLAY STRATEGIES ──────────────────────────────────────────

  STRATEGY 1: KAFKA REPLAY (for projections built purely from events)

    Use case: Search Indexer needs a full reindex.

    Steps:
      1. Create a NEW consumer group:
           search-indexer-rebuild-{timestamp}
      2. Set auto.offset.reset = earliest.
      3. Deploy the rebuild consumer against post.events,
         comment.events, community.events.
      4. Consumer reads from the beginning, rebuilds the
         Elasticsearch index into a NEW index alias.
      5. When consumer lag = 0, swap the ES alias atomically
         from old index to new index.
      6. Delete old index. Delete temporary consumer group.

    Works for: Search Indexer, Notification catchup (limited to
    retention window).

  STRATEGY 2: DATABASE SNAPSHOT + KAFKA TAIL (for projections that
              need data older than Kafka retention)

    Use case: Feed fan-out. We can't replay 30 days of post.events
    to rebuild every user's timeline — that would take too long
    and is wasteful.

    Steps:
      1. Run a batch job that reads from the owning database
         (Postgres `posts` table):
           SELECT post_id, author_id, created_at
             FROM posts
            WHERE created_at > NOW() - INTERVAL '30 days'
              AND deleted_at IS NULL
            ORDER BY created_at DESC;
      2. For each post, look up the author's followers (via
         Identity gRPC) and write timeline entries to Redis.
         (This is the RebuildTimeline RPC in res3 §7.4.)
      3. Record the Kafka offset corresponding to the start of
         the batch job (use consumer timestamps API:
         offsetsForTimes).
      4. Start normal fan-out consumer from THAT offset, so it
         picks up events that occurred during and after the
         batch rebuild.
      5. Brief overlap (events processed twice) is safe because
         ZADD is idempotent.

    Works for: Feed timeline rebuild, Feed author_snapshots
    rebuild (read from Identity DB snapshot via gRPC +
    tail user.events).

  STRATEGY 3: COMPACTED TOPIC FULL READ (for reference data)

    Use case: Chat Service needs to rebuild its local block-list
    after a data loss.

    Steps:
      1. Create new consumer group on user.events (compacted).
      2. Read from offset 0. Because the topic is compacted, this
         reads the LATEST state for every user (not full history).
      3. Extract user.blocked / user.unblocked events.
      4. Populate local block-list table.
      5. Switch to normal consumer group offset.

    Works for: Any projection of user.events or community.events
    (both compacted).

── 9.4 REPLAY SAFETY RULES ────────────────────────────────────────

  R1. Never replay into a LIVE consumer group.
      Always create a temporary consumer group for rebuild.
      This prevents the rebuild from racing with live processing.

  R2. Consumers MUST be idempotent (§7.6).
      Replay means re-processing events. If the consumer isn't
      idempotent, replay corrupts data.

  R3. Side-effecting consumers (Notification) MUST NOT replay
      side effects.
      The Notification consumer must detect replay mode (e.g.,
      via a config flag or by checking if the event's occurred_at
      is older than a threshold) and SKIP sending push notifications
      for replayed events. Nobody wants 30 days of stale
      notifications delivered at once.

  R4. Rebuild jobs must record their Kafka "high-water mark"
      (the offset at the time the batch snapshot started) and
      hand it off to the live consumer as the starting offset.
      This ensures no gap between snapshot and stream.

  R5. Replay/rebuild runbooks are required for each consumer
      projection. Documented in the ops runbook repo. Each
      runbook includes:
        • Trigger conditions (when to rebuild).
        • Exact commands to create temp consumer group.
        • Expected duration estimate.
        • Validation steps (how to verify the rebuild is correct:
          record counts, checksums, spot checks).
        • Rollback procedure (switch back to old projection if
          rebuild is broken).

── 9.5 RETENTION vs REBUILD COST MATRIX ────────────────────────────

  ┌───────────────┬────────────────┬────────────────┬──────────────────────┐
  │ Projection    │ Primary replay │ Fallback       │ Max rebuild time     │
  │               │ source         │ source         │ (estimated)          │
  ├───────────────┼────────────────┼────────────────┼──────────────────────┤
  │ Search index  │ Kafka replay   │ Postgres       │ ~20 min (from Kafka) │
  │ (ES)          │ (post, comment,│ batch export + │ ~60 min (from PG)    │
  │               │ community.evts)│ Kafka tail     │                      │
  ├───────────────┼────────────────┼────────────────┼──────────────────────┤
  │ Feed timeline │ Postgres       │ —              │ ~10 min for all      │
  │ (Redis)       │ snapshot +     │                │ active users         │
  │               │ Kafka tail     │                │ (parallelised)       │
  ├───────────────┼────────────────┼────────────────┼──────────────────────┤
  │ Author        │ user.events    │ Identity gRPC  │ ~2 min (compacted    │
  │ snapshots     │ (compacted)    │ GetUsersBatch  │ topic, ~30k records) │
  │ (Feed PG)     │                │                │                      │
  ├───────────────┼────────────────┼────────────────┼──────────────────────┤
  │ Block list    │ user.events    │ Identity gRPC  │ ~2 min               │
  │ (Chat local)  │ (compacted)    │ IsBlocked      │                      │
  ├───────────────┼────────────────┼────────────────┼──────────────────────┤
  │ Community     │ community.evts │ Community gRPC │ ~1 min (compacted)   │
  │ member cache  │ (compacted)    │ IsMemberBatch  │                      │
  │ (Chat, Feed)  │                │                │                      │
  ├───────────────┼────────────────┼────────────────┼──────────────────────┤
  │ Notification  │ NOT rebuilt.   │ —              │ N/A — notifications  │
  │ (sent notifs) │ Missed notifs  │                │ are fire-and-forget. │
  │               │ within 14d     │                │ Accept the loss.     │
  │               │ retention are  │                │                      │
  │               │ re-sent via    │                │                      │
  │               │ catchup.       │                │                      │
  └───────────────┴────────────────┴────────────────┴──────────────────────┘

================================================================================
§10  SUMMARY & DECISION RECORD
================================================================================

  ┌─────────┬──────────────────────────────────────────────────────────────┐
  │ Area    │ Decision                                                     │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ FORMAT  │ Apache Avro. Compact binary, first-class Confluent SR       │
  │         │ support, enforced defaults for safe evolution. Replaces      │
  │         │ the JSON payloads from our res3 draft.                       │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ SCHEMAS │ Stored in astu-connect/event-schemas repo. CI validates     │
  │         │ syntax + BACKWARD_TRANSITIVE compatibility. Merge publishes │
  │         │ to Schema Registry and generates language bindings.          │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ COMPAT  │ BACKWARD_TRANSITIVE on every payload subject. New fields    │
  │ RULES   │ require defaults. Removals are two-phase (add default →     │
  │         │ wait → remove). Renames are forbidden (use aliases). Type    │
  │         │ changes only via Avro promotions. Enum values never removed │
  │         │ from schema (stop producing instead). Partition key changes  │
  │         │ require a new topic.                                         │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ TOPIC   │ <domain>.<category>[.v<N>]. One producer per topic.         │
  │ NAMING  │ No auto-creation. Dead letter: <consumer-group>.dlt.        │
  │         │ SR subjects: TopicRecordNameStrategy.                        │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ TOPIC   │ Incompatible changes → new topic (.v2). Dual-write          │
  │ VERSION │ migration: producer writes to old+new → consumers switch    │
  │         │ → stop dual-write → deprecate old. 48h soak between steps.  │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │PARTITION│ Key = entity ID (post_id, user_id, conversation_id,         │
  │ KEYS    │ community_id, target_user_id). Guarantees per-entity order. │
  │         │ No cross-topic ordering; consumers handle via idempotency.  │
  │         │ Partition counts: 12 (low vol), 24 (med), 48 (high). Never  │
  │         │ changed after creation.                                      │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ OUTBOX  │ Every producing service writes events to an outbox table    │
  │         │ in the same DB transaction as the business write. Separate  │
  │         │ relay process polls and publishes. AT-LEAST-ONCE delivery.  │
  │         │ Postgres: FOR UPDATE SKIP LOCKED. Cassandra: sharded outbox │
  │         │ with TTL. Future upgrade: CDC (Debezium).                    │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │CONSUMER │ Mandatory for all consumers. ZADD idempotent, ES doc ID     │
  │IDEMPOT. │ idempotent, upsert idempotent, dedup set for Notification.  │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │RETENTION│ user.events + community.events: INFINITE (log compacted).   │
  │         │ post/comment.events: 30/14 days. message.events: 14 days.  │
  │         │ reaction.events: 7 days. feed.fanout.cmd: 3 days.           │
  │         │ DLTs: 30 days.                                               │
  ├─────────┼──────────────────────────────────────────────────────────────┤
  │ REPLAY  │ Three strategies depending on projection type:               │
  │         │ (1) Kafka replay from offset 0 (Search, compacted topics).  │
  │         │ (2) DB snapshot + Kafka tail (Feed timelines).              │
  │         │ (3) Compacted topic full read (reference data projections). │
  │         │ Safety: temp consumer groups, idempotent consumers,          │
  │         │ side-effect suppression for Notification during replay.      │
  │         │ Runbooks required per consumer projection.                   │
  └─────────┴──────────────────────────────────────────────────────────────┘

  WHY THIS DESIGN IS PRODUCTION-READY

    1. ZERO EVENTS LOST — The outbox pattern guarantees that if the
       business write committed, the event will eventually reach Kafka.
       No dual-write failures. No phantom events.

    2. SAFE EVOLUTION — BACKWARD_TRANSITIVE + CI enforcement + two-
       phase removal means schemas can evolve without breaking any
       consumer, even consumers running old code against new messages
       or new code against old messages.

    3. REBUILDABLE — Every consumer projection has a documented,
       tested rebuild path. Compacted topics for reference data mean
       rebuilds are fast. Longer-lived topics (30d for posts) allow
       full Search reindexes from Kafka alone.

    4. ORDERED WHERE IT MATTERS — Entity-keyed partitions guarantee
       that per-entity causality is preserved (create before delete,
       join before leave). Cross-entity ordering is not needed and
       not promised, keeping the system horizontally scalable.

    5. OBSERVABLE — Envelope carries event_id, correlation_id,
       causation_id. Combined with consumer-group lag metrics and
       DLTs, operators can trace any event from HTTP request to
       final consumer side-effect.

════════════════════════════════════════════════════════════════════════════════
END OF SPEC
════════════════════════════════════════════════════════════════════════════════
