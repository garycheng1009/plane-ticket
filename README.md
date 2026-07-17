# 機票價格追蹤器

這是一個可放到 GitHub Actions 每天自動執行的機票價格追蹤工具。GUI 用 Streamlit 編輯 `config.json`，追蹤器會把每日最低價寫入 `data/prices/*.json`，符合條件時用 LINE Messaging API 推播。

## 功能

- 航線可用 `config.json` 擴充
- 支援指定日期、航空公司、排除航空公司、直飛、去回程時段
- 支援低於最高價格通知、漲價通知
- 每天紀錄 JSON 歷史價格
- 最近 30 天平均、最低、目前價與購買建議
- 資料來源可插拔，目前含 `eztravel`、`skyscanner`、`mock`

## 安裝

```bash
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config.example.json config.json
```

## 開 GUI

```bash
streamlit run app.py
```

## 試跑追蹤器

```bash
python tracker.py --config config.json --dry-run
```

只測單一航線：

```bash
python tracker.py --config config.json --dry-run --route tokyo
```

如果 Windows 終端機顯示中文亂碼，可先設定：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python tracker.py --config config.json --dry-run
```

## LINE 設定

LINE Notify 已於 2025-03-31 結束服務，建議使用 LINE Messaging API。

在 GitHub repo 的 Secrets 新增：

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_TO`

本機可用環境變數設定同名值。

## 注意

ezTravel 和 Skyscanner 都是動態網站，可能會因反自動化、驗證、版面改版或使用條款限制而無法長期穩定抓取。這個專案把資料來源包成 adapter，之後可以替換成正式 API 或其他來源。
