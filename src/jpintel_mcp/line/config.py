"""LINE bot configuration.

Environment variables are the only configuration surface — nothing is
baked into source. An empty channel secret or access token must NOT crash
import; the webhook handler raises 503 at request time instead so a dev
running the API locally without LINE env vars can still boot.

Secrets
-------
LINE_CHANNEL_SECRET
    HMAC SHA-256 secret used to verify `X-Line-Signature` on incoming
    webhook POSTs. Found in the LINE Developers Console → Messaging API
    channel → Channel secret.

LINE_CHANNEL_ACCESS_TOKEN
    Long-lived channel access token used as Bearer auth on outbound API
    calls (reply / push / rich-menu upload). Rotate via the LINE
    Developers Console; the app reads the env on each restart.

LINE_STRIPE_PRICE_ID
    Stripe Price id for the LINE bot ¥500/月 flat subscription. Separate
    from the per-request Price used by the core API so accounting can
    split revenue by product line. Idempotently created by
    `scripts/setup_stripe_line_product.py`.

LINE_BOT_SUCCESS_URL / LINE_BOT_CANCEL_URL
    Where Stripe Checkout returns the user. Defaults land on
    jpcite.com/line.html.

LINE_OA_FRIEND_URL
    The https://lin.ee/XXXX URL shown on the landing page + QR. Must be
    set after the LINE OA is registered; rendered as-is in site copy.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    channel_secret: str = Field(default="", alias="LINE_CHANNEL_SECRET")
    channel_access_token: str = Field(default="", alias="LINE_CHANNEL_ACCESS_TOKEN")

    # Stripe — flat ¥500/月 (税込 ¥550) Price (recurring, not metered).
    # Separate from STRIPE_PRICE_PER_REQUEST (the core API's ¥3/req metered
    # Price) so revenue can be split per product line.
    stripe_price_id: str = Field(default="", alias="LINE_STRIPE_PRICE_ID")

    success_url: str = Field(
        default="https://jpcite.com/line.html?checkout=success",
        alias="LINE_BOT_SUCCESS_URL",
    )
    cancel_url: str = Field(
        default="https://jpcite.com/line.html?checkout=cancel",
        alias="LINE_BOT_CANCEL_URL",
    )

    # Public friend-add URL (https://lin.ee/...). Rendered on the landing
    # page and in the "menu" quick reply. Empty → the landing page falls
    # back to a "coming soon" note so we don't ship a dead link.
    oa_friend_url: str = Field(default="", alias="LINE_OA_FRIEND_URL")

    # Internal REST base for the prescreen call. In-process callers would
    # normally import `run_prescreen` directly, but the LINE webhook runs
    # in the same FastAPI process so we do that too. This field is a safety
    # net for a future out-of-process worker.
    internal_api_base: str = Field(default="http://127.0.0.1:8080", alias="LINE_INTERNAL_API_BASE")

    # Monthly free query quota per LINE user. 10 is the product decision;
    # do not raise without revisiting the ¥500 price (at 10 free + ¥500
    # flat, the marginal user margin vs the core ¥3/req API stays
    # positive under our demand assumptions).
    free_queries_per_month: int = Field(default=10, alias="LINE_FREE_QUERIES_PER_MONTH")


line_settings = LineSettings()
