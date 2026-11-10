---
project_id: beacon
status: shipped
---

# Beacon

## Overview

Beacon is a distributed uptime monitoring platform that checks
websites and APIs at configurable intervals, records response
times, calculates uptime, detects incidents, and sends email
alerts when services go down or recover.

It was built to explore queue-driven architectures, concurrent
job processing, reliable scheduling, incident lifecycles, and
historical monitoring analytics.

## Architecture

Beacon uses a Turborepo monorepo with a Next.js dashboard,
an Express API, a PostgreSQL database accessed through Prisma,
Redis with BullMQ, and a dedicated email notifier using Resend.

### Monitoring workflow

1. The scheduler polls PostgreSQL for active monitors whose
   nextCheckAt timestamp is due.
2. It atomically claims due monitors using PostgreSQL
   FOR UPDATE SKIP LOCKED, advances nextCheckAt, and records
   pending jobs in the PendingCheck outbox.
3. After the database operation succeeds, the scheduler drains
   outbox entries and enqueues check jobs in BullMQ through Redis.
4. Workers consume check jobs with configurable concurrency
   (default 10), send HTTP requests, measure response times,
   and persist check results through Prisma.
5. HTTP 4xx/5xx responses and request failures such as timeouts
   are classified as DOWN checks. Successful 2xx/3xx responses
   are classified as UP.
6. The worker updates failure tracking and incident state.
   An incident opens after three consecutive failed checks.
   A successful check resets the failure counter and resolves
   any open incident.
7. When an incident opens or resolves, the worker enqueues an
   alert notification job.
8. The notifier consumes alert jobs and sends email through
   Resend. Jobs that exhaust their configured three attempts
   are recorded in the FailedJob database table.

### Main components

- Next.js: monitoring dashboard and analytics.
- Express API: REST endpoints, business logic, and JWT authentication.
- PostgreSQL and Prisma: persistent data and relational integrity.
- Scheduler: finds monitors due for their next check.
- Redis and BullMQ: asynchronous job queues, retries, and concurrency.
- Worker: performs HTTP checks and processes their results.
- Notifier: delivers incident emails through Resend.

## Key Engineering Decisions

### Why use a queue instead of running checks inside the API?

Running HTTP checks inside API request handlers would couple
external network latency and timeouts to the API's request
processing. Separating the scheduler, queue, and workers allows
checks to execute asynchronously and worker concurrency to be
managed independently of API traffic.

### Why PostgreSQL?

Beacon manages related entities such as users, monitors,
check history, and incidents. PostgreSQL supports relational
constraints, transactions, and indexes for these relationships
and for scheduler queries.

The composite index on (active, nextCheckAt) supports finding
active monitors that are due for their next check.

### How does Beacon prevent multiple schedulers from scheduling the same monitor?

The original implementation used a plain read followed by
an update. Two scheduler replicas could read the same due
monitors before either updated their nextCheckAt timestamps,
leading to duplicate jobs.

The revised implementation uses FOR UPDATE SKIP LOCKED to
claim rows without competing schedulers processing the same
rows in that transaction. It also updates nextCheckAt and
creates PendingCheck outbox entries in the same database
operation.

### Why use a transactional outbox?

Updating nextCheckAt and then enqueueing a Redis job creates
a failure window: the scheduler could crash after the database
update but before publishing the job.

Beacon stages pending checks in the PendingCheck table as part
of the database operation. The scheduler dispatches those
entries to BullMQ and deletes them after successful enqueueing.
On startup, the outbox drainer attempts to process entries
left behind by a previous crash.

This provides a recovery mechanism for the database-to-queue
dispatch gap. It should not be described as a universal
exactly-once delivery guarantee.

### Why send only two emails per incident?

Beacon sends an email when an incident opens and another
when it resolves. It intentionally omits periodic outage
reminders in V1 to reduce inbox clutter and unnecessary
email API usage.

### How does notification deduplication work?

The notifier uses a Redis-backed key based on the incident
and event type, along with Resend's Idempotency-Key support.
The Redis deduplication key has a 300-second TTL.

## Engineering Challenge: Double Scheduling

### Problem

Two scheduler replicas could select the same three due monitors,
enqueueing six jobs in total instead of three.

### Initial approach

The initial plain-select-then-update implementation did not
safely claim rows against concurrent schedulers.

### Solution

The revised implementation combines atomic row claiming through
FOR UPDATE SKIP LOCKED with a transactional outbox.

### Documented experiment

The README documents a live reproduction with two scheduler
instances and three due monitors:

- Before the fix: six jobs were queued.
- After the fix: three jobs were queued.
- The PendingCheck outbox was empty after successful draining.

This result demonstrates the specific tested scenario. It is
not a general throughput benchmark.

## Database and Data Retention

The main data model includes:

- User: owns monitors.
- Monitor: stores target URL, interval, active state, and
  scheduling timestamps.
- Check: stores individual monitoring results and response times.
- Incident: records the start and resolution of an outage.
- PendingCheck: temporarily stages scheduled jobs for dispatch.
- FailedJob: records jobs that exhaust their configured retries.

Check history older than 30 days is removed by a scheduled
data-retention job.

## Deployment

The repository provides a monolith start script that launches
the API, worker, scheduler, and notifier as separate processes
under concurrently.

The documented deployment architecture uses Vercel for the
Next.js frontend, Neon PostgreSQL, Upstash Redis, and a Render
web service for backend processes. A Docker Compose deployment
configuration is also included.

## Connection Management Limitation

The Prisma client wrapper currently instantiates PrismaClient
without explicit pool-limit options in that wrapper. Actual
connection behaviour depends on the deployed database connection
string and provider configuration.

## Limitations and Future Work

Not implemented in V1:

- Public status pages.
- SSL/TLS certificate expiration monitoring.
- Multi-region probing.
- Prometheus and OpenTelemetry metrics.
- Pre-built Grafana dashboards.
- Queue partitioning and time-partitioned check storage.

These are future improvements, not current capabilities.

## Testing and Verification

The repository includes Vitest tests covering API routes,
shared utilities, worker incident detection, and notifier
behaviour including email flow and idempotency.

The README also documents the live two-scheduler experiment
described above. Treat it separately from automated test
coverage.

## Project Links

- Repository: https://github.com/Arjun8242/Beacon
- Live application: https://beacon-sigma-henna.vercel.app/