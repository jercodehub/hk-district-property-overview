# 香港地區物業概覽

District Property Overview — 按 18 區瀏覽私人樓宇位置與樓齡的互動地圖。

## 功能
- 18 區篩選（開啟時顯示沙田區）。側欄頂部與頁首的「全港」一次顯示全部地區，並把地圖縮放到香港範圍；再點選某一區會回到該區的縮放與資料
- 按樓齡著色的地圖標記，點擊查看地址、類型、佔用許可年份與估算樓齡
- 地區視角和全港視角都用樓齡圓環聚合：環色是該組樓宇的樓齡比例，中間大字是平均樓齡、細字是幢數；點擊圓環會放大，放大到約 17 級後顯示個別樓宇
- 側欄列出目前範圍的樓宇數量、平均樓齡及樓齡分布
- 選中某一區或「全港」時，側欄同時顯示該範圍的私人住宅市場統計：總存量、落成量、空置量、空置率。色階地圖留待以後，這一版不靠分區多邊形
- 窄螢幕可收合側欄。頁首的「全港」在側欄收起時仍可點

全港約 5 萬幢。標記會按區暫存，第一次繪製時分段建立，並用 MarkerCluster 的 `chunkedLoading` 加到地圖上。城市層級（`fitBounds` 後大約 10–12 級，視乎視窗）的聚合半徑較細，圓環會散佈全港；13 級及以上沿用地區視角的半徑。

地圖只顯示樓宇點位，沒有公園、街市或交通站等設施圖層。

## 數據
`buildings.json` 由屋宇署「樓宇資料及樓齡紀錄」開放數據轉出，涵蓋全港 18 區（約 5 萬幢有佔用許可年份及座標的私人樓宇）。這不是抽樣檔。

- 數據集：`hk-bd-opendata-building-information`
- 下載：https://static.csdi.gov.hk/csdi-webpage/download/0e55c533715b5da3ae0ca6e6024e90b4/csv
- 每筆記錄：`addr`（地址）、`type`（佔用許可證上的用途，並註明座或平台）、`year`（佔用許可年份）、`lat`、`lng`
- 鍵名與頁面上的 18 區一致。源數據有些分區沒有「區」字，轉換時會補上。沒有分區的紀錄（例如落馬洲河套，標成 Out Of District）以及沒有佔用許可日期的紀錄不會放進地圖。

重新產生（需要網絡）：

```bash
python3 scripts/build_buildings.py
```

檔案若需要再縮小，可以每區抽樣，例如 `python3 scripts/build_buildings.py --max-per-district 400`。倉庫目前提交的是全量結果。

## 物業市場統計
側欄的市場卡片讀 `market-stats.json`。數字是**私人住宅單位**（設有專用煮食設施、浴室和廁所），不是地圖上的樓宇幢數。最新年底總存量來自差餉估價紀錄，不是「上年存量＋落成量」。

這一版用差餉物業估價署「物業市場統計」裡的「私人住宅 — 各區總存量、落成量及空置量」（資料一線通套件 `hk-rvd-tsinfo_rvd-property-market-statistics`）。表內有 18 區、港島／九龍／新界小計，以及全港。側欄只顯示選中的區，或全港那一列已公布的總數（腳本會核對它等於 18 區之和）。來源地名有時沒有「區」，轉換時補上，對齊頁面上的 18 個鍵。

- 數據集：https://data.gov.hk/tc-data/dataset/hk-rvd-tsinfo_rvd-property-market-statistics
- 中文 CSV：https://www.rvd.gov.hk/datagovhk/Dom_Stock_Completions_and_Vacancy_by_District_Chi.csv
- 英文對照：https://www.rvd.gov.hk/datagovhk/Dom_Stock_Completions_and_Vacancy_by_District_Eng.csv
- 「-」表示沒有錄得（卡片顯示「—」）。落成量佔存量的「+」表示少於 0.05%。
- 此表**沒有分區吸納量**。吸納量是全港按年系列，不能靠這張只有一年空置的表倒推各區。
- 此表**沒有分區樓價**。

重新產生（需要網絡；也可把已下載的 CSV 傳給 `--input`）：

```bash
python3 scripts/build_market_stats.py
```

### 哪些數據適合疊到這張地圖
適合、但這一片還沒做：

- 同套件的「按地區分類的總存量」（A–E 類單位）和「各區落成量及預測落成量」。預測由 2025 年起包含港人首次置業的資助出售單位，若要顯示必須註明。
- 「各區洋房總存量及落成量」只是私人住宅裡的洋房子集。
- `hk-rvd-tsinfo_rvd-statistical-tables-on-valuation-list-and-government-rent-roll` 有 18 區的估價冊評估數目和應課差餉租值。那是估價，而且涵蓋各類物業，不是私人住宅成交價。

不適合直接做成 18 區樓價或吸納量：

- 售價／租金指數多數是全港、按單位類別，不是 18 區。
- 平均租金和售價的地理只到港島、九龍、新九龍、新界，不是區議會 18 區。
- 個別屋苑指數是選定屋苑，不是分區。
- 吸納量是全港系列（實用面積 100 平方米以下／以上），沒有 18 區。
- 寫字樓、商舖、工廈、貨倉的分區存量是另一類物業，不要不加說明就疊在私人住宅樓齡上。
- 土地註冊處相關的 `hk-landsd-lao-*` 是註冊／申請統計，不是二手買賣成交。
- 房委會出售數據是資助房屋，不是這張私人住宅地圖的主體。

分區色階可以之後用同一份 `market-stats.json`，不需要先有多邊形。

## 本地預覽
用瀏覽器直接開啟 `index.html` 時，`fetch` 讀不到旁邊的 JSON。請先在倉庫根目錄啟動靜態伺服器：

```bash
python3 -m http.server 8080
```

然後開啟 http://localhost:8080/ 。

## 部署
可放在 GitHub Pages，發佈倉庫根目錄即可。`buildings.json` 約 6–7 MB。
