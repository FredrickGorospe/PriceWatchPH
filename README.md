# PriceWatchPH

PriceWatchPH is a portfolio project for tracking Philippine secondhand PC
hardware prices. It ingests listing observations, resolves noisy titles to
canonical SKUs, builds rolling per-SKU price evidence, and flags unusually
low asking prices for review.

## What is implemented

- Immutable raw-listing ingestion with provenance and pseudonymised seller data
- Deterministic SKU resolution and administrator review workflows
- Decimal-safe rolling price baselines and deal scoring
- Django REST Framework APIs with a React review and outcome interface
- Session authentication, CSRF protection, and administrator login throttling
- Governed deal outcome tracking and Telegram alert delivery
- Cron-driven processing through Django management commands
- PostgreSQL 16 constraints and triggers for critical integrity boundaries
- Verified PostgreSQL backup and scratch-restore tooling
- Production-oriented Gunicorn, WhiteNoise, and Docker Compose runtime

## Stack

- Python 3.12, Django 5.2, and Django REST Framework
- PostgreSQL 16
- React, TypeScript, and Vite
- Docker Compose and Gunicorn

## Validation

The repository includes backend acceptance tests against PostgreSQL, frontend
unit tests, linting and production-build checks, migration-drift checks, and
deployment configuration tests.

Public HTTPS/TLS deployment is pending. This repository does not claim a live
public production service.
