TO: {{customer_email}}
FROM: support@zeimu-kaikei.ai
SUBJECT: 【jpintel-mcp】サービス障害に関するご連絡 ({{incident_id}})

{{customer_name}} 様

お世話になっております。jpintel-mcp サポート担当の {{operator_name}} でございます。
現在発生しておりますサービス障害につきまして、下記のとおりご報告申し上げます。

■ 障害概要
 - インシデント ID: {{incident_id}}
 - 発生検知時刻 (JST): {{incident_detected_at}}
 - 影響範囲: {{affected_scope}}
   (例: /v1/programs/search を含む API 全体 / 一部 endpoint / 管理画面のみ 等)
 - 現在のステータス: {{current_status}}
   (例: 調査中 / 緩和中 / 復旧確認中 / 復旧済み)
 - ステータスページ: https://zeimu-kaikei.ai/status

■ これまでの経緯
{{timeline_summary}}

■ 現在の対応状況
{{current_action}}

■ 復旧見込み
{{eta_statement}}
(現時点で確定見込みが提示できない場合は「現在調査中のため、{{next_update_at}} を
 目処に続報をお送りいたします」と記載)

■ お客様にお願いしたい事項
 - リクエストは自動リトライをお控えください (障害の長期化につながる恐れがあります)
 - ステータスページにて最新状況をご確認ください
 - データ損失等が疑われる事象を観測された場合は本メールへご返信ください

復旧までご不便をおかけし誠に申し訳ございません。
続報は {{next_update_at}} までにお送りいたします。
復旧後には事後報告 (postmortem) を 72 時間以内に公開いたします。

---
jpintel-mcp サポート
{{operator_name}}
support@zeimu-kaikei.ai
https://zeimu-kaikei.ai/
