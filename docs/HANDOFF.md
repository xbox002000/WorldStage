# 交接文件（給第一次接手這個專案的 AI agent）

最後更新：2026-10-02，提交 `1a02ac0` 之後。先讀這一頁，再照「閱讀順序」往下。

## 這個專案在做什麼
一個像《楚門的世界》那樣**自己運轉的世界**：角色依自己的背景、個性、記憶和處境過日子；系統從中**發現**真的戲，編成一集，之後拍出來發佈。
流程：世界（事件溯源）→ 敘事讀取（發現戲、編一集）→ 製作中間格式（鏡頭單）→ 影片模型（目前只 dry-run）。

## 紅線（違反就是錯，有測試把關）
- `world.db` 是唯一真相，**只有 `apply_event` 能寫入**。LLM 只提出意圖，由規則裁決。
- `narrative/`、`runtime/`、導播室、台詞都是**讀取模型**，永遠不寫回世界。
- 製作人（`producer/`）只能透過封閉詞彙（`world/interventions.py`）介入；不 import Simulation（`tests/test_layers.py`）。
- **舊配方行為不能變**：純重構或新功能都要跑行為指紋；新機制一律做成新的 primitive，只在新配方開啟。
- 套件（`world/domains/*.py`）單檔 ≤ 600 行（`tests/test_domains.py`）。
- 隨機只能用 `world/rng.py`（`tests/test_rng.py` 會擋 `random.Random(` 與內建 `hash(`）。
- 感情線雙方都要 ≥ 18 歲；畫面不露骨。真人一律虛構化，發佈前掃描禁用名。
- 預算 $0。**下載、付費、發佈、git 提交、排程或持久設定，都要使用者明確同意。** API key 只在 Windows 環境變數，絕不讀出、印出或寫進檔案。

## 使用者的工作方式
- 用**繁體中文**回報，附數字（改前／改後、樣本數、信賴區間），並寫明**哪些沒有成立**。
- 使用者常貼第三方的建議或評估：逐條驗證，採納、調整或拒絕，並說明理由。
- 使用者常說「全權交給你」：自己決定，不要事事詢問；但上面的同意事項例外。
- 只有使用者說要提交才提交，而且**用明確的路徑** `git add`，不要 `git add -A`。遠端：`https://github.com/xbox002000/WorldStage`（`master` 推到 `main`）。

## 閱讀順序
1. `README.md`、`docs/architecture/`（分層、邊界、如何接新影片模型：`provider_conformance.md`）。
2. 計畫與決策紀錄：`C:\Users\xbox0\.claude\plans\concordia-fuzzy-creek.md`。很長，**只讀最上面的 v0.8 與各段「進度紀錄」**。
3. 使用者記憶：`C:\Users\xbox0\.claude\projects\E--work-video\memory\`（偏好、工具路徑、Windows 的坑）。
4. 依主題：`docs/producer.md`（製作人）、`docs/episode_planner.md`（一集怎麼編）、`docs/speech.md`（對白）、`docs/soul.md`＋`docs/soul_scale.md`（角色接 LLM）、`docs/jianghu_drama.md`（新江湖內容包）、`docs/impression.md`（外貌／親和／話量）、`docs/studio.md`（導播室）。
5. `git log`：每個提交訊息都寫了做了什麼與量到的數字。

## 地圖（主要目錄）
| 目錄／檔案 | 做什麼 |
|---|---|
| `world/` | 真相：`db.py`、`simulation.py`（每天的迴圈）、`domains/*`（套件：比武、感情、派系、印象…）、`content/*`（角色名冊與內容包）、`recipes/*.json`（配方＝內容＋開哪些 primitive） |
| `agent/` | 決策：`volition.py`（規則代理）、`cognition.py`（LLM 心智，在喚醒點才想）、`llm.py`＋`llm_cache.py`＋`llm_ledger.py` |
| `producer/` | 製作人：安排處境，不決定結果（預設策略 `greedy`） |
| `narrative/` | 讀取：`episode_planner.py`（一集）、`lint.py`（劇本檢查）、`speech.py`（台詞）、`state.py`、`inner_state.py`、`payoff.py`（爽點） |
| `production/`、`contracts/` | 與模型無關的鏡頭單、資產冊（Bible）、合約與 JSON schema |
| `channel/studio.py`＋`render/studio/` | 導播室（網頁）；`render/godview/` 是 3D 觀測台 |
| `soul_lab.py`、`soul_stats.py` | 讓角色接 LLM 跑世界、統計 |
| `out/` | 產出（不進版控） |

## 指令
全套測試，約 25 分鐘：

```bash
.venv/Scripts/python -m unittest discover -s tests -t .
```

舊配方行為不能變：

```bash
.venv/Scripts/python -m tests.refactor_baseline --check out/refactor_baseline.json
```

導播室（之後開 http://127.0.0.1:8795/，右上角切換世界）：

```bash
.venv/Scripts/python -m channel.studio --preset drama --days 14 --out out/studio_hub --mind out/soul/soul503 --port 8795
```

角色接 LLM，先用假心智試跑（不連網、不花額度）：

```bash
.venv/Scripts/python soul_lab.py --name test --days 3 --dry
```

## 踩過的坑
- **一律用 `.venv/Scripts/python`**（3.12）；系統的 `python` 是另一個版本，曾經讓整個實驗跑錯。
- **絕不要用「CPU 時間」去找並殺 python 行程**：會殺掉使用者的伺服器。要停伺服器就用埠號找 PID，或停自己開的背景工作。
- 改完 `render/` 的靜態檔，瀏覽器常拿舊快取：伺服器已送 `no-store`，仍要 Ctrl+F5。
- **LLM 快取的鍵是提示全文**：不只改提示本身，改任何會進到提示的文字（目標文字、話題詞、名字）都會讓已記錄的 LLM 世界在那一天重播失敗（例：「攢下N文錢」讓 drama701 的第 6 天對不上）。補救：複製它的 `*.llm_cache.db` 成新名字，用同樣參數重跑 `soul_lab.py`，只有變動的提示會重問（這次 2 次）。提示目前有 v1／v2／v3（v3 多要一句說出口的話）。
- 免費額度：答案先查快取；額度用完當天就停，世界退回上一個完整日子，隔天續跑。`flash-lite` 一天至少 252 次沒被拒絕過。
- Git Bash 的 heredoc 遇到引號容易壞：較長的修改用 Edit 工具或先寫成腳本檔再執行。
- 平行派子代理時，**每個代理只改自己的檔案**，共用檔（`contracts/versions.py`）只准小範圍加一行。

## 現況（2026-10-02）
- 全套 1069 個測試全過（2 個跳過，2026-10-02）；舊配方指紋 identical。
- 已完成：製作人、爽點、Episode Planner v0.2、情境台詞與潛台詞、表面情緒與真正原因、A/B 故事進封包、資產冊與一致性套件、導播室（含角色時間軸、劇本問題、LLM 心聲）、角色接 LLM（11 種子實驗）、劇本檢查器（512 → 0）、`jianghu_drama` 內容包與繼位過程、第一印象、目標要掙來。

## 下一步（照優先順序）
1. **角色卡與角色工坊**（計畫 v0.8 的 C13–C17）：一張卡＝一個人、角色與世界脫鉤、讓參數真的影響行為、原型生成器（決定性隨機、可鎖定）、導播室裡的 🎲／🔒 介面。
2. **好人卡變成故事**：目前只是狀態，14 天沒有追求或告白；要改感情公式（只在新配方）。
3. **像電視劇的因果**（v0.8 的 E23–E26）：恩情與欠債、家與責任、秘密當籌碼、師徒偏心、友情選邊；量「起因跨線的比例」。
4. 小問題：目標文字「存到 N 元」的貨幣字；「你師兄」這類稱呼；集變薄（每集 3.2 場），要不要放寬前情由使用者看過再決定。
5. 用提示 v2 跑真的 LLM 世界（花額度，先問使用者），量回答被擋掉的比例。
