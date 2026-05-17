"""Shared cohort vocabulary + cost-saving narrative helpers for HE-5 / HE-6.

Both HE-5 (D-tier ¥30 cohort-specific deep) and HE-6 (D+-tier ¥100 cohort
ultra-deep with implementation hand-off) share the same 5-cohort vocabulary
table, persona styling, and cost-saving narrative builders. Centralising
them here keeps the 10 cohort-specific endpoints DRY and ensures the
cohort-specific terminology hydration is byte-identical across HE-5 and
HE-6 responses.

Hard constraints (CLAUDE.md / AGENTS.md):

* NO LLM inference. Pure-Python lookup + string composition.
* Reference-only — these helpers MUST be pure functions; HE-5 / HE-6
  responses are deterministic per ``(query, entity_id, context_token)``.
* No network I/O. The cohort vocabulary is static (canonical 士業 / SME
  terminology), revised on operator request only.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "COHORT_DEADLINES",
    "COHORT_ESCALATION_FLOW",
    "COHORT_FORMS",
    "COHORT_IDS",
    "COHORT_IMPLEMENTATION_WORKFLOW",
    "COHORT_LABELS_JA",
    "COHORT_PERSONA_STYLE",
    "COHORT_PITFALLS",
    "COHORT_PRACTICAL_STEPS",
    "COHORT_REGULATED_ACTS",
    "COHORT_RISK_REGISTER",
    "COHORT_VOCAB",
    "cohort_terminology_hydrate",
    "he5_cost_saving_footer",
    "he6_cost_saving_footer",
]


COHORT_IDS: tuple[str, ...] = (
    "zeirishi",
    "kaikeishi",
    "gyouseishoshi",
    "shihoshoshi",
    "chusho_keieisha",
)

COHORT_LABELS_JA: dict[str, str] = {
    "zeirishi": "税理士",
    "kaikeishi": "会計士",
    "gyouseishoshi": "行政書士",
    "shihoshoshi": "司法書士",
    "chusho_keieisha": "中小経営者",
}


COHORT_VOCAB: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "損金算入",
        "益金算入",
        "別表",
        "別表4",
        "別表5(一)",
        "繰越欠損金",
        "措置法42-4",
        "措置法42-12-5",
        "インボイス制度",
        "2割特例",
        "簡易課税",
        "原則課税",
        "仕入税額控除",
        "電子帳簿保存法",
    ),
    "kaikeishi": (
        "監査調書",
        "内部統制",
        "J-SOX",
        "監査基準",
        "ASBJ",
        "IFRS",
        "リスク評価",
        "PBC list",
        "関連当事者取引",
        "tax effect",
        "繰延税金資産",
        "回収可能性",
        "ASR",
        "監査意見",
    ),
    "gyouseishoshi": (
        "許認可",
        "建設業許可",
        "宅建業免許",
        "古物商許可",
        "風営法",
        "酒類販売業免許",
        "在留資格",
        "補助金公募要領",
        "申請書類一式",
        "添付書類",
        "受付印",
        "副本",
        "閲覧書類",
        "行政書士法 §1",
    ),
    "shihoshoshi": (
        "商業登記",
        "不動産登記",
        "設立登記",
        "役員変更登記",
        "組織再編登記",
        "抵当権設定登記",
        "根抵当権設定登記",
        "登記簿謄本",
        "印鑑証明書",
        "司法書士法 §3",
        "登記識別情報",
        "登記原因証明情報",
        "申請順序",
        "オンライン申請",
    ),
    "chusho_keieisha": (
        "資金繰り",
        "運転資金",
        "設備投資",
        "補助金併用",
        "排他ルール",
        "採択率",
        "事業再構築",
        "ものづくり補助金",
        "IT導入補助金",
        "事業承継・引継ぎ補助金",
        "措置法42-4 設備投資減税",
        "事業承継税制",
        "経営承継円滑化法",
        "M&A検討",
    ),
}


COHORT_REGULATED_ACTS: dict[str, tuple[str, ...]] = {
    "zeirishi": ("税理士法 §52", "電子帳簿保存法", "国税通則法"),
    "kaikeishi": ("公認会計士法 §47条の2", "会社法 §436以下", "監査基準"),
    "gyouseishoshi": ("行政書士法 §1", "行政書士法 §19", "申請取次規則"),
    "shihoshoshi": ("司法書士法 §3", "不動産登記法", "商業登記法"),
    "chusho_keieisha": ("中小企業基本法", "経営承継円滑化法", "中小企業等経営強化法"),
}


COHORT_PERSONA_STYLE: dict[str, str] = {
    "zeirishi": (
        "顧問先実務に直結する税務処理を、別表記載 + 損金算入判定 + 措置法適用要件で 整理しました。"
    ),
    "kaikeishi": (
        "監査調書 draft + リスク評価 + 関連当事者 mapping + 内部統制 reference を "
        "監査計画 / J-SOX 評価向けに編成しました。"
    ),
    "gyouseishoshi": (
        "許認可申請 / 補助金申請の必要書類一式 + 添付書類リスト + 副本部数 + "
        "受付印 確認手順を申請順序通りに編成しました。"
    ),
    "shihoshoshi": (
        "商業登記 / 不動産登記の申請書面 scaffold + 添付書類 + 申請順序 + "
        "登記識別情報の取扱を、登記原因毎に編成しました。"
    ),
    "chusho_keieisha": (
        "経営判断に直結する補助金 / 税制 / 融資 portfolio + 5年 roadmap + "
        "事業承継 / M&A 検討材料 をビジネス目線で編成しました。"
    ),
}


COHORT_PRACTICAL_STEPS: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "1. 関連条文 / 通達 / 裁決の verbatim を顧問先に開示し前提を共有",
        "2. 別表4 加算減算項目を確定し、損金算入 / 益金算入 を仕訳に紐付け",
        "3. 措置法適用要件 (取得価額 / 中小企業者 / 業種制限) を check-list 化",
        "4. 別表5(一) 残高 + 繰越欠損金 を 過年度 申告書と突合",
        "5. 電子帳簿保存法 / インボイス制度 対応の保存要件を 顧問先 IT 環境で検証",
    ),
    "kaikeishi": (
        "1. リスク評価 risk matrix (5x5) を 業種 / 規模 / 内部統制成熟度 で編成",
        "2. 関連当事者取引 mapping を houjin_360 + entity_id_map で確定",
        "3. PBC list を CSV coverage receipt + identity reconcile で完備",
        "4. 監査調書に 法令 / 通達 / 裁決 の verbatim citation を 出典 URL 付きで残す",
        "5. 税効果 (繰延税金資産 回収可能性) を 5年 forecast で 監査クライアントと協議",
    ),
    "gyouseishoshi": (
        "1. 業種別 fence (建設業 / 宅建 / 古物 / 風営 等) を申請先 自治体毎に確定",
        "2. 必要書類 checklist を 副本部数 + 添付書類 + 図面 まで網羅",
        "3. 公募要領 / 申請要綱 の verbatim を顧客に開示し誤解を予防",
        "4. 排他 / 併用ルール を programs/exclusions で check し申請順序を最適化",
        "5. post-award monitoring (中間報告 / 実績報告) calendar を申請完了時に登録",
    ),
    "shihoshoshi": (
        "1. 登記原因 (売買 / 相続 / 増資 / 役員変更 等) を houjin_360 + 旧商号で特定",
        "2. 申請書面の登記原因証明情報 / 印鑑証明書 / 委任状 の有効期限を check",
        "3. 申請順序 (本店所在地 → 支店 → 不動産) を 法務局 申請順で配列",
        "4. 添付書類の原本還付 / 副本提出 / オンライン申請 の振り分けを確定",
        "5. 登記識別情報の取扱 + 受領証 を顧客に説明し受領手順を fixed",
    ),
    "chusho_keieisha": (
        "1. 月次資金繰り + 運転資金 needs を 3ヶ月 forecast で見える化",
        "2. 補助金 portfolio (年次) を programs + cohort + exclusions で 3 候補に絞る",
        "3. 措置法42-4 / 措置法42-12-5 等 税制特例 適用可否を 税理士へ相談",
        "4. M&A / 事業承継 timing を 経営承継円滑化法 + 譲渡側 / 譲受側 制度で評価",
        "5. 5年 roadmap (投資 / 採択 / 申告 / 承継) を quarterly review cadence で運用",
    ),
}


COHORT_PITFALLS: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "通達のみで判断し法令本文を確認しない",
        "改正前後の effective_from を確認せず stale な解釈を流用する",
        "措置法適用要件の中小企業者判定を簡易判定で済ませる",
        "電子帳簿保存法のスキャナ保存要件を保存先 only でクリア扱いする",
    ),
    "kaikeishi": (
        "監査調書に判例 / 採決の出典 URL を残さず draft で確定する",
        "関連当事者範囲を 過去の連結範囲 のままで mapping する",
        "リスク評価を業種テンプレで済ませ 内部統制成熟度を反映しない",
        "税効果 回収可能性を tax expense の loss carryforward だけで判定する",
    ),
    "gyouseishoshi": (
        "申請書面の作成を引受け 行政書士法 §1 boundary を超える",
        "副本部数 / 添付書類 / 図面 を 自治体毎に再確認しない",
        "公募要領の更新を見逃し前回版で申請する",
        "post-award monitoring の中間報告期限を顧客に共有しない",
    ),
    "shihoshoshi": (
        "添付書類の有効期限 (印鑑証明書 3ヶ月以内 等) を確認しない",
        "申請順序を誤り後続申請の前提が崩れる",
        "登記識別情報の受領証を顧客に渡さず行方不明になる",
        "原本還付請求の手続を忘れ原本が返らない",
    ),
    "chusho_keieisha": (
        "補助金併用の排他ルールを確認せず申請する",
        "措置法適用を 税理士確認なし で agent 出力のみで判断する",
        "M&A timing を 経営承継円滑化法 認定 timing と整合させない",
        "5年 roadmap を quarterly review なしで stale 化させる",
    ),
}


COHORT_FORMS: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "別表4 (所得の金額の計算に関する明細書)",
        "別表5(一) (利益積立金額及び資本金等の額の計算に関する明細書)",
        "別表7(一) (欠損金又は災害損失金の損金算入等に関する明細書)",
        "消費税申告書 (一般用 / 簡易課税用)",
        "適格請求書発行事業者の登録申請書",
    ),
    "kaikeishi": (
        "監査計画書 (リスク評価 / 重要性 / 監査手続)",
        "監査調書 (PBC list / 試査調書 / 内部統制評価)",
        "監査意見書 / 監査報告書 draft",
        "関連当事者取引一覧表",
        "税効果 計算書 + 回収可能性 評価書",
    ),
    "gyouseishoshi": (
        "建設業許可申請書 (新規 / 更新 / 業種追加)",
        "宅建業免許申請書",
        "古物商許可申請書",
        "ものづくり補助金 / IT導入補助金 / 事業再構築補助金 申請書一式",
        "中間報告書 / 実績報告書 (post-award)",
    ),
    "shihoshoshi": (
        "商業登記 設立登記申請書",
        "商業登記 役員変更登記申請書",
        "不動産登記 売買による所有権移転登記申請書",
        "不動産登記 相続登記申請書",
        "登記原因証明情報 / 委任状",
    ),
    "chusho_keieisha": (
        "事業計画書 (補助金申請用 + 銀行融資用)",
        "資金繰り表 (3ヶ月 / 12ヶ月)",
        "事業承継計画書 (経営承継円滑化法 認定申請用)",
        "M&A intent letter / 基本合意書 draft",
        "5年中期経営計画書",
    ),
}


COHORT_DEADLINES: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "法人税申告: 事業年度終了の日の翌日から2ヶ月以内 (延長申請で1ヶ月延長可)",
        "消費税申告: 課税期間終了の日の翌日から2ヶ月以内",
        "源泉徴収 納付: 翌月10日 (納期特例で年2回 = 7月10日 / 1月20日)",
        "年末調整: 翌年1月31日 (給与所得者の扶養控除等申告書)",
        "償却資産申告: 毎年1月31日",
    ),
    "kaikeishi": (
        "監査報告書: 株主総会の1週間前まで (会社法 §437)",
        "計算書類 株主総会承認: 事業年度終了から3ヶ月以内 (定款で変更可)",
        "有価証券報告書: 事業年度終了後3ヶ月以内 (金商法 §24)",
        "内部統制報告書: 有報と同時 (J-SOX)",
        "四半期報告書: 各四半期終了後45日以内 (継続開示)",
    ),
    "gyouseishoshi": (
        "建設業許可 更新申請: 有効期限の30日前まで (5年毎)",
        "ものづくり補助金 公募: 各回 約2ヶ月の応募期間",
        "IT導入補助金 公募: 各回 約1〜2ヶ月の応募期間",
        "中間報告書: 補助事業期間の中間時点",
        "実績報告書: 補助事業完了後30日以内",
    ),
    "shihoshoshi": (
        "設立登記: 発起人による定款認証後、設立予定日から2週間以内",
        "役員変更登記: 役員変更日から2週間以内 (会社法 §915)",
        "本店移転登記: 移転日から2週間以内",
        "相続登記: 2024年4月1日以降 義務化 (相続を知ってから3年以内)",
        "印鑑証明書: 発行から3ヶ月以内 (登記申請の添付書類)",
    ),
    "chusho_keieisha": (
        "補助金 採択 → 交付申請: 採択通知から30日以内 (制度により異なる)",
        "事業承継税制 認定申請: 後継者代表者就任前後の所定期間内",
        "M&A検討: 6ヶ月〜2年 (DD + 基本合意 + 最終契約)",
        "経営計画 quarterly review: 各四半期末から30日以内",
        "決算 確定 → 株主総会: 事業年度終了から3ヶ月以内",
    ),
}


COHORT_IMPLEMENTATION_WORKFLOW: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "月次: 仕訳 + 試算表 + 月次監査証跡 (audit_seal pack)",
        "四半期: 中間決算 + 法人税 中間申告 + 消費税 中間申告",
        "年次: 決算 + 法人税申告 (別表4 / 5 / 7) + 消費税申告",
        "年次: 法定調書 + 給与支払報告書 + 償却資産申告 + 年末調整",
        "随時: 顧問先制度提案 + 税制特例検討 + インボイス取引先確認",
    ),
    "kaikeishi": (
        "監査計画フェーズ: リスク評価 + 重要性決定 + 監査手続設計",
        "中間監査フェーズ: 試査 + 実証手続 + 関連当事者確認",
        "期末監査フェーズ: 棚卸立会 + 残高確認状 + 後発事象確認",
        "監査意見形成フェーズ: 監査調書 review + 監査意見 + 監査報告書",
        "事後フェーズ: 翌期 PBC + 内部統制 改善提案 + 監査品質 review",
    ),
    "gyouseishoshi": (
        "受任フェーズ: 業種 / 申請先 / 必要書類 を確認",
        "書類準備フェーズ: 添付書類 + 副本 + 図面 + 委任状",
        "申請フェーズ: 申請先 自治体 / 警察署 / 公的機関 へ提出",
        "審査対応フェーズ: 補正指示対応 + 追加書類提出",
        "post-award フェーズ: 許可証受領 + 中間 / 実績報告 + 更新監視",
    ),
    "shihoshoshi": (
        "受任フェーズ: 登記原因 + 関係者 + 添付書類有効期限 を確認",
        "書類準備フェーズ: 登記原因証明情報 + 印鑑証明書 + 委任状 + 議事録",
        "申請フェーズ: 法務局 (本店 → 支店 → 不動産 の順) へ提出",
        "補正対応フェーズ: 法務局からの補正指示 へ24時間以内対応",
        "完了フェーズ: 登記識別情報 / 登記事項証明書 を顧客へ交付",
    ),
    "chusho_keieisha": (
        "年初: 経営計画 review + 5年 roadmap update",
        "四半期: 採択補助金 進捗 + 資金繰り review + 取引先与信 update",
        "決算前: 税理士へ申告書 確認依頼 + 措置法適用可否 review",
        "決算後: 株主総会 + 計算書類確定 + 翌期予算 確定",
        "随時: M&A検討 + 事業承継検討 + 政策融資検討",
    ),
}


COHORT_RISK_REGISTER: dict[str, tuple[dict[str, str], ...]] = {
    "zeirishi": (
        {
            "id": "RZ1",
            "risk": "措置法適用要件の誤判定",
            "mitigation": "措置法本文 + 通達を verbatim で確認",
        },
        {
            "id": "RZ2",
            "risk": "改正前後の effective_from 混在",
            "mitigation": "as_of snapshot で過去日比較",
        },
        {
            "id": "RZ3",
            "risk": "インボイス 2割特例 sunset 認識不足",
            "mitigation": "2026年9月30日 終了を顧問先 calendar に登録",
        },
        {
            "id": "RZ4",
            "risk": "電子帳簿保存法 スキャナ保存要件未対応",
            "mitigation": "保存要件 check-list を IT 環境で検証",
        },
    ),
    "kaikeishi": (
        {
            "id": "RK1",
            "risk": "関連当事者範囲漏れ",
            "mitigation": "houjin_360 + entity_id_map で再 mapping",
        },
        {
            "id": "RK2",
            "risk": "リスク評価 業種テンプレ化",
            "mitigation": "5x5 matrix を 業種 / 規模 / 内部統制 で個別化",
        },
        {
            "id": "RK3",
            "risk": "税効果 回収可能性 過大評価",
            "mitigation": "5年 forecast を 監査クライアントと協議",
        },
        {
            "id": "RK4",
            "risk": "監査調書 出典 URL 欠落",
            "mitigation": "verbatim citation + URL を必須 review 項目化",
        },
    ),
    "gyouseishoshi": (
        {
            "id": "RG1",
            "risk": "行政書士法 §1 boundary 超過",
            "mitigation": "scaffold + 一次 URL のみ、申請書面 creation 禁止",
        },
        {
            "id": "RG2",
            "risk": "公募要領 更新見逃し",
            "mitigation": "programs/{id}/round で最新 round を確認",
        },
        {
            "id": "RG3",
            "risk": "排他ルール 確認漏れ",
            "mitigation": "exclusions/check を必須 pre-flight 化",
        },
        {
            "id": "RG4",
            "risk": "post-award monitoring 失念",
            "mitigation": "program_post_award_calendar 自動登録",
        },
    ),
    "shihoshoshi": (
        {
            "id": "RS1",
            "risk": "添付書類有効期限切れ",
            "mitigation": "印鑑証明書 3ヶ月以内 etc を予約時 check",
        },
        {
            "id": "RS2",
            "risk": "申請順序誤り",
            "mitigation": "本店 → 支店 → 不動産 の順を template 化",
        },
        {"id": "RS3", "risk": "登記識別情報紛失", "mitigation": "受領証 双方署名 + 保管場所明示"},
        {
            "id": "RS4",
            "risk": "司法書士法 §3 boundary 超過",
            "mitigation": "登記簿事項 retrieval のみ、登記事項判断 禁止",
        },
    ),
    "chusho_keieisha": (
        {
            "id": "RC1",
            "risk": "補助金併用 排他違反",
            "mitigation": "exclusions/rules で 181 rule を pre-check",
        },
        {
            "id": "RC2",
            "risk": "措置法 自己判断",
            "mitigation": "税理士確認 必須 (CONSTITUTION 13.2)",
        },
        {
            "id": "RC3",
            "risk": "M&A timing ずれ",
            "mitigation": "経営承継円滑化法 認定 + 譲渡側 / 譲受側制度 を同期",
        },
        {
            "id": "RC4",
            "risk": "5年 roadmap stale 化",
            "mitigation": "quarterly review cadence + jpcite watch hook",
        },
    ),
}


COHORT_ESCALATION_FLOW: dict[str, tuple[str, ...]] = {
    "zeirishi": (
        "Level 1: 顧問先 担当 → 税理士",
        "Level 2: 税理士 → 国税局 / 税務署 ヒアリング",
        "Level 3: 税理士 → 国税不服審判所 (異議申立)",
        "Level 4: 税理士 + 弁護士 → 税務訴訟",
    ),
    "kaikeishi": (
        "Level 1: 監査チーム内 / マネージャー review",
        "Level 2: 主査 → 監査責任者 (パートナー)",
        "Level 3: 監査責任者 → 監査法人 品質管理本部",
        "Level 4: 監査法人 → 金融庁 / 公認会計士・監査審査会",
    ),
    "gyouseishoshi": (
        "Level 1: 申請担当 行政書士 内部 review",
        "Level 2: 行政書士 → 自治体担当課 ヒアリング",
        "Level 3: 行政書士 → 上位行政庁 ヒアリング",
        "Level 4: 行政書士 + 弁護士 → 行政不服審査 / 行政訴訟",
    ),
    "shihoshoshi": (
        "Level 1: 担当 司法書士 内部 review",
        "Level 2: 司法書士 → 法務局 ヒアリング",
        "Level 3: 司法書士 → 法務局 補正対応 / 取下げ",
        "Level 4: 司法書士 + 弁護士 → 異議申立 / 行政訴訟",
    ),
    "chusho_keieisha": (
        "Level 1: 経営者 → 顧問税理士 / 顧問社労士",
        "Level 2: 経営者 + 顧問 → 業務委託先専門家 (会計士 / 弁護士)",
        "Level 3: 経営者 + 顧問 → 金融機関 / 認定支援機関",
        "Level 4: 経営者 + 顧問 + 公的機関 (中小機構 / よろず支援拠点)",
    ),
}


def he5_cost_saving_footer(cohort: str) -> str:
    """Return the HE-5 cost-saving narrative footer for ``cohort``."""
    label = COHORT_LABELS_JA.get(cohort, cohort)
    return (
        "Cost-saving claim: equivalent to ~7-turn Opus 4.7 reasoning with "
        f"cohort-specific persona (¥500-700). This endpoint: ¥30 = 1/17-1/24. "
        f"Cohort: {label} ({cohort})."
    )


def he6_cost_saving_footer(cohort: str) -> str:
    """Return the HE-6 cost-saving narrative footer for ``cohort``."""
    label = COHORT_LABELS_JA.get(cohort, cohort)
    return (
        "Cost-saving claim: equivalent to ~21-turn Opus 4.7 multi-round "
        f"reasoning (¥1,500). This endpoint: ¥100 = 1/15. "
        f"Cohort: {label} ({cohort})."
    )


def cohort_terminology_hydrate(cohort: str, body: str) -> dict[str, Any]:
    """Return a {body, terms_found, missing_terms, total} payload."""
    lexicon = COHORT_VOCAB.get(cohort, ())
    body_text = body or ""
    found: list[str] = [t for t in lexicon if t in body_text]
    missing: list[str] = [t for t in lexicon if t not in body_text]
    return {
        "body": body_text,
        "terms_found": found,
        "missing_terms": missing,
        "total_lexicon": len(lexicon),
        "coverage_ratio": (len(found) / max(len(lexicon), 1)),
    }
