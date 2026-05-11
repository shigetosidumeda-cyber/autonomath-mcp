-- target_db: autonomath
-- migration 214_invoice_houjin_refs
-- generated_at: 2026-05-11
-- author: 8-source cross-corpus join layer (jpcite v0.3.4)
--
-- Purpose
-- -------
-- Join table: 適格請求書発行事業者 x 法人番号 (invoice_registrants x
-- houjin). One row per (invoice_id, houjin_bangou) pair with the NTA
-- `registered_at` (ISO date) for time-series filtering. Bridges
-- T-番号 to the 13-digit 法人番号 for 取引先 due-diligence walks.
--
-- FK note
-- -------
-- jpi_invoice_registrants.invoice_registration_number (TEXT) is the
-- canonical mirror PK. houjin_bangou is the 13-digit corporate number;
-- not FK'd to keep one row per (T-番号, houjin) observation even if a
-- houjin row is dormant on jpi_houjin_master.
--
-- Idempotency
-- -----------
-- CREATE TABLE / INDEX IF NOT EXISTS. No seed data.
--
-- DOWN
-- ----
-- Companion: 214_invoice_houjin_refs_rollback.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS invoice_houjin_refs (
    invoice_id     TEXT NOT NULL REFERENCES jpi_invoice_registrants(invoice_registration_number),
    houjin_bangou  TEXT NOT NULL,
    registered_at  TEXT,
    created_at     INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    PRIMARY KEY (invoice_id, houjin_bangou)
);

CREATE INDEX IF NOT EXISTS idx_invoice_houjin_refs_houjin
    ON invoice_houjin_refs(houjin_bangou);

CREATE INDEX IF NOT EXISTS idx_invoice_houjin_refs_registered
    ON invoice_houjin_refs(registered_at)
    WHERE registered_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_invoice_houjin_refs_created_at
    ON invoice_houjin_refs(created_at);
