# 香港地區物業概覽

District Property Overview — 按 18 區瀏覽私人樓宇位置與樓齡的互動地圖。

## 功能
- 18 區篩選（開啟時顯示沙田區）。側欄頂部與頁首的「全港」一次顯示全部地區，並把地圖縮放到香港範圍；再點選某一區會回到該區的縮放與資料
- 按樓齡著色的地圖標記，點擊查看地址、類型、佔用許可年份與估算樓齡
- 地區視角和全港視角都用樓齡圓環聚合：環色是該組樓宇的樓齡比例，中間大字是平均樓齡、細字是幢數；點擊圓環會放大，放大到約 17 級後顯示個別樓宇
- 側欄列出目前範圍的樓宇數量、平均樓齡及樓齡分布
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

## 本地預覽
用瀏覽器直接開啟 `index.html` 時，`fetch` 讀不到旁邊的 JSON。請先在倉庫根目錄啟動靜態伺服器：

```bash
python3 -m http.server 8080
```

然後開啟 http://localhost:8080/ 。

## 部署
可放在 GitHub Pages，發佈倉庫根目錄即可。`buildings.json` 約 6–7 MB。
