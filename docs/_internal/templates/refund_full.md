TO: {{customer_email}}
FROM: support@zeimu-kaikei.ai
SUBJECT: 【jpintel-mcp】返金処理のご連絡 (ticket {{ticket_id}})

{{customer_name}} 様

お世話になっております。jpintel-mcp サポート担当の {{operator_name}} でございます。
{{ticket_id}} にてご連絡いただきました {{plan_tier}} プランの返金申請につきまして、
内容を確認のうえ全額返金の手続きを完了いたしましたのでご連絡申し上げます。

■ 返金内容
 - 対象決済日: {{payment_date}}
 - 返金金額: {{refund_amount_jpy}} 円 (全額)
 - Stripe 決済 ID: {{stripe_payment_intent_id}}
 - 返金処理実施日時: {{refund_executed_at}}

Stripe の仕様上、カード会社への反映には通常 5〜10 営業日を要します。
明細への表示タイミングはカード会社により異なりますので、ご不明な場合は
発行カード会社へ直接お問い合わせください。

あわせて、お客様の API キーにつきましては本日付で失効 (revoke) し、
以降のリクエストは受け付けない状態といたしました。

この度はご期待に沿えず誠に申し訳ございません。
今後サービスの改善点としてご意見を頂戴できれば幸いです。
追加のご質問がございましたら、本メールへそのまま返信ください。

引き続きどうぞよろしくお願い申し上げます。

---
jpintel-mcp サポート
{{operator_name}}
support@zeimu-kaikei.ai
https://zeimu-kaikei.ai/
