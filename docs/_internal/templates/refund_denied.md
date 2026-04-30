TO: {{customer_email}}
FROM: support@jpcite.com
SUBJECT: 【jpintel-mcp】返金申請に関するご回答 (ticket {{ticket_id}})

{{customer_name}} 様

お世話になっております。jpintel-mcp サポート担当の {{operator_name}} でございます。
{{ticket_id}} にてご連絡いただきました {{plan_tier}} プランの返金申請につきまして、
内部調査の結果をご報告いたします。

誠に恐縮ではございますが、本件は返金の対象外と判断いたしましたこと、
下記のとおりご回答申し上げます。

■ 判断理由
 - 対象決済日: {{payment_date}}
 - 決済以降の API 呼び出し回数: {{call_count}} 回
 - 当該プラン上限に対する比率: {{usage_ratio}}
 - 該当する利用規約: 利用規約第 {{tos_section}} 条 ({{tos_section_title}})

ご契約プランに対し、著しく高い利用量または契約趣旨に反する利用形態が
確認されたため、返金を見送らせていただく方針でございます。
詳細につきましては利用規約 (https://jpcite.com/tos.html) をあわせてご確認ください。

なお、事実関係に相違がございましたら、具体的な利用状況や背景を添えて
本メールにご返信ください。改めて精査のうえ再回答申し上げます。
また、ご契約内容 (プラン変更 / 解約) につきましては Stripe カスタマーポータル
(https://jpcite.com/billing/portal) よりいつでもご自身で変更いただけます。

ご期待に沿えない回答となり大変申し訳ございません。
引き続きどうぞよろしくお願い申し上げます。

---
jpintel-mcp サポート
{{operator_name}}
support@jpcite.com
https://jpcite.com/
