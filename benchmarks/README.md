# Benchmarks Boundary

`benchmarks/` contains evaluation assets and benchmark reports. These files are
valuable for trust, but they must not be turned into broad marketing claims
without checking scope and caveats.

## Commit

- benchmark definitions
- deterministic scoring code
- small representative fixtures
- compact reports with methodology and limitations

## Keep Internal Or Caveated

- seed estimates that are not validated
- raw benchmark runs that are easy to regenerate
- token-only ROI claims
- results from endpoints that are not wired in production

## Product Value

The strongest reusable assets are:

- `jcrb_v1/`: deterministic Japanese compliance reasoning benchmark
- `composite_vs_naive/`: composite-call vs multi-call engineering benchmark
- `sims/`: persona ROI simulations, when framed around verification time

Use these to prove workflow quality and verification-time reduction. Do not use
them to promise universal savings, guaranteed accuracy, or contractual SLA.
