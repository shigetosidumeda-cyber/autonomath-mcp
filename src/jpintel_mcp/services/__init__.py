"""Cross-cutting services for the trust 8-pack and adjacent surfaces.

Today this package only carries `cross_source` (mig 101 #6). The package
exists so the API router (`api/trust.py`) and the hourly cron
(`scripts/cron/cross_source_check.py`) share one implementation rather
than re-deriving the agreement math in two places.
"""
