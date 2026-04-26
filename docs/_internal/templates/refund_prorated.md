TO: {{customer_email}}
FROM: support@autonomath.ai
SUBJECT: 【jpintel-mcp】日割り返金のご案内 (ticket {{ticket_id}})

{{customer_name}} 様

お世話になっております。jpintel-mcp サポート担当の {{operator_name}} でございます。
{{ticket_id}} にてご連絡いただきました {{plan_tier}} プランの解約・返金につきまして、
下記のとおり日割りでの返金処理を実施いたしました。

■ 返金内容
 - 対象決済日: {{payment_date}}
 - 月額料金: {{monthly_amount_jpy}} 円
 - ご利用日数: {{days_used}} 日 / {{days_in_cycle}} 日
 - 返金金額 (日割り): {{refund_amount_jpy}} 円
 - Stripe 決済 ID: {{stripe_payment_intent_id}}
 - 返金処理実施日時: {{refund_executed_at}}

計算式: 月額 {{monthly_amount_jpy}} 円 × (残り {{days_remaining}} 日 / {{days_in_cycle}} 日) = {{refund_amount_jpy}} 円

Stripe の仕様上、カード会社への反映には通常 5〜10 営業日を要します。

■ API キーの取扱い
現在発行中の API キーは、本サイクル終了日 ({{cycle_end_date}}) をもって失効 (revoke)
いたします。それまでは引き続きご利用いただけます。サブスクリプション自体は
Stripe 側で自動更新されない設定に変更済みです。

ご不明な点がございましたら本メールへそのままご返信ください。
引き続きどうぞよろしくお願い申し上げます。

---
jpintel-mcp サポート
{{operator_name}}
support@autonomath.ai
https://autonomath.ai/
