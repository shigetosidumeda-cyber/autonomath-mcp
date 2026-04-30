TO: {{customer_email}}
FROM: support@jpcite.com
SUBJECT: 【jpintel-mcp】API キー失効のご連絡 (ticket {{ticket_id}})

{{customer_name}} 様

お世話になっております。jpintel-mcp サポート担当の {{operator_name}} でございます。
本メールは、お客様アカウントに発行済みの API キーを失効 (revoke) した件に関する
正式なご連絡でございます。

■ 失効対象
 - プラン: {{plan_tier}}
 - キー末尾 4 桁: {{key_last4}}
 - 失効日時 (JST): {{revoked_at}}

■ 失効理由
下記利用状況が利用規約第 {{tos_section}} 条 ({{tos_section_title}}) に
抵触すると判断いたしました。

 - 検出した事象: {{abuse_signal}}
   (例: 同一キーの IP 分散利用、契約プラン上限を大幅に超過するリクエスト、
    自動スクレイピングと推定される挙動 等)
 - 観測期間: {{observation_window}}
 - 直近の送信元 IP 多様性: {{ip_range_count}} 個の /24 レンジ
 - 直近のリクエスト回数: {{call_count}} 回 ({{plan_tier}} プラン上限比 {{usage_ratio}})

■ 今後のお取扱い
1. 本キーは即時失効しており、以降のリクエストは 401 / 403 を返します。
2. Stripe サブスクリプション ({{stripe_subscription_id}}) につきましては
   {{subscription_action}} いたしました。
3. 事実関係に誤認がある場合は、{{reply_deadline}} までに利用状況・設定詳細を添えて
   本メールへご返信ください。内容を精査のうえ、再発行の可否を判断いたします。
4. 再発行をご希望される場合は、再発防止策 (キーの保管・共有範囲・リクエスト設計等)
   をご記載ください。

本ご連絡は当社の利用規約および個人情報保護の方針に基づくものでございます。
ご不便をおかけして誠に申し訳ございません。

---
jpintel-mcp サポート
{{operator_name}}
support@jpcite.com
https://jpcite.com/
