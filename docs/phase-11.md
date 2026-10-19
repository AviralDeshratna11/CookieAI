# Phase 11 memory dynamics

Migration 0009 adds thematic clusters, membership, prospective memories and open loops. Decay changes strength and ACTIVE/DORMANT/ARCHIVED/EXPIRED eligibility, never physically deletes or increases truth. Salient, important and outcome-reinforced memories decay more slowly; pinned records are protected. Deep recall includes dormant/archived records. Entity/topic clusters contain regenerable summaries, centroids, importance and provenance. Deleting a member removes its dependent summary.

Prospective triggers activate context on time/date/entity/event/context/recorded goal state; they never send external notifications. Open loops retain originating session and optional goal. Example: POST `/v1/prospective` or `/v1/open-loops`; pin via POST `/v1/memory/{id}/pin`; service methods run decay, cluster maintenance and trigger evaluation.

Acceptance verifies archival with deep recall, truth invariance, pinned retention, one-shot contextual triggers and deletion of derived cluster text. Limits: decay and cluster refresh are bounded maintenance operations; scheduling/retries and operational hardening are finalized in the worker phase.
