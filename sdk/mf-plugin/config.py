"""env 検証 + MF Cloud OAuth エンドポイント定数。

参考:
  - https://developers.biz.moneyforward.com/docs/common/oauth/app-portal-overview/
  - https://developers.biz.moneyforward.com/docs/common/getting-started-moneyforward-cloud-apis/
  - https://biz.moneyforward.com/support/app-portal/guide/g011.html

MF の OAuth2 は RFC6749 準拠。アプリポータルでアプリを登録すると Client ID と
Client Secret が発行される。クライアント認証方式は CLIENT_SECRET_BASIC
(Authorization ヘッダ送信) を本実装で採用 (公式推奨)。

MF の認可は **事業者単位 (tenant)** であり、個人ユーザー単位ではない。
session に保持するのは tenant_uid と事業者表示名のみ。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

# MF アプリポータル / 認可サーバー側の既定エンドポイント (env で上書き可)。
# 公式ドキュメントが path 名のみ公開しているため、host は app.biz.moneyforward.com
# を既定とし、運用中に変更があれば env で差し替える。
DEFAULT_MF_AUTHORIZE_URL: Final = "https://app.biz.moneyforward.com/oauth/authorize"
DEFAULT_MF_TOKEN_URL: Final = "https://app.biz.moneyforward.com/oauth/token"
DEFAULT_MF_REVOKE_URL: Final = "https://app.biz.moneyforward.com/oauth/revoke"

# 会計 (mfc/ac) の read のみ。MF の scope は `mfc/{product}/data.{read,write}`
# 階層に従う (請求書 = mfc/invoice, 給与 = mfc/payroll, 経費 = mfc/expense 等)。
DEFAULT_MF_SCOPE: Final = "mfc/ac/data.read"

DEFAULT_JPCITE_API_BASE: Final = "https://api.jpcite.com"

# MF が iframe で plugin を表示する際の origin 群。CSP `frame-ancestors` で許可。
MF_FRAME_ANCESTORS: Final = (
    "https://app.biz.moneyforward.com",
    "https://accounting.biz.moneyforward.com",
    "https://invoice.biz.moneyforward.com",
    "https://expense.biz.moneyforward.com",
    "https://payroll.biz.moneyforward.com",
    "https://hr.biz.moneyforward.com",
    "https://biz.moneyforward.com",
)


@dataclass(frozen=True)
class Settings:
    mf_client_id: str
    mf_client_secret: str
    mf_authorize_url: str
    mf_token_url: str
    mf_revoke_url: str
    mf_scope: str
    jpcite_api_base: str
    jpcite_api_key: str
    plugin_base_url: str
    session_secret: str
    node_env: str
    port: int

    @property
    def is_production(self) -> bool:
        return self.node_env == "production"

    @property
    def redirect_uri(self) -> str:
        # MF の redirect_uri は完全一致照合。末尾スラッシュ無し。
        return f"{self.plugin_base_url.rstrip('/')}/oauth/callback"

    @property
    def zeimu_kaikei_base_url(self) -> str:
        """Backward-compatible attribute for older plugin code/tests."""
        return self.jpcite_api_base

    @property
    def zeimu_kaikei_api_key(self) -> str:
        """Backward-compatible attribute for older plugin code/tests."""
        return self.jpcite_api_key


_REQUIRED = (
    "MF_CLIENT_ID",
    "MF_CLIENT_SECRET",
    "SESSION_SECRET",
    "PLUGIN_BASE_URL",
)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def load_settings() -> Settings:
    """env を読み出し、欠けていたら起動時に fail-fast。"""
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if not _first_env("JPCITE_API_KEY", "ZEIMU_KAIKEI_API_KEY"):
        missing.append("JPCITE_API_KEY (or legacy ZEIMU_KAIKEI_API_KEY)")
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(missing)}. " "see .env.example")
    session_secret = os.environ["SESSION_SECRET"]
    if len(session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be >= 32 chars (use openssl rand -hex 32)")

    return Settings(
        mf_client_id=os.environ["MF_CLIENT_ID"],
        mf_client_secret=os.environ["MF_CLIENT_SECRET"],
        mf_authorize_url=os.environ.get("MF_AUTHORIZE_URL", DEFAULT_MF_AUTHORIZE_URL),
        mf_token_url=os.environ.get("MF_TOKEN_URL", DEFAULT_MF_TOKEN_URL),
        mf_revoke_url=os.environ.get("MF_REVOKE_URL", DEFAULT_MF_REVOKE_URL),
        mf_scope=os.environ.get("MF_SCOPE", DEFAULT_MF_SCOPE),
        jpcite_api_base=_first_env("JPCITE_API_BASE", "ZEIMU_KAIKEI_BASE_URL")
        or DEFAULT_JPCITE_API_BASE,
        jpcite_api_key=_first_env("JPCITE_API_KEY", "ZEIMU_KAIKEI_API_KEY") or "",
        plugin_base_url=os.environ["PLUGIN_BASE_URL"],
        session_secret=session_secret,
        node_env=os.environ.get("NODE_ENV", "development"),
        port=int(os.environ.get("PORT", "8080")),
    )
