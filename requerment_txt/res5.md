════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — OPERATOR RUNBOOK
Event Replay & Consumer Projection Rebuild
════════════════════════════════════════════════════════════════════════════════

Audience:  On-call engineers and platform operators.
Purpose:   Step-by-step procedures to replay Kafka events, reset offsets,
           create temporary consumer groups, take snapshots, and rebuild
           consumer-side projections after data loss, schema migration,
           or bug recovery.
Pairs with: res4 (event system spec) §9.
Status:    Production runbook. Execute EXACTLY as written.

================================================================================
TABLE OF CONTENTS
================================================================================

  RB-0   Quick Decision Tree — Which Runbook Do I Need?
  RB-1   Pre-Flight Checklist (Required Before ANY Procedure)
  RB-2   Offset Reset (Same Consumer Group)
  RB-3   Temporary Consumer Group Creation & Teardown
  RB-4   Database Snapshot Capture + High-Water Mark Recording
  RB-5   FULL PROCEDURE — Rebuild Search Index (Kafka-only replay)
  RB-6   FULL PROCEDURE — Rebuild Feed Timelines (Snapshot + Kafka tail)
  RB-7   FULL PROCEDURE — Rebuild Author Snapshots (Compacted topic replay)
  RB-8   FULL PROCEDURE — Rebuild Chat Block-List (Compacted topic replay)
  RB-9   FULL PROCEDURE — Rebuild Community Member Cache (Compacted replay)
  RB-10  Dead-Letter Topic Reprocessing
  RB-11  Notification Catch-Up (Bounded Replay, Side-Effect Suppression)
  RB-12  Verification Checks (Record Counts, Checksums, Spot Checks)
  RB-13  Troubleshooting — Common Failures & Fixes
  RB-14  Emergency Abort / Rollback Procedures
  RB-15  Post-Incident Cleanup

================================================================================
RB-0  QUICK DECISION TREE — WHICH RUNBOOK DO I NEED?
================================================================================

  START: What is broken / what are you trying to fix?

  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │  Search results missing / stale / wrong?                               │
  │      → RB-5  Rebuild Search Index                                      │
  │                                                                        │
  │  User timelines empty / corrupted / stale after Redis loss?            │
  │      → RB-6  Rebuild Feed Timelines                                    │
  │                                                                        │
  │  Timeline showing wrong author names / avatars?                        │
  │      → RB-7  Rebuild Author Snapshots                                  │
  │                                                                        │
  │  Blocked users can still message / unblocked users can't?              │
  │      → RB-8  Rebuild Chat Block-List                                   │
  │                                                                        │
  │  Chat group membership out of sync with Community?                     │
  │  Feed lets non-members post in community?                              │
  │      → RB-9  Rebuild Community Member Cache                            │
  │                                                                        │
  │  Events piling up in a DLT?                                            │
  │      → RB-10 Dead-Letter Topic Reprocessing                            │
  │                                                                        │
  │  Notifications not sent for some time window (consumer was down)?      │
  │      → RB-11 Notification Catch-Up                                     │
  │                                                                        │
  │  Consumer group somehow got ahead of where it should be                │
  │  (skipped events)?                                                     │
  │      → RB-2  Offset Reset (rewind the group)                           │
  │                                                                        │
  │  New consumer being onboarded to an existing topic?                    │
  │      → RB-3  Temporary Consumer Group (bootstrap from earliest)        │
  │                                                                        │
  └────────────────────────────────────────────────────────────────────────┘

================================================================================
RB-1  PRE-FLIGHT CHECKLIST  (REQUIRED BEFORE ANY PROCEDURE)
================================================================================

  Execute ALL items. Do not skip.

  ☐  1. Confirm you are on-call or have explicit approval from the
         owning service's team lead. Log the incident ticket number
         (or create one). All commands below are pasted into the
         incident timeline.

  ☐  2. Identify the environment. All commands in this runbook
         assume env vars:
           KAFKA_BOOTSTRAP   = <broker-list>  (e.g., kafka-0:9092,...)
           KAFKA_TOOLS_IMAGE = confluentinc/cp-kafka:latest
           ENV               = prod | staging

  ☐  3. Verify Kafka cluster health before touching anything:
           kafka-broker-api-versions --bootstrap-server $KAFKA_BOOTSTRAP
         Expect: all 3 brokers listed, no errors.

  ☐  4. Verify Schema Registry is reachable:
           curl -s http://schema-registry:8081/subjects | jq length
         Expect: non-zero.

  ☐  5. Snapshot the current state of the affected consumer group
         BEFORE making changes:
           kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
             --group <group-name> --describe \
             > /tmp/cg-before-${INCIDENT_ID}.txt
         Attach this file to the incident ticket.

  ☐  6. Determine whether the procedure requires the LIVE consumer
         to be STOPPED. See per-procedure note. If yes:
           kubectl scale deployment/<consumer-deployment> \
             --replicas=0 -n <namespace>
         Verify consumer-group has 0 active members:
           kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
             --group <group-name> --describe | grep -c CONSUMER-ID
         Expect: 0 (or header line only).

  ☐  7. Post in #astu-connect-oncall Slack channel:
         "[${ENV}] Starting ${PROCEDURE} for ${INCIDENT_ID}. Owner:
          @${YOUR_NAME}. Expect ${SERVICE} degradation for ~${EST}."

  ☐  8. Set a reminder / pager for the expected completion time.
         If procedure exceeds 2× expected time → escalate.

================================================================================
RB-2  OFFSET RESET (SAME CONSUMER GROUP)
================================================================================

  WHEN TO USE
    • Consumer group accidentally committed an offset past events it
      never processed (bug caused it to skip).
    • You want to re-process a small recent window (last N minutes)
      on the SAME group.
    • NOT for full rebuild — use RB-3 (temporary group) for that.

  IMPORTANT
    • The consumer group MUST have zero active members during reset.
      Kafka rejects offset reset on an active group.
    • Offset reset is permanent for the group. If you need to
      preserve the old offsets, snapshot them first (RB-1 step 5).

  PROCEDURE

    Step 1: Stop the consumer deployment.
      kubectl scale deployment/<consumer> --replicas=0 -n <ns>

      Wait for: consumer-group describe shows 0 members.

    Step 2: Dry-run the reset (no changes applied).
      kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
        --group <group-name> \
        --topic <topic-name> \
        --reset-offsets \
        --to-datetime 2026-03-02T09:00:00.000Z \
        --dry-run

      Review output. It shows CURRENT-OFFSET → NEW-OFFSET per
      partition. Sanity-check: NEW-OFFSET should be LESS than
      CURRENT-OFFSET (we're rewinding).

      Alternative targets:
        --to-earliest         → go to the oldest retained offset
        --to-latest           → skip everything (careful!)
        --to-offset <N>       → specific offset (all partitions)
        --shift-by -<N>       → rewind by N messages
        --to-datetime <ISO>   → first offset at/after timestamp

    Step 3: Execute the reset.
      Same command but replace --dry-run with --execute.

    Step 4: Verify.
      kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
        --group <group-name> --describe

      CURRENT-OFFSET should equal the NEW-OFFSET from step 2.
      LAG will have increased (this is expected — we rewound).

    Step 5: Restart the consumer.
      kubectl scale deployment/<consumer> --replicas=<orig> -n <ns>

    Step 6: Monitor.
      Watch consumer lag decrease back to normal. Watch for error
      spikes in consumer logs (reprocessing old events may surface
      idempotency bugs). Alert on-call if errors exceed baseline.

================================================================================
RB-3  TEMPORARY CONSUMER GROUP — CREATION & TEARDOWN
================================================================================

  WHEN TO USE
    • Full projection rebuild via Kafka replay.
    • Onboarding a new consumer that needs to bootstrap from history.
    • Testing a consumer change against production data without
      disturbing the live consumer group.

  WHY A TEMPORARY GROUP
    • The live consumer group's offsets are precious — they represent
      "where production is up to". We never rewind the live group for
      a full rebuild because if the rebuild fails we've lost our
      place.
    • A temporary group starts from `earliest` (or a chosen offset),
      processes independently, and is deleted when done.

  NAMING CONVENTION
    <live-group-name>-rebuild-<YYYYMMDD>-<HHMM>
    Example: search-indexer-rebuild-20260302-0945

  PROCEDURE — CREATE

    Step 1: Choose a name. Record it in the incident ticket.
      REBUILD_GROUP="search-indexer-rebuild-$(date -u +%Y%m%d-%H%M)"

    Step 2: Deploy the rebuild consumer.
      The rebuild consumer is the SAME container image as the live
      consumer but with different config:

        helm upgrade --install ${REBUILD_GROUP} \
          ./charts/<consumer-chart> \
          --namespace <ns> \
          --set consumerGroup=${REBUILD_GROUP} \
          --set autoOffsetReset=earliest \
          --set replayMode=true \
          --set targetIndex=<new-index-name>    # (ES-specific)
          --set replicas=<N>                    # parallelism ≤ partitions

      KEY FLAGS:
        consumerGroup      — the temporary group name.
        autoOffsetReset    — "earliest" to start from the oldest
                              retained offset.
        replayMode=true    — enables side-effect suppression (see
                              RB-11). CRITICAL for consumers with
                              external side effects.
        targetIndex        — (projection-specific) where to write
                              the rebuilt data. Must be a SEPARATE
                              destination from the live projection
                              (see shadow-write pattern in RB-5).

    Step 3: Verify the group is reading.
      kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
        --group ${REBUILD_GROUP} --describe

      Expect: CURRENT-OFFSET starts at a low value and increases.
              LAG starts at a high value and decreases.

    Step 4: Monitor progress.
      Grafana dashboard: "Consumer Lag by Group".
      Filter to ${REBUILD_GROUP}. Lag should trend to 0.

      Estimate completion: (initial lag) ÷ (consumption rate).
      If consumption rate plateaus below expected, check:
        • Consumer pod CPU/memory (scale replicas if needed)
        • Downstream write target (ES/Redis/DB) saturation

  PROCEDURE — TEARDOWN (after rebuild validated, see RB-12)

    Step 1: Stop the rebuild consumer.
      helm uninstall ${REBUILD_GROUP} -n <ns>

    Step 2: Delete the consumer group (frees Kafka metadata).
      kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
        --group ${REBUILD_GROUP} --delete

      Expect: "Deletion of requested consumer groups was successful."

    Step 3: Update incident ticket: temp group deleted.

================================================================================
RB-4  DATABASE SNAPSHOT CAPTURE + HIGH-WATER MARK RECORDING
================================================================================

  WHEN TO USE
    When rebuilding a projection from the owning service's database
    (because Kafka retention is too short for full history).
    Used by RB-6 (Feed timelines).

  PRINCIPLE
    A snapshot reads state at time T. While the snapshot runs, new
    events continue arriving. After the snapshot, we must resume
    from Kafka at EXACTLY the offset corresponding to T — otherwise
    we lose events that happened between T and "now".

    ┌──────────────────────────────────────────────────────────────┐
    │                                                              │
    │  time ───────────────────────────────────────────────────►   │
    │                                                              │
    │  T₀            T₁                    T₂        T₃            │
    │  │             │                     │         │             │
    │  │             │   snapshot reads    │  kafka  │             │
    │  │   record    │   from DB           │  tail   │  live       │
    │  │   HWM       │                     │  catches│  consumer   │
    │  │             │                     │  up     │  resumes    │
    │  │             │                     │         │             │
    │  Kafka offset  │                     │         │             │
    │  at T₀ = HWM ──┴──────────────────── tail starts here        │
    │                                                              │
    │  Events between T₀ and T₂ are processed by BOTH snapshot     │
    │  (if written to DB before snapshot read them) AND kafka      │
    │  tail. This overlap is SAFE because writes are idempotent.   │
    │                                                              │
    └──────────────────────────────────────────────────────────────┘

  PROCEDURE

    Step 1: Record the high-water mark (HWM) BEFORE starting
            the snapshot.

      For each topic the consumer reads:
        kafka-run-class kafka.tools.GetOffsetShell \
          --bootstrap-server $KAFKA_BOOTSTRAP \
          --topic <topic-name> \
          --time -1 \
          > /tmp/hwm-${INCIDENT_ID}-<topic>.txt

      The -1 flag returns the LATEST offset per partition at the
      moment of the query. This is the HWM.

      Save these files to the incident ticket. They are the
      starting point for the Kafka tail in later steps.

    Step 2: Record a DB-side timestamp.
      In the owning Postgres:
        SELECT NOW(), pg_current_wal_lsn();
      Record both. The timestamp is used to bound the snapshot
      query. The LSN is for auditing / forensics.

    Step 3: Run the snapshot query.
      (Projection-specific — see RB-6 for Feed timeline example.)
      Use a READ REPLICA, not the primary, to avoid load impact.

      Bound the query by the timestamp from Step 2:
        ... WHERE created_at <= '<timestamp-from-step-2>'

      This ensures the snapshot has a well-defined cutoff.

    Step 4: After snapshot completes, start the Kafka tail.
      Create a temporary consumer group (RB-3). Instead of
      `autoOffsetReset=earliest`, set each partition's starting
      offset to the HWM recorded in Step 1:

        # For each line <topic>:<partition>:<offset> in the HWM file:
        kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
          --group ${REBUILD_GROUP} \
          --topic <topic>:<partition> \
          --reset-offsets --to-offset <offset> \
          --execute

      (Do this for every partition listed in the HWM file. Some
      tooling scripts wrap this; see /ops/scripts/set-offsets.sh)

    Step 5: Start the tail consumer.
      It processes events from HWM → current. Some events will
      overlap with what the snapshot already wrote — this is
      expected and safe (idempotent writes).

    Step 6: When tail lag reaches 0, the projection is fully
            caught up. Proceed to validation (RB-12) and cutover.

================================================================================
RB-5  FULL PROCEDURE — REBUILD SEARCH INDEX (Kafka-only replay)
================================================================================

  SYMPTOMS TRIGGERING THIS PROCEDURE
    • Search returns stale results (posts not appearing).
    • ES index corrupted / red cluster state.
    • Schema change in ES mapping requires full reindex.

  PREREQUISITES
    • All of RB-1 (pre-flight) completed.
    • post.events retention = 30 days, community.events = compacted.
      If the corruption predates 30 days, fall back to the
      PG-snapshot variant (see RB-5.ALT below).

  ESTIMATED DURATION
    • ~20 min consumption + ~10 min validation = ~30 min total.
    • Search remains available throughout (serves from old index).

  STEPS

    Step 1: Create a new Elasticsearch index.
      NEW_INDEX="posts-v$(date -u +%Y%m%d%H%M)"
      curl -X PUT "http://es:9200/${NEW_INDEX}" \
        -H 'Content-Type: application/json' \
        -d @./ops/es-mappings/posts.json

      Verify: curl "http://es:9200/${NEW_INDEX}/_count"
              → { "count": 0 }

    Step 2: Create and deploy temporary consumer group (per RB-3).
      REBUILD_GROUP="search-indexer-rebuild-$(date -u +%Y%m%d-%H%M)"

      helm install ${REBUILD_GROUP} ./charts/search-indexer \
        --namespace search \
        --set consumerGroup=${REBUILD_GROUP} \
        --set autoOffsetReset=earliest \
        --set replayMode=true \
        --set targetIndex=${NEW_INDEX} \
        --set replicas=4

      Note: replayMode=true for search-indexer is a no-op (indexing
      is its only side effect), but we set it for consistency.

    Step 3: Monitor until lag = 0.
      watch -n5 "kafka-consumer-groups \
        --bootstrap-server $KAFKA_BOOTSTRAP \
        --group ${REBUILD_GROUP} --describe \
        | awk '{sum+=\$6} END {print \"Total lag:\", sum}'"

      Wait for: Total lag: 0 (and stable for 2 consecutive reads).

    Step 4: Run verification (RB-12, Search-specific checks).
      • Count parity:
          PG_COUNT=$(psql -h feed-pg-replica -c \
            "SELECT COUNT(*) FROM posts WHERE deleted_at IS NULL \
             AND created_at > NOW() - INTERVAL '30 days';" -tA)
          ES_COUNT=$(curl -s "http://es:9200/${NEW_INDEX}/_count" \
            | jq .count)
          echo "PG: $PG_COUNT, ES: $ES_COUNT"

        Expect: within 1% (difference = in-flight events).
        If difference > 5%: STOP. Investigate (RB-13).

      • Spot-check 10 random posts:
          for id in $(psql ... "SELECT id FROM posts ORDER BY \
            RANDOM() LIMIT 10" -tA); do
            curl -s "http://es:9200/${NEW_INDEX}/_doc/${id}" \
              | jq '._source.body_preview'
          done
        Each should return a non-null result.

    Step 5: ATOMIC CUTOVER — swap the alias.
      The live search service queries via an alias `posts-live`,
      not the index directly. Swap it:

        curl -X POST "http://es:9200/_aliases" \
          -H 'Content-Type: application/json' -d '{
            "actions": [
              { "remove": { "index": "'${OLD_INDEX}'",
                            "alias": "posts-live" }},
              { "add":    { "index": "'${NEW_INDEX}'",
                            "alias": "posts-live" }}
            ]}'

      This is atomic. Search immediately serves from the new index.

    Step 6: Update the LIVE search-indexer consumer to target the
            new index.

      helm upgrade search-indexer ./charts/search-indexer \
        --namespace search \
        --set targetIndex=${NEW_INDEX} \
        --reuse-values

      (The live indexer's offsets are already ahead of the rebuild
      group, so it just continues indexing new events into the new
      index. No offset reset needed.)

    Step 7: Teardown (per RB-3 teardown).
      • helm uninstall ${REBUILD_GROUP}
      • kafka-consumer-groups --delete --group ${REBUILD_GROUP}
      • Delete old ES index AFTER 24h safety window:
          curl -X DELETE "http://es:9200/${OLD_INDEX}"

    Step 8: Close incident. Record ${NEW_INDEX} as the current
            live index in the ops wiki.

  ── RB-5.ALT — Fallback: PG-snapshot reindex ────────────────────

    When events older than Kafka retention are needed (e.g., rebuilding
    after >30-day data corruption).

    Replace Step 2 with a direct PG→ES batch indexer:
      ./ops/jobs/reindex-from-pg.sh --target ${NEW_INDEX}

    This script reads from the Feed Postgres replica in batches of
    5,000 rows and bulk-indexes into ES. ~60 min for full history.

    After the batch completes, record the HWM (RB-4 step 1) and
    start a Kafka tail from the HWM to catch up events that
    occurred during the batch. Then proceed with Step 4 onwards.

================================================================================
RB-6  FULL PROCEDURE — REBUILD FEED TIMELINES (Snapshot + Kafka tail)
================================================================================

  SYMPTOMS TRIGGERING THIS PROCEDURE
    • Redis (Feed Cache) data loss — failover lost AOF, or
      accidental FLUSHALL.
    • Users report empty home feeds.
    • Automated alert: `feed_timeline_empty_ratio > 0.1`.

  APPROACH
    Timelines are NOT in Kafka. They're derived by the fan-out
    worker from post.created events. But replaying all post.events
    (30 days) through the fan-out worker means re-looking-up
    follower lists for every historical post — slow and wasteful.

    Instead: read recent posts directly from Postgres, enumerate
    followers once per AUTHOR (not per post), and batch-write
    Redis ZSETs. Then tail Kafka to catch up in-flight events.

  ESTIMATED DURATION
    • ~10 min for all active users (parallelised).
    • Feed read degraded (slower — falls back to PG pull-model)
      throughout. NO outage — users still see their feed.

  STEPS

    Step 1: Scale down the live fan-out worker to 0.
      kubectl scale deployment/feed-fanout-worker --replicas=0 \
        -n feed
      This prevents the live worker from writing partial timelines
      that race with the rebuild.

    Step 2: Record HWM for post.events AND feed.fanout.cmd.
      (per RB-4 step 1)
        kafka-run-class kafka.tools.GetOffsetShell \
          --bootstrap-server $KAFKA_BOOTSTRAP \
          --topic post.events --time -1 \
          > /tmp/hwm-${INCIDENT_ID}-post.events.txt
        kafka-run-class kafka.tools.GetOffsetShell \
          --bootstrap-server $KAFKA_BOOTSTRAP \
          --topic feed.fanout.cmd --time -1 \
          > /tmp/hwm-${INCIDENT_ID}-feed.fanout.cmd.txt

    Step 3: Record DB snapshot timestamp.
      psql -h feed-pg-replica -c "SELECT NOW();" -tA \
        > /tmp/snapshot-ts-${INCIDENT_ID}.txt
      SNAPSHOT_TS=$(cat /tmp/snapshot-ts-${INCIDENT_ID}.txt)

    Step 4: Run the timeline rebuild batch job.
      kubectl create job timeline-rebuild-${INCIDENT_ID} \
        --from=cronjob/timeline-rebuild-template \
        -n feed \
        -- --mode=full --snapshot-ts="${SNAPSHOT_TS}" \
           --parallelism=16

      The job:
        a. Queries Feed PG replica for all author_ids with posts
           in the last 30 days.
        b. For each author, calls Identity gRPC GetFollowerIds
           (streaming).
        c. For each follower, computes the set of post_ids they
           should see from that author (bounded by snapshot-ts)
           and pipelines ZADD into Redis timeline:{followerId}.
        d. Caps each timeline at 800 entries (ZREMRANGEBYRANK).
        e. Emits progress metrics: feed_rebuild_users_processed.

      Monitor:
        kubectl logs -f job/timeline-rebuild-${INCIDENT_ID} -n feed
        Grafana: feed_rebuild_users_processed vs total users.

    Step 5: Wait for job completion.
      kubectl wait --for=condition=complete --timeout=30m \
        job/timeline-rebuild-${INCIDENT_ID} -n feed

      If timeout: check job logs for errors (RB-13).

    Step 6: Reset live consumer group offsets to HWM.
      The live fan-out worker's consumer group (feed-fanout-worker)
      must resume from the HWM recorded in Step 2, NOT from where
      it last committed (which might be far behind due to the
      outage, or far ahead if the group was healthy but Redis
      was lost).

      For each line in the HWM files:
        kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
          --group feed-fanout-worker \
          --topic feed.fanout.cmd:<partition> \
          --reset-offsets --to-offset <hwm-offset> \
          --execute

      (Use /ops/scripts/set-offsets.sh to automate across all
       partitions.)

    Step 7: Restart the live fan-out worker.
      kubectl scale deployment/feed-fanout-worker --replicas=2 \
        -n feed

      It now processes events from HWM → current. Some timelines
      will receive duplicate ZADDs (events that were captured in
      both the snapshot and the tail) — idempotent, no harm.

    Step 8: Validation (RB-12).
      • Sample 20 random active users:
          for uid in $(redis-cli KEYS 'timeline:*' | shuf -n20); do
            COUNT=$(redis-cli ZCARD $uid)
            echo "$uid → $COUNT entries"
          done
        Expect: each has > 0 entries (unless the user follows
        nobody).

      • Compare one user's Redis timeline to a direct PG query:
          UID=<pick-one>
          REDIS_IDS=$(redis-cli ZREVRANGE timeline:${UID} 0 49)
          PG_IDS=$(psql ... "SELECT p.id FROM posts p \
            JOIN follows f ON f.followee_id = p.author_id \
            WHERE f.follower_id='${UID}' \
            ORDER BY p.created_at DESC LIMIT 50" -tA)
          # The two sets should overlap substantially.

      • Check fan-out worker lag → should trend to 0 within 2 min.

    Step 9: Cleanup.
      kubectl delete job timeline-rebuild-${INCIDENT_ID} -n feed
      (after verifying completion).

    Step 10: Close incident.

================================================================================
RB-7  FULL PROCEDURE — REBUILD AUTHOR SNAPSHOTS (Compacted topic replay)
================================================================================

  SYMPTOMS TRIGGERING THIS PROCEDURE
    • Feed timeline shows wrong or stale display names / avatars.
    • author_snapshots table count diverges from Identity user count.
    • After a bug in the user.events consumer.

  APPROACH
    user.events is log-compacted (see res4 §9.2). Reading from
    offset 0 gives the LATEST state for every user, not the full
    history. Fast (~30k records).

  ESTIMATED DURATION
    • ~2 min consumption + ~1 min validation = ~3 min total.
    • No user-facing impact (Feed serves from existing snapshots
      which gradually get corrected).

  STEPS

    Step 1: (No need to stop the live consumer — the rebuild is
            non-destructive. Snapshots are upserted by user_id;
            the live consumer and rebuild consumer both upserting
            is safe.)

    Step 2: Create temporary consumer group.
      REBUILD_GROUP="feed-user-events-rebuild-$(date -u +%Y%m%d-%H%M)"

      helm install ${REBUILD_GROUP} ./charts/feed-event-consumer \
        --namespace feed \
        --set consumerGroup=${REBUILD_GROUP} \
        --set autoOffsetReset=earliest \
        --set topics='{user.events}' \
        --set replayMode=true \
        --set replicas=2

      Only 2 replicas needed (12 partitions, low volume).

    Step 3: Monitor lag → 0 (per RB-3 step 4).
      Expect: < 2 minutes for compacted user.events.

    Step 4: Validation (RB-12).
      • Count parity:
          SNAP_COUNT=$(psql -h feed-pg-primary -c \
            "SELECT COUNT(*) FROM author_snapshots;" -tA)
          IDENTITY_COUNT=$(grpcurl -plaintext identity:9090 \
            identity.v1.UserService/GetUserCount | jq .count)
          echo "Snapshots: $SNAP_COUNT, Identity: $IDENTITY_COUNT"
        Expect: equal (or within ±5 for in-flight signups).

      • Spot-check 10 random users: display_name matches.

    Step 5: Teardown temporary group (per RB-3 teardown).

    Step 6: Close incident.

  NOTE: The live consumer group (feed-user-events) does NOT need
  offset adjustment. It was never stopped and continues processing
  new user.updated events normally. The rebuild group just filled
  in any gaps.

================================================================================
RB-8  FULL PROCEDURE — REBUILD CHAT BLOCK-LIST (Compacted topic replay)
================================================================================

  SYMPTOMS TRIGGERING THIS PROCEDURE
    • Blocked users can still send messages (false negatives).
    • Unblocked users still blocked (false positives).
    • Chat's local block_list table corrupted.

  APPROACH
    Same as RB-7: user.events is compacted. Full replay from
    offset 0 rebuilds the block-list projection.

  ESTIMATED DURATION: ~2 min.

  STEPS

    Step 1: Temporary consumer group on user.events.
      REBUILD_GROUP="chat-blocklist-rebuild-$(date -u +%Y%m%d-%H%M)"

      helm install ${REBUILD_GROUP} ./charts/chat-event-consumer \
        --namespace chat \
        --set consumerGroup=${REBUILD_GROUP} \
        --set autoOffsetReset=earliest \
        --set topics='{user.events}' \
        --set handlers='{user.blocked,user.unblocked}' \
        --set replayMode=true \
        --set replicas=2

      The handlers filter means we only process block/unblock
      events, ignoring user.created/updated/followed etc.
      (Compacted topic means we still read every key, but we
      only act on block events. Cost is negligible.)

    Step 2: Monitor lag → 0.

    Step 3: Validation.
      • Compare a sample of block relationships:
          for pair in $(psql -h chat-pg ... \
            "SELECT blocker_id||':'||blocked_id FROM block_list \
             ORDER BY RANDOM() LIMIT 20" -tA); do
            BLOCKER=${pair%:*}; BLOCKED=${pair#*:}
            RESULT=$(grpcurl ... identity.v1.UserService/IsBlocked \
              -d "{\"actor_id\":\"$BLOCKER\",\"target_id\":\"$BLOCKED\"}")
            echo "$pair → Identity says: $RESULT"
          done
        Each sampled block in Chat's local table should be
        confirmed by Identity (blocked: true).

      • Reverse check: pick 20 blocks from Identity, verify
        they're in Chat's local table.

    Step 4: Teardown temp group.

    Step 5: Close incident.

================================================================================
RB-9  FULL PROCEDURE — REBUILD COMMUNITY MEMBER CACHE (Compacted replay)
================================================================================

  SYMPTOMS TRIGGERING THIS PROCEDURE
    • Chat: users not in community group chat despite being members.
    • Feed: non-members can post in a community (authz bypass).
    • Community member cache (in Chat's or Feed's local DB) diverges
      from Community service source of truth.

  APPROACH
    community.events is log-compacted. Full replay from offset 0.

  ESTIMATED DURATION: ~1 min (low volume — ~1000 communities,
  ~30k memberships).

  NOTE: This procedure applies to BOTH Chat's and Feed's local
  member cache. Run once per affected service.

  STEPS (for Chat — repeat with chart=feed-event-consumer for Feed)

    Step 1: Create temporary group.
      REBUILD_GROUP="chat-membership-rebuild-$(date -u +%Y%m%d-%H%M)"

      helm install ${REBUILD_GROUP} ./charts/chat-event-consumer \
        --namespace chat \
        --set consumerGroup=${REBUILD_GROUP} \
        --set autoOffsetReset=earliest \
        --set topics='{community.events}' \
        --set handlers='{community.member.joined,community.member.left,community.role.changed}' \
        --set replayMode=true \
        --set replicas=2

    Step 2: Monitor lag → 0.

    Step 3: Validation.
      • For 10 random communities, compare member count:
          for cid in $(... random 10 community IDs ...); do
            LOCAL=$(psql -h chat-pg -c \
              "SELECT COUNT(*) FROM community_members \
               WHERE community_id='$cid';" -tA)
            REMOTE=$(grpcurl ... \
              community.v1.MembershipService/GetMemberCount \
              -d "{\"community_id\":\"$cid\"}" | jq .count)
            echo "Community $cid: local=$LOCAL, remote=$REMOTE"
          done
        Expect: equal (or within ±1 for in-flight joins).

      • Spot-check: pick one (user, community) pair known to be
        a member → both IsMemberBatch gRPC and local table say yes.
        Pick one known NOT to be a member → both say no.

    Step 4: Teardown temp group.

    Step 5: Close incident.

================================================================================
RB-10  DEAD-LETTER TOPIC REPROCESSING
================================================================================

  WHEN TO USE
    • Alert fires: `kafka_dlt_messages_total{group="X"} > 0` and
      climbing.
    • Investigate WHY messages landed in the DLT before reprocessing.

  DLT CONTENTS
    Each message in <consumer-group>.dlt is the ORIGINAL event,
    wrapped with extra headers:
      x-dlt-original-topic     — where it came from
      x-dlt-original-partition — original partition
      x-dlt-original-offset    — original offset
      x-dlt-error-class        — the exception that caused failure
      x-dlt-error-message      — error detail
      x-dlt-retry-count        — how many retries before giving up
      x-dlt-first-failed-at    — timestamp of first failure
      x-dlt-last-failed-at     — timestamp of last failure

  PROCEDURE

    Step 1: Inspect the DLT contents.
      kafka-console-consumer --bootstrap-server $KAFKA_BOOTSTRAP \
        --topic <consumer-group>.dlt \
        --from-beginning --max-messages 20 \
        --property print.headers=true \
        --property print.key=true

      Categorise the errors:
        • Transient (timeout, connection refused): safe to retry.
        • Logic bug in consumer: fix bug FIRST, then retry.
        • Data error (malformed event): investigate producer;
          these may need to be skipped permanently.

    Step 2: FIX THE ROOT CAUSE BEFORE REPROCESSING.
      DLT reprocessing without fixing the cause just fills the DLT
      again. Deploy the consumer fix, verify it's healthy.

    Step 3: Choose a reprocessing strategy.

      OPTION A — Republish to original topic.
        For each DLT message, produce it back to its original
        topic (from x-dlt-original-topic header) with its
        original key. The live consumer will pick it up.

        ./ops/scripts/dlt-republish.sh \
          --dlt-topic <consumer-group>.dlt \
          --dry-run

        Review dry-run output, then run with --execute.

        CAUTION: This changes ordering. The republished event
        lands AFTER newer events. Only safe if the consumer is
        idempotent and ordering-insensitive for this event type.

      OPTION B — Direct reprocessing from DLT.
        Run a one-off consumer against the DLT itself:

        ./ops/scripts/dlt-reprocess.sh \
          --dlt-topic <consumer-group>.dlt \
          --consumer-chart ./charts/<consumer> \
          --dry-run

        This reads from the DLT and invokes the same processing
        logic directly, without republishing. Preserves that the
        event is "out of order" (it's being processed late).

      OPTION C — Skip permanently.
        For genuinely bad events that should never be processed:
        Record the DLT offsets in the incident ticket as
        "intentionally skipped". Do NOT delete from DLT — the
        30-day retention will clean up. Just don't reprocess them.

    Step 4: Verify DLT growth has stopped.
      kafka-run-class kafka.tools.GetOffsetShell \
        --bootstrap-server $KAFKA_BOOTSTRAP \
        --topic <consumer-group>.dlt --time -1
      Run twice, 5 min apart. Offset should not increase.

    Step 5: Close incident with root cause and fix description.

================================================================================
RB-11  NOTIFICATION CATCH-UP (Bounded Replay, Side-Effect Suppression)
================================================================================

  WHEN TO USE
    • Notification service was down for a period. Users missed
      push notifications for events during that window.
    • We want to re-deliver those notifications BUT NOT older ones
      (nobody wants notifications for last week's posts).

  CRITICAL RULE — SIDE-EFFECT SUPPRESSION

    Notification Service is the ONLY consumer with UNDOABLE external
    side effects (sends push notifications). Every other consumer
    just writes to a datastore (idempotent, can be overwritten).

    The notification consumer respects two config flags:

      replayMode                — when true, NO notifications are
                                   sent. Consumer reads and discards.
                                   Used for offset warm-up.

      notificationAgeLimitHours — suppress any notification where
                                   event.occurred_at is older than
                                   this many hours. Default: 24.

    Together, these let us reset offsets back in time while only
    actually SENDING notifications for events newer than the limit.

  ESTIMATED DURATION: depends on backlog size. For a 1-hour outage
  at peak (500 msg/s × 3600 ≈ 1.8M events), catch-up takes ~30 min
  with 4 consumer replicas.

  STEPS

    Step 1: Determine the outage window.
      From alerting / logs:
        OUTAGE_START = <ISO timestamp>  (when consumer went down)
        OUTAGE_END   = <ISO timestamp>  (when consumer came back)

    Step 2: Check if live consumer already caught up.
      kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
        --group notification-service --describe

      If lag is 0 AND the consumer resumed from its last committed
      offset, it's already processing the backlog. Just monitor.
      You may need to TEMPORARILY raise notificationAgeLimitHours
      to cover the outage window (step 3 below), then skip to
      step 5.

      If lag is 0 but the consumer was misconfigured and committed
      ahead (skipped events), proceed to step 3.

    Step 3: Calculate the age limit to cover the outage.
      HOURS_SINCE_START=$(( ($(date +%s) - $(date -d "$OUTAGE_START" +%s)) / 3600 + 1 ))
      # +1 for safety margin.

    Step 4: Rewind the LIVE consumer group to OUTAGE_START.
      (Per RB-2, but with --to-datetime.)

      kubectl scale deployment/notification-service --replicas=0 \
        -n notification

      Wait for 0 active members.

      kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
        --group notification-service \
        --all-topics \
        --reset-offsets \
        --to-datetime ${OUTAGE_START} \
        --execute

    Step 5: Restart with extended age limit.
      helm upgrade notification-service ./charts/notification \
        --namespace notification \
        --set notificationAgeLimitHours=${HOURS_SINCE_START} \
        --reuse-values

      kubectl scale deployment/notification-service --replicas=4 \
        -n notification

    Step 6: Monitor.
      • Consumer lag → 0.
      • `notifications_sent_total` metric increases (events within
        the age limit are being delivered).
      • `notifications_suppressed_age_total` increases for events
        older than the limit (if any were rewound past the limit).
      • NO user complaints about very-old notifications (if
        complaints: age limit is too high — check HOURS_SINCE_START
        calculation).

    Step 7: After catch-up (lag = 0), reset age limit to default.
      helm upgrade notification-service ./charts/notification \
        --namespace notification \
        --set notificationAgeLimitHours=24 \
        --reuse-values

    Step 8: Close incident.

================================================================================
RB-12  VERIFICATION CHECKS (Record Counts, Checksums, Spot Checks)
================================================================================

  Run after any rebuild to verify correctness BEFORE cutover.

── 12.1  COUNT PARITY CHECK ────────────────────────────────────────

  Principle: the rebuilt projection's record count should match
  the source of truth (within a small delta for in-flight events).

  ┌─────────────────────────┬──────────────────────────────────────┐
  │ Projection              │ Count comparison                     │
  ├─────────────────────────┼──────────────────────────────────────┤
  │ Search index (ES)       │ ES _count vs PG COUNT(*) posts       │
  │                         │ WHERE deleted_at IS NULL             │
  │                         │ AND created_at > NOW()-'30 days'     │
  │                         │ Tolerance: ±1%                       │
  │ Author snapshots        │ PG COUNT(*) author_snapshots vs      │
  │ (Feed PG)               │ Identity gRPC GetUserCount           │
  │                         │ Tolerance: ±5 records                │
  │ Block list (Chat)       │ Chat PG COUNT(*) block_list vs       │
  │                         │ Identity PG COUNT(*) blocks          │
  │                         │ (direct query on Identity replica    │
  │                         │  or via an ops-only gRPC)            │
  │                         │ Tolerance: ±5 records                │
  │ Member cache (Chat/Feed)│ Per community: local COUNT vs        │
  │                         │ Community gRPC GetMemberCount        │
  │                         │ Tolerance: ±1 record per community   │
  │ Feed timelines (Redis)  │ (No direct count parity — see spot   │
  │                         │  checks below)                       │
  └─────────────────────────┴──────────────────────────────────────┘

  If count delta exceeds tolerance:
    • Check if Kafka tail has lag > 0 (still catching up).
    • Check if snapshot query had wrong cutoff timestamp.
    • Check DLT for errors during rebuild.
    • DO NOT cut over until resolved.

── 12.2  CHECKSUM CHECK (optional, for high-stakes rebuilds) ──────

  For projections where count parity isn't enough (e.g., we're
  worried about data corruption, not just missing records).

  Example — Search index content checksum:
    # PG side: concatenate and hash a deterministic field
    psql -h feed-pg-replica -c \
      "SELECT md5(string_agg(id||body_preview, '' ORDER BY id)) \
       FROM (SELECT id, LEFT(body, 280) as body_preview \
             FROM posts WHERE deleted_at IS NULL \
             AND created_at > NOW()-'30 days' \
             ORDER BY id LIMIT 10000) s;"

    # ES side: fetch same 10k docs, compute same hash
    ./ops/scripts/es-checksum.sh --index ${NEW_INDEX} \
      --field body_preview --order-by id --limit 10000

    Compare hashes. Match = content-level consistency for the
    sampled set.

── 12.3  SPOT CHECKS (always do at least 10) ──────────────────────

  Pick random records and verify end-to-end.

  Search:    Pick 10 recent post IDs from PG. Search ES for each
             by ID. All must be found with correct body_preview.

  Author snapshots: Pick 10 random user_ids from Identity. Compare
             display_name in Identity vs author_snapshots. Must match.

  Block list: Pick 10 (blocker, blocked) pairs from Identity. All
             must exist in Chat's local block_list. Then pick 10
             random (userA, userB) pairs that are NOT blocked.
             None must exist in block_list.

  Timelines: Pick 5 active users. For each:
             • Redis ZREVRANGE timeline:{uid} 0 19 (top 20 posts).
             • PG query: top 20 posts from their followees.
             • Compute set intersection. Expect ≥ 90% overlap.
               (Not 100% because of celebrity pull-merge, recency,
                and community posts. <50% indicates a problem.)

── 12.4  FUNCTIONAL SMOKE TEST ────────────────────────────────────

  After cutover, exercise the full path:

  Search:    Create a new post (via API). Wait 10s. Search for a
             unique word from the post body. Expect: result found.

  Timelines: Have a test user follow another test user. Second user
             posts. Wait 5s. First user's timeline includes the post.

  Block list: Block a test user. Wait 5s. Attempt to send message.
             Expect: 403.

  If any smoke test fails → RB-14 (rollback).

================================================================================
RB-13  TROUBLESHOOTING — COMMON FAILURES & FIXES
================================================================================

  ┌─────────────────────────────────┬──────────────────────────────────────┐
  │ Symptom                         │ Likely cause → fix                   │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Offset reset fails with         │ Consumer group has active members.   │
  │ "Group has active members"      │ → Verify deployment scaled to 0.     │
  │                                 │   Check for orphaned pods.           │
  │                                 │   Wait for session.timeout.ms        │
  │                                 │   (default 45s) for zombie           │
  │                                 │   members to be kicked.              │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Rebuild consumer lag not        │ • Consumer pods CPU-bound → scale    │
  │ decreasing (stuck)              │   replicas (up to partition count).  │
  │                                 │ • Downstream (ES/Redis/PG) saturated │
  │                                 │   → check target metrics; throttle   │
  │                                 │   consumer batch size.               │
  │                                 │ • Consumer crashing in a loop →      │
  │                                 │   check logs; check DLT.             │
  │                                 │ • Stuck on a poison message →        │
  │                                 │   check logs for same offset         │
  │                                 │   repeating; skip via offset shift.  │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Rebuild consumer reading but    │ • replayMode flag not set → consumer │
  │ writing to LIVE projection      │   using live target. STOP            │
  │ instead of shadow               │   IMMEDIATELY, check helm values.    │
  │                                 │   May need to roll back live         │
  │                                 │   projection.                        │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Count parity off by >5%         │ • Kafka retention expired some       │
  │                                 │   events → fall back to snapshot     │
  │                                 │   strategy (RB-5.ALT, RB-4).         │
  │                                 │ • DLT accumulated during rebuild →   │
  │                                 │   process DLT (RB-10) then recount.  │
  │                                 │ • Wrong snapshot cutoff timestamp →  │
  │                                 │   verify query bounds.               │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ HWM offset "out of range"       │ Kafka retention deleted the offset   │
  │ when setting tail start         │ between HWM capture and tail start.  │
  │                                 │ → The snapshot took too long.        │
  │                                 │   For topics with short retention,   │
  │                                 │   record HWM IMMEDIATELY before      │
  │                                 │   starting snapshot, not before      │
  │                                 │   preparation. If gap persists:      │
  │                                 │   accept data loss for events in     │
  │                                 │   [expired-offset, snapshot-start]   │
  │                                 │   and document in incident.          │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Temp consumer group won't       │ Consumer still has active members.   │
  │ delete                          │ → Scale deployment to 0, wait 60s,   │
  │                                 │   retry delete.                      │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Live consumer lag spikes after  │ Expected if cutover changed the      │
  │ cutover                         │ target and live consumer is now      │
  │                                 │ writing to a new index/table.        │
  │                                 │ Should recover in minutes.           │
  │                                 │ If not recovering: check target      │
  │                                 │ capacity, consumer errors.           │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Schema Registry rejects events  │ Producer using a schema version that │
  │ during replay                   │ was never registered (or was deleted)│
  │                                 │ → Check SR subject versions.         │
  │                                 │   Re-register the old schema if      │
  │                                 │   needed (it's in the event-schemas  │
  │                                 │   git history).                      │
  ├─────────────────────────────────┼──────────────────────────────────────┤
  │ Users receiving old             │ notificationAgeLimitHours too high   │
  │ notifications after RB-11       │ or not set.                          │
  │                                 │ → Verify helm values. Set            │
  │                                 │   replayMode=true temporarily to     │
  │                                 │   stop all sends, recalculate limit, │
  │                                 │   redeploy.                          │
  └─────────────────────────────────┴──────────────────────────────────────┘

================================================================================
RB-14  EMERGENCY ABORT / ROLLBACK PROCEDURES
================================================================================

  USE WHEN
    • Verification (RB-12) fails.
    • Rebuild is making things worse (e.g., corrupting live data).
    • Procedure is taking >3× estimated time with no clear path
      forward.

── 14.1  ABORT BEFORE CUTOVER (no user-visible impact) ─────────────

  If cutover (alias swap / offset reset on live group) has NOT
  happened, abort is clean:

    Step 1: Stop and delete the temp consumer group.
      helm uninstall ${REBUILD_GROUP}
      kafka-consumer-groups --delete --group ${REBUILD_GROUP}

    Step 2: Delete any shadow targets (new ES index, shadow table).
      curl -X DELETE "http://es:9200/${NEW_INDEX}"
      psql ... "DROP TABLE IF EXISTS author_snapshots_rebuild;"

    Step 3: Verify live consumer is healthy and processing normally.

    Step 4: Update incident with abort reason. Schedule retry.

── 14.2  ROLLBACK AFTER CUTOVER (user-visible, act fast) ───────────

  SEARCH INDEX ROLLBACK
    • The old index still exists (24h safety window).
    • Swap alias back:
        curl -X POST "http://es:9200/_aliases" -d '{
          "actions": [
            { "remove": { "index": "'${NEW_INDEX}'",
                          "alias": "posts-live" }},
            { "add":    { "index": "'${OLD_INDEX}'",
                          "alias": "posts-live" }}]}'
    • Revert live indexer's targetIndex to ${OLD_INDEX}.
    • Search immediately serves from old index.
    • Old index is stale by however long the rebuild took. Live
      indexer will catch up as it processes from its current offset.

  FEED TIMELINE ROLLBACK
    • There is NO clean rollback for timelines (Redis was flushed).
    • Best option: re-run RB-6 from Step 1 after fixing whatever
      went wrong.
    • Degraded mode in the meantime: Feed Service's timeline read
      falls back to pull-model (PG query) automatically when Redis
      timeline is empty. Slower but functional.

  AUTHOR SNAPSHOTS / BLOCK LIST / MEMBER CACHE ROLLBACK
    • These are upsert-based; rebuild doesn't destroy data, just
      updates it. A "bad" rebuild (e.g., wrote wrong values) is
      fixed by running the rebuild again with corrected logic.
    • No explicit rollback — re-run the (fixed) procedure.

  OFFSET RESET ROLLBACK
    • If you saved the pre-reset offsets (RB-1 step 5), you can
      restore them:
        /ops/scripts/set-offsets.sh \
          --from-file /tmp/cg-before-${INCIDENT_ID}.txt \
          --group <group-name> \
          --execute
    • If you did NOT save them (you skipped pre-flight — don't):
      there is no rollback. The group is now at the new offsets.

================================================================================
RB-15  POST-INCIDENT CLEANUP
================================================================================

  Execute within 24 hours of closing the incident.

  ☐  1. All temporary consumer groups deleted. Verify:
           kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
             --list | grep rebuild
         Expect: no output.

  ☐  2. All shadow targets deleted (old ES indexes past 24h safety,
         shadow DB tables, temp Redis keyspaces).

  ☐  3. Helm values reset to defaults (notificationAgeLimitHours,
         any temporary overrides). Verify:
           helm get values <release> -n <ns>
         Compare to checked-in values.yaml.

  ☐  4. HWM snapshot files and pre-reset offset files attached
         to incident ticket (for audit trail), then cleaned from
         /tmp.

  ☐  5. If this runbook had to be deviated from: file a PR to
         update the runbook with what was actually done.

  ☐  6. Post-incident review scheduled within 1 week.

  ☐  7. #astu-connect-oncall notified: "${PROCEDURE} cleanup
         complete for ${INCIDENT_ID}."

════════════════════════════════════════════════════════════════════════════════
QUICK REFERENCE — CHEAT SHEET
════════════════════════════════════════════════════════════════════════════════

  # Describe a consumer group
  kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
    --group <G> --describe

  # Reset offsets (dry-run first!)
  kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
    --group <G> --topic <T> --reset-offsets \
    --to-datetime <ISO> --dry-run   # then --execute

  # Delete a consumer group (must have 0 members)
  kafka-consumer-groups --bootstrap-server $KAFKA_BOOTSTRAP \
    --group <G> --delete

  # Get latest offsets (HWM) per partition
  kafka-run-class kafka.tools.GetOffsetShell \
    --bootstrap-server $KAFKA_BOOTSTRAP --topic <T> --time -1

  # Peek at a DLT
  kafka-console-consumer --bootstrap-server $KAFKA_BOOTSTRAP \
    --topic <G>.dlt --from-beginning --max-messages 20 \
    --property print.headers=true

  # ES alias atomic swap
  curl -X POST es:9200/_aliases -d '{"actions":[
    {"remove":{"index":"<OLD>","alias":"<A>"}},
    {"add":   {"index":"<NEW>","alias":"<A>"}}]}'

  # Redis timeline size for a user
  redis-cli ZCARD timeline:<uid>

════════════════════════════════════════════════════════════════════════════════
END OF RUNBOOK
════════════════════════════════════════════════════════════════════════════════
