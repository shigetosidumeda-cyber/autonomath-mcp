# Acceptance test package — Wave 20 B12 50/50 gate substrate.
#
# Tests in this directory are the *minimal blocker* gates for shipping
# a release. Each test asserts a high-signal contract that, when broken,
# blocks a release tag from being cut. The full 286-test acceptance
# suite (DEEP-22..65, scattered across `tests/test_*.py`) is the
# *evidence* substrate; this directory is the *gate*.
#
# Memory anchor: feedback_completion_gate_minimal — 40+ item all-green
# gate is forbidden, this directory must stay at the minimum 5-8 blocker
# count plus 50/50 extension surface for the Wave 19/20 endpoint cohort.
