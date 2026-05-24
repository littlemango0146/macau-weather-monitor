# 澳門氣象資料站

地圖優先的澳門氣象站資料網站。後端定時抓取澳門氣象局 XML，寫入 SQLite；前端顯示站點地圖、即時資料、排行與歷史圖表。

## 部署方式

這個專案支援兩種模式：

- 本機完整模式：FastAPI + SQLite + APScheduler，適合開發與校內電腦長期運行。
- GitHub Pages 靜態模式：GitHub Actions 定時抓取 SMG XML，生成 `dist/index.html`，部署到 GitHub Pages。

GitHub Pages 不能長期運行 FastAPI 後端；公開版會使用 Actions 生成的靜態快照。

## 啟動

```powershell
D:\anaconda\python.exe -m app.cli init-db
D:\anaconda\python.exe -m app.cli collect-once
powershell -ExecutionPolicy Bypass -File scripts\start_site.ps1 -OpenBrowser
```

打開 `http://127.0.0.1:8000`。

如果 Codex 內建瀏覽器或校內環境打不開 localhost，可以匯出可直接打開的離線版：

```powershell
D:\anaconda\python.exe -m app.export_static
```

然後打開 `dist\offline.html`。

第一版建議用 Windows 工作排程器每 5 分鐘執行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_collect_task.ps1
```

## 管理

```powershell
D:\anaconda\python.exe -m app.cli backup
```

資料庫預設位置：`data/weather.sqlite`。

## GitHub Pages

推送到 GitHub 後，到 repository 的 Settings → Pages，將 Source 設為 GitHub Actions。

 workflow 位置：

```text
.github/workflows/pages.yml
```

它會：

1. 安裝 Python 依賴。
2. 執行測試。
3. 抓取最新 SMG XML。
4. 生成 `dist/offline.html`。
5. 複製為 `dist/index.html`。
6. 發佈到 GitHub Pages。

預設每 30 分鐘更新一次，也可以在 Actions 頁面手動執行。

## 上傳到 GitHub

如果已安裝並登入 GitHub CLI：

```powershell
git init
git add .
git commit -m "Initial Macau weather monitoring site"
gh repo create macau-weather-monitor --public --source=. --remote=origin --push
```

如果不用 GitHub CLI，先在 GitHub 建立空 repo，再執行：

```powershell
git init
git add .
git commit -m "Initial Macau weather monitoring site"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/macau-weather-monitor.git
git push -u origin main
```
