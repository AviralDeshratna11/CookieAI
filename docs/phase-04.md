# Phase 4 episodes

Migration 0003 persists episode payloads and atomic evidence links. EpisodeService records attributed tool observations with intent, parameters, output, errors, retry, latency and outcome; composes deterministic event summaries; segments by session/time boundary; and recalls episodes through authorized memory search. Every synthesized record inherits evidence restrictions. Empty unsupported episodes are rejected.

Acceptance: 49 tests passed, including real PostgreSQL, before Phase 5. Tests verify failure/success retention, evidence links, source-deletion propagation and segmentation. Example: POST `/v1/episodes` with title, trigger, goal, context and actual tool attempts. The deterministic segmenter is available through `EpisodeService.segment`.

Limits: automatic task-boundary segmentation beyond session/time requires an explicit task signal or configured model. No biological episodic reconstruction is claimed.
