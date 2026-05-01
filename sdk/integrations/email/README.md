# jpcite — Email digest cron

> Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708) · brand: jpcite ·
> API base: `https://api.jpcite.com` · cost: **¥3/req** metered (税込 ¥3.30)

A cron-friendly Python script that runs each customer's saved searches
once a month and emails an HTML + plain-text digest to the customer.

```text
+--------------+        +----------------------+        +-----------------+
|  cron (host) | -----> | email_digest.py      | -----> | SendGrid / SES /|
|  (monthly)   |        |  - fetch saved       |        | Mailchimp send  |
|              |        |  - run REST searches |        | (customer's     |
|              |        |  - render Jinja2     |        |  transport key) |
+--------------+        +----------------------+        +-----------------+
```

The digest:

- Calls `GET /v1/me/saved_searches` once per customer (saved-search CRUD is free; each executed saved search is ¥3).
- Calls each saved search's declared endpoint once (¥3 per search).
- Renders a Jinja2 HTML template + plain-text fallback.
- Hands the prepared payload to a transport stub (SendGrid v3, SES v2,
  Mailchimp Transactional). The stub **does not** send; it returns the
  payload so the customer's cron wrapper issues the real HTTPS POST
  with their own credentials.

## Cost model

Each saved search execution = 1 jpcite request = ¥3 (税込 ¥3.30). A
typical 税理士 顧問先 fan-out (cohort #2):

| Saved searches | Customers | Cron frequency | Monthly cost |
| -------------- | --------- | -------------- | ------------ |
| 4 / customer   | 100       | monthly        | ¥1,200       |
| 8 / customer   | 50        | monthly        | ¥1,200       |
| 4 / customer   | 100       | weekly         | ¥4,800       |

The transport stub adds zero markup. The SendGrid / SES / Mailchimp
send itself is billed by your provider, not by jpcite.

## Connect to your email provider (3 transport options)

`email_digest.py` exposes three "prepare" functions. None of them
issue HTTPS — they return the payload so you can plug it into your
own runtime.

```python
from email_digest import (
    build_digest_for_customer,
    prepare_sendgrid_send,
    prepare_ses_send,
    prepare_mailchimp_send,
)
import httpx, os

digest = build_digest_for_customer(
    customer_name="顧問先 A",
    api_key=os.environ["JPCITE_API_KEY"],
)

# Option 1: SendGrid
prepared = prepare_sendgrid_send(
    digest=digest,
    to_email="customer@example.co.jp",
    from_email="info@bookyou.net",
    api_key=os.environ["SENDGRID_API_KEY"],
)
httpx.post(prepared.url, headers=prepared.headers, json=prepared.body, timeout=15)

# Option 2: SES (use boto3 instead of raw POST in production)
prepared = prepare_ses_send(
    digest=digest,
    to_email="customer@example.co.jp",
    from_email="info@bookyou.net",
    region="ap-northeast-1",
)

# Option 3: Mailchimp Transactional
prepared = prepare_mailchimp_send(
    digest=digest,
    to_email="customer@example.co.jp",
    from_email="info@bookyou.net",
    api_key=os.environ["MAILCHIMP_API_KEY"],
)
```

## Cron setup

Pick the platform you already run on. Examples below assume you have
a cron host with the digest module on `PYTHONPATH` and the relevant
env vars (`JPCITE_API_KEY`, `SENDGRID_API_KEY`, etc.) available.

### Linux/macOS crontab (monthly, 09:00 JST first day)

```cron
0 0 1 * *  /usr/bin/python /opt/jpcite/sdk/integrations/email/run_monthly.py >> /var/log/jpcite-digest.log 2>&1
```

`run_monthly.py` is a thin script you write that loops over your
customer list and calls `build_digest_for_customer` + a transport
prepare function.

### GitHub Actions (monthly)

```yaml
name: jpcite-monthly-digest
on:
  schedule: [{ cron: "0 0 1 * *" }]  # 1st of month, 09:00 JST
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install httpx jinja2
      - env:
          JPCITE_API_KEY: ${{ secrets.JPCITE_API_KEY }}
          SENDGRID_API_KEY: ${{ secrets.SENDGRID_API_KEY }}
        run: python run_monthly.py
```

### Cloud Scheduler + Cloud Run

Wrap `email_digest.py` in a small Flask handler, deploy to Cloud Run,
then add a Cloud Scheduler job that POSTs to it monthly.

## What the cron does *not* do

- **No LLM call.** Everything is deterministic Jinja2 + REST.
- **No state.** No SQL, no Redis, no `~/.cache/`. Every run is
  reproducible from API key + customer name + clock.
- **No transport secrets.** Bookyou never holds your SendGrid / SES /
  Mailchimp keys. The transport stubs return the payload; you wire it
  into your own runtime.

## File map

```
email_digest.py                 # cron entry + transport stubs
templates/email_digest.html     # HTML body (Jinja2)
templates/email_digest.txt      # plain-text fallback (Jinja2)
tests/test_email_digest_smoke.py
```

## License

MIT. See `LICENSE` in the repo root.

## 不具合報告

info@bookyou.net (Bookyou株式会社, 適格請求書発行事業者番号 T8010001213708)
