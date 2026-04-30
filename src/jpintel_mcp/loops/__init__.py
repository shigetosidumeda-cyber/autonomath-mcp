"""Operator-side review CLIs that gate auto-extension pipelines.

Spec posture: every weekly cron that mines candidate edits to the live
corpus (e.g. `scripts/cron/alias_dict_expansion.py`) lands its proposals
in a queue table. Review CLIs in this package are the ONLY surface that
promotes a queue row to the production table — production write 必ず
review 後 (Plan §8.7).
"""
