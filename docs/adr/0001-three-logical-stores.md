# Three logical stores in PostgreSQL

Accepted. The reference guide separates main memory vectors, entity vectors and relational audit/rolling messages. We preserve these responsibilities and use PostgreSQL with pgvector rather than independent vector databases and SQLite. The master prompt explicitly allows this MVP deployment. Co-location provides transactional consistency; adapters may later externalize projections through the outbox. Redis never becomes a source of truth.
