"""Generate placeholder PNGs for the freee marketplace submission.

These are intentionally simple, branded mock-ups. **Real screenshots must
replace these once a freee app account is registered and the plugin is
installed in a test office** (see ../../SUBMISSION_CHECKLIST.md).

Run:
    cd sdk/freee-plugin/marketplace/submission/screenshots
    python3 _stub_generator.py

Outputs:
    icon-640x640.png
    01-subsidy-search.png
    02-tax-incentive.png
    03-invoice-check.png
    04-evidence-prefetch.png
    05-disclaimer-footer.png
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

ACCENT = (15, 111, 255)
BG = (255, 255, 255)
BG_SOFT = (246, 248, 250)
LINE = (226, 232, 236)
FG = (29, 29, 31)
FG_MUTE = (95, 108, 123)
WARN_BG = (255, 247, 230)
WARN_FG = (138, 83, 0)
TIER_S_BG = (255, 247, 230)
TIER_S_FG = (138, 83, 0)
TIER_A_BG = (230, 255, 251)
TIER_A_FG = (0, 118, 108)


def find_jp_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/HiraginoSans-W6.ttc",
        "/System/Library/Fonts/HiraginoSans-W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_icon() -> None:
    size = 640
    img = Image.new("RGB", (size, size), ACCENT)
    draw = ImageDraw.Draw(img)
    # Subtle gradient feel via a darker circle bottom-right.
    draw.ellipse((size * 0.55, size * 0.55, size * 1.4, size * 1.4), fill=(10, 90, 214))
    # Foreground: jpcite wordmark.
    f_big = find_jp_font(150)
    f_med = find_jp_font(70)
    draw.text((size / 2, size / 2 - 30), "jpcite", font=f_big, fill="white", anchor="mm")
    draw.text((size / 2, size - 60), "for freee", font=f_med, fill=(220, 234, 255), anchor="mm")
    img.save(HERE / "icon-640x640.png", "PNG", optimize=True)


def _frame(draw: ImageDraw.ImageDraw, w: int, h: int, title: str, subtitle: str) -> None:
    """Render the common header + footer chrome."""
    # Header
    draw.rectangle((0, 0, w, 80), fill=BG_SOFT)
    draw.line((0, 80, w, 80), fill=LINE, width=2)
    f_title = find_jp_font(32)
    f_sub = find_jp_font(20)
    draw.text((40, 40), "jpcite", font=f_title, fill=FG, anchor="lm")
    draw.text((180, 44), "freee 会計 連携", font=f_sub, fill=FG_MUTE, anchor="lm")
    # Company pill (right side)
    draw.rounded_rectangle((w - 280, 30, w - 130, 60), radius=15, fill=(238, 244, 255))
    draw.text((w - 205, 45), "Bookyou株式会社", font=find_jp_font(18), fill=ACCENT, anchor="mm")
    draw.text((w - 80, 45), "ログアウト", font=find_jp_font(18), fill=FG_MUTE, anchor="mm")
    # Footer (税理士法 §52 disclaimer)
    foot_h = 90
    draw.rectangle((0, h - foot_h, w, h), fill=WARN_BG)
    draw.line((0, h - foot_h, w, h - foot_h), fill=LINE, width=2)
    f_disc = find_jp_font(16)
    f_disc_bold = find_jp_font(17)
    draw.text(
        (40, h - foot_h + 22),
        "税理士法 第52条 ご注意:",
        font=f_disc_bold,
        fill=WARN_FG,
        anchor="lm",
    )
    draw.text(
        (40, h - foot_h + 50),
        "本サービスは情報提供のみを目的とし、税理士業務に該当する個別アドバイスを行いません。",
        font=f_disc,
        fill=WARN_FG,
        anchor="lm",
    )
    draw.text(
        (40, h - foot_h + 72),
        "提供: jpcite / 運営: Bookyou株式会社 (T8010001213708)",
        font=find_jp_font(14),
        fill=FG_MUTE,
        anchor="lm",
    )


def _tab_strip(draw: ImageDraw.ImageDraw, w: int, active: int, labels: list[str]) -> None:
    y = 110
    f = find_jp_font(20)
    x = 40
    for i, label in enumerate(labels):
        is_active = i == active
        text_color = ACCENT if is_active else FG_MUTE
        draw.text((x, y), label, font=f, fill=text_color, anchor="lm")
        if is_active:
            tw = draw.textlength(label, font=f)
            draw.line((x, y + 18, x + tw, y + 18), fill=ACCENT, width=3)
        x += int(draw.textlength(label, font=f)) + 60
    draw.line((40, y + 26, w - 40, y + 26), fill=LINE, width=1)


def _result_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    title: str,
    meta: list[tuple[str, str]],
    deep: str,
    tier: str | None = None,
) -> int:
    """Render a single search-result card; return the y-coordinate of next row."""
    h = 90
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, outline=LINE, fill="white")
    draw.text((x + 16, y + 18), title, font=find_jp_font(20), fill=FG, anchor="lm")
    mx = x + 16
    for kind, text in meta:
        if kind == "tier":
            color_bg = TIER_S_BG if text == "S" else TIER_A_BG
            color_fg = TIER_S_FG if text == "S" else TIER_A_FG
            tw = 70
            draw.rounded_rectangle(
                (mx, y + 40, mx + tw, y + 60), radius=4, fill=color_bg, outline=LINE
            )
            draw.text(
                (mx + tw / 2, y + 50),
                f"Tier {text}",
                font=find_jp_font(14),
                fill=color_fg,
                anchor="mm",
            )
            mx += tw + 10
        else:
            tw = int(draw.textlength(text, font=find_jp_font(14)))
            draw.text((mx, y + 50), text, font=find_jp_font(14), fill=FG_MUTE, anchor="lm")
            mx += tw + 16
    draw.text((x + 16, y + 75), deep, font=find_jp_font(14), fill=ACCENT, anchor="lm")
    return y + h + 10


def screenshot_subsidy() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    _frame(draw, w, h, "補助金検索", "")
    _tab_strip(draw, w, 0, ["補助金", "税制優遇", "インボイス番号確認"])

    # Search form
    fy = 160
    draw.rounded_rectangle((40, fy, 580, fy + 40), radius=6, outline=LINE, fill="white")
    draw.text((52, fy + 20), "省エネ", font=find_jp_font(18), fill=FG, anchor="lm")
    draw.rounded_rectangle((600, fy, 820, fy + 40), radius=6, outline=LINE, fill="white")
    draw.text((612, fy + 20), "東京都", font=find_jp_font(18), fill=FG, anchor="lm")
    draw.rounded_rectangle((840, fy, 940, fy + 40), radius=6, fill=ACCENT)
    draw.text((890, fy + 20), "検索", font=find_jp_font(18), fill="white", anchor="mm")

    # Result cards
    cy = 220
    cy = _result_card(
        draw,
        40,
        cy,
        w - 80,
        "省エネルギー投資促進支援事業費補助金",
        [("tier", "S"), ("text", "経産省"), ("text", "全国")],
        "出典を確認 (https://sii.or.jp/) · jpciteで詳細",
    )
    cy = _result_card(
        draw,
        40,
        cy,
        w - 80,
        "東京都中小企業 設備投資緊急支援事業",
        [("tier", "A"), ("text", "東京都産業労働局"), ("text", "東京都")],
        "出典を確認 · jpciteで詳細",
    )
    cy = _result_card(
        draw,
        40,
        cy,
        w - 80,
        "ものづくり補助金 (一般型 / 省エネ枠)",
        [("tier", "S"), ("text", "中小企業庁"), ("text", "全国")],
        "出典を確認 · jpciteで詳細",
    )
    img.save(HERE / "01-subsidy-search.png", "PNG", optimize=True)


def screenshot_tax() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    _frame(draw, w, h, "税制優遇", "")
    _tab_strip(draw, w, 1, ["補助金", "税制優遇", "インボイス番号確認"])

    fy = 160
    draw.rounded_rectangle((40, fy, 1040, fy + 40), radius=6, outline=LINE, fill="white")
    draw.text((52, fy + 20), "賃上げ", font=find_jp_font(18), fill=FG, anchor="lm")
    draw.rounded_rectangle((1060, fy, 1160, fy + 40), radius=6, fill=ACCENT)
    draw.text((1110, fy + 20), "検索", font=find_jp_font(18), fill="white", anchor="mm")

    cy = 220
    cy = _result_card(
        draw,
        40,
        cy,
        w - 80,
        "中小企業向け 賃上げ促進税制",
        [("text", "租税特別措置法 第42条の12の5"), ("text", "適用期間: 令和 6.4.1 〜 令和 9.3.31")],
        "条文・告示を確認 (https://elaws.e-gov.go.jp/)",
    )
    cy = _result_card(
        draw,
        40,
        cy,
        w - 80,
        "中小企業 経営強化税制",
        [("text", "租税特別措置法 第42条の12の4"), ("text", "適用期間: 令和 7.4.1 〜 令和 9.3.31")],
        "条文・告示を確認",
    )
    cy = _result_card(
        draw,
        40,
        cy,
        w - 80,
        "DX 投資促進税制",
        [("text", "租税特別措置法 第42条の12の7"), ("text", "適用期間: 令和 3.8.2 〜 令和 7.3.31")],
        "条文・告示を確認",
    )
    img.save(HERE / "02-tax-incentive.png", "PNG", optimize=True)


def screenshot_invoice() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    _frame(draw, w, h, "インボイス登録番号確認", "")
    _tab_strip(draw, w, 2, ["補助金", "税制優遇", "インボイス番号確認"])

    fy = 160
    draw.rounded_rectangle((40, fy, 1040, fy + 40), radius=6, outline=LINE, fill="white")
    draw.text((52, fy + 20), "T8010001213708", font=find_jp_font(18), fill=FG, anchor="lm")
    draw.rounded_rectangle((1060, fy, 1160, fy + 40), radius=6, fill=ACCENT)
    draw.text((1110, fy + 20), "確認", font=find_jp_font(18), fill="white", anchor="mm")

    # Single result card with details
    cy = 220
    card_h = 130
    draw.rounded_rectangle((40, cy, w - 40, cy + card_h), radius=10, outline=LINE, fill="white")
    draw.text((56, cy + 24), "Bookyou株式会社", font=find_jp_font(22), fill=FG, anchor="lm")

    # Status pill
    pill_x = w - 200
    draw.rounded_rectangle(
        (pill_x, cy + 18, pill_x + 100, cy + 44),
        radius=4,
        fill=(230, 255, 240),
        outline=(135, 232, 174),
    )
    draw.text((pill_x + 50, cy + 31), "有効", font=find_jp_font(16), fill=(0, 128, 60), anchor="mm")

    draw.text(
        (56, cy + 60),
        "登録番号: T8010001213708 · 登録日: 令和7年5月12日",
        font=find_jp_font(15),
        fill=FG_MUTE,
        anchor="lm",
    )
    draw.text(
        (56, cy + 85),
        "所在地: 東京都文京区小日向2-22-1",
        font=find_jp_font(15),
        fill=FG_MUTE,
        anchor="lm",
    )
    draw.text(
        (56, cy + 110),
        "国税庁公表サイトで確認 →",
        font=find_jp_font(14),
        fill=ACCENT,
        anchor="lm",
    )
    img.save(HERE / "03-invoice-check.png", "PNG", optimize=True)


def screenshot_evidence_prefetch() -> None:
    """Optional 4th screenshot: official-source evidence packet prefetch."""
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    _frame(draw, w, h, "証跡パケット", "")

    draw.text(
        (60, 120),
        "freee 事業所情報から、確認用の一次資料セットを事前取得",
        font=find_jp_font(26),
        fill=FG,
        anchor="la",
    )
    draw.rounded_rectangle((60, 170, 1140, 510), radius=12, fill="white", outline=LINE)
    draw.text(
        (90, 205),
        "証跡パケット: 東京都 / IT / 法人番号あり",
        font=find_jp_font(20),
        fill=FG,
        anchor="la",
    )
    draw.text(
        (90, 250),
        "1. 中小企業経営強化税制",
        font=find_jp_font(18),
        fill=FG,
        anchor="la",
    )
    draw.text(
        (90, 280),
        "   一次資料: e-Gov 租税特別措置法 第42条の12の4",
        font=find_jp_font(15),
        fill=FG_MUTE,
        anchor="la",
    )
    draw.text(
        (90, 325),
        "2. DX 投資促進税制",
        font=find_jp_font(18),
        fill=FG,
        anchor="la",
    )
    draw.text(
        (90, 355),
        "   一次資料: 経産省 / 租税特別措置法 第42条の12の7",
        font=find_jp_font(15),
        fill=FG_MUTE,
        anchor="la",
    )
    draw.text(
        (90, 400),
        "3. IT 導入補助金 2026 (デジタル枠)",
        font=find_jp_font(18),
        fill=FG,
        anchor="la",
    )
    draw.text(
        (90, 430),
        "   一次資料: 中小企業庁 IT 導入補助金事務局",
        font=find_jp_font(15),
        fill=FG_MUTE,
        anchor="la",
    )
    draw.text(
        (90, 475),
        "各項目は制度名・適用期間・出典 URL・取得日時をまとめて表示します。",
        font=find_jp_font(16),
        fill=ACCENT,
        anchor="la",
    )
    img.save(HERE / "04-evidence-prefetch.png", "PNG", optimize=True)


def screenshot_disclaimer() -> None:
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    _frame(draw, w, h, "免責事項", "")

    draw.text(
        (w / 2, 130),
        "税理士法 第52条 への対応",
        font=find_jp_font(34),
        fill=FG,
        anchor="mm",
    )
    body_lines = [
        "本サービスは公的データの 横断検索・出典提示 を目的とした",
        "情報提供サービスです。税理士法 第52条 に基づく税務代理・",
        "税務書類の作成・税務相談 (個別の税務判断) には該当しません。",
        "",
        "個別の税務判断は、必ず貴社の 顧問税理士 にご確認ください。",
    ]
    y = 200
    for line in body_lines:
        draw.text((w / 2, y), line, font=find_jp_font(22), fill=FG_MUTE, anchor="mm")
        y += 40

    # Highlight: shown in UI footer + every API response
    box_y = 440
    draw.rounded_rectangle(
        (100, box_y, w - 100, box_y + 100), radius=10, fill=WARN_BG, outline=(255, 213, 145)
    )
    draw.text(
        (w / 2, box_y + 35),
        "プラグイン UI フッターに 常時表示",
        font=find_jp_font(20),
        fill=WARN_FG,
        anchor="mm",
    )
    draw.text(
        (w / 2, box_y + 70),
        "全 API レスポンスに `_disclaimer` フィールドを 同梱",
        font=find_jp_font(20),
        fill=WARN_FG,
        anchor="mm",
    )
    img.save(HERE / "05-disclaimer-footer.png", "PNG", optimize=True)


def main() -> None:
    make_icon()
    screenshot_subsidy()
    screenshot_tax()
    screenshot_invoice()
    screenshot_evidence_prefetch()
    screenshot_disclaimer()
    print("Generated:")
    for f in sorted(HERE.glob("*.png")):
        print(f"  {f.name}  ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
