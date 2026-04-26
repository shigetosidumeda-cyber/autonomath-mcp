# Prompts page screenshot TODO

Reserved `<img>` slots in `site/prompts.html` point here. Each `.png` should be a
Claude Desktop (or Cursor) screenshot showing the prompt executed against the MCP server,
width ~1200px, 72-96dpi, letterboxed PNG.

File naming is `NN-slug.png`:

- [ ] `01-aomori-apple.png` — #1 青森 × りんご × 新規就農
- [ ] `02-niigata-rice.png` — #2 新潟 × 米 × 法人経営
- [ ] `03-hokkaido-dairy.png` — #3 北海道 × 酪農 × 環境保全
- [ ] `04-tokyo-manufacturing.png` — #4 東京 × 製造業 × 設備投資
- [ ] `05-osaka-it.png` — #5 大阪 × サービス業 × IT導入
- [ ] `06-fukuoka-restaurant.png` — #6 福岡 × 飲食 × 創業融資
- [ ] `07-keiei-kyoka-tax.png` — #7 経営強化法 税制優遇 棚卸し
- [ ] `08-invoice.png` — #8 インボイス対応 × 補助金 申請予定
- [ ] `09-combo-check.png` — #9 候補 5 つ 併用可否 判定
- [ ] `10-keiei-vs-koyo.png` — #10 経営開始資金 × 雇用就農資金 併用判定

Until these files exist, `onerror` in `prompts.html` swaps in a dashed `[ screenshot-N ]`
placeholder, so the page renders cleanly without broken image icons.
