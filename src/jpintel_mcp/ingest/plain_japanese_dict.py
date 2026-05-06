"""plain_japanese_dict — rule-based dictionary for 平易日本語 mode.

Used by `get_program_narrative(reading_level="plain")` (W3-12 UC7 LINE
中小企業向け blocker) to substitute jargon-heavy 補助金 / 税制 / 行政
terminology with plain-Japanese paraphrases.

Hard rule (memory `feedback_no_operator_llm_api` + repo CLAUDE.md
"Non-negotiable constraints"):
  * NO LLM call inside the jpcite service.
  * Substitution is rule-based dict lookup only.
  * Replacements are intentionally lossy — they trade legal precision
    for readability, so the response always flags `_reading_level: "plain"`
    and the auto-injected `_disclaimer` envelope (sensitive tool) tells the
    customer this is NOT 申請代理 / 税務助言.

Coverage:
  ~50 entries across 補助金 / 融資 / 税制 / 行政手続き jargon. Ordered
  longest-first when applied so 'IT導入補助金' wins over '補助金' on the
  same input span.
"""

from __future__ import annotations

# (jargon, plain) pairs. Keep longest entries first — `replace_plain_japanese`
# applies them in declared order so multi-character compounds win over their
# substrings (e.g. '事業再構築補助金' before '補助金', '小規模事業者' before
# '事業者').
_PLAIN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # ---- 補助金プログラム名 (longest first) -----------------------------
    ("事業再構築補助金", "事業のやり直しを助けるお金"),
    ("ものづくり補助金", "新しい機械や設備を買うお金を助ける制度"),
    ("小規模事業者持続化補助金", "小さな会社が続けていくのを助けるお金"),
    ("IT導入補助金", "パソコンや業務ソフトを買うお金を助ける制度"),
    ("経営強化税制", "会社を強くするための税金まけ制度"),
    # ---- 補助金 / 融資 一般語 ------------------------------------------
    ("補助率", "お金の半分くれます"),
    ("公募要領", "申込みの説明書"),
    ("交付決定", "お金をあげると決まったお知らせ"),
    ("採択", "申込みが選ばれること"),
    ("不採択", "申込みが選ばれなかったこと"),
    ("申請書", "申込み用紙"),
    ("申請期間", "申込みできる期間"),
    ("公募期間", "申込みを受け付けている期間"),
    ("補助上限額", "もらえるお金の最大の金額"),
    ("補助対象経費", "お金を出してもらえる費用"),
    ("補助金交付申請", "お金をもらうための申込み"),
    ("実績報告", "やったことの報告書"),
    ("精算払", "あとからまとめて払う方式"),
    ("概算払", "前払いのお金"),
    ("自己負担", "自分で出すお金"),
    # ---- 融資 -----------------------------------------------------------
    ("融資", "銀行などからお金を借りること"),
    ("担保", "返せないときに代わりに渡す財産"),
    ("保証人", "お金を返せなかったとき代わりに払ってくれる人"),
    ("無担保無保証", "財産も保証人もいらない"),
    ("据置期間", "しばらく返さなくていい期間"),
    ("利率", "借りたお金につく利息の割合"),
    ("償還期間", "お金を返す期間"),
    # ---- 税制 -----------------------------------------------------------
    ("税額控除", "払う税金を少なくしてくれる制度"),
    ("所得控除", "もうけから差し引ける金額"),
    ("租税特別措置法", "特別に税金をまけてくれる法律"),
    ("法人税", "会社がもうけにかかる税金"),
    ("所得税", "個人がもうけにかかる税金"),
    ("消費税", "買い物のときにかかる税金"),
    ("青色申告", "きちんと記録して出す確定申告"),
    ("確定申告", "1年分のもうけを国に報告する手続き"),
    ("繰越欠損金", "前の年の赤字を次の年にまわせる仕組み"),
    # ---- 行政手続き ------------------------------------------------------
    ("認定", "お墨付きをもらうこと"),
    ("認可", "国や役所のOKをもらうこと"),
    ("届出", "役所に知らせる手続き"),
    ("登記", "会社や財産を国の帳簿にのせる手続き"),
    ("定款", "会社のルールを書いた書類"),
    ("登記簿謄本", "会社の登録内容のコピー"),
    ("住民票", "住んでいる場所を証明する書類"),
    # ---- 事業者属性 ------------------------------------------------------
    ("中小企業者", "中くらいの会社や小さな会社"),
    ("小規模事業者", "とくに小さな会社や個人事業主"),
    ("みなし大企業", "大企業とみなされる会社"),
    ("個人事業主", "会社にしないで一人でやっている人"),
    # ---- 期間 / 締切 ----------------------------------------------------
    ("締切日", "申込みの期限の日"),
    ("公募開始", "申込みの受付が始まること"),
    ("公募終了", "申込みの受付が終わること"),
)


def replace_plain_japanese(text: str | None) -> str:
    """Apply rule-based 平易日本語 substitutions in declared order.

    None / empty input is returned unchanged (typed back to '' for None
    so callers don't have to guard).
    """
    if not text:
        return text or ""
    out = text
    for jargon, plain in _PLAIN_REPLACEMENTS:
        if jargon in out:
            out = out.replace(jargon, plain)
    return out


__all__ = ["replace_plain_japanese", "_PLAIN_REPLACEMENTS"]
