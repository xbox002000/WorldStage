# 外貌、親和、話量與第一印象（primitive `social.impression`，impression_v0.1）

> 計畫 v0.8 的 D19–D22。草稿，只在開啟 `social.impression` 的配方生效；沒有開的配方逐筆不變。
> 先寫驗收標準（第 1 節，跑之前寫定），設計在第 2、3 節，結果在第 5 節，沒成立的在第 6 節。

## 1. 驗收標準（跑之前寫定，不調權重硬拉）

對照：同一個種子、同一份內容（`jianghu_story_v1` 的 pillars／base），差別只有 `social.impression`。
測試配方只在 tests 裡註冊（`impression_test_v1`），不是 `world/recipes/` 的正式配方。
種子 7、11、23，各 14 天，每世界 10 人，三個種子合併 n = 30。對照組與實驗組用**同一組** looks／warmth（取自內容檔），
這樣兩組算出來的相關係數才比得起來。

指標（每人 X）：
- `A_X` ＝ 前 3 天（時間 < 3×1440）以 X 為 target 的 `talk` 事件數（被搭話次數）。
- `T_X` ＝ 第 14 天結束時，其他 9 人對 X 的 trust 平均。
- Spearman：ρ_A ＝ ρ(looks, A)，ρ_T ＝ ρ(looks, T)，ρ_W ＝ ρ(warmth, T)。

通過條件：
1. 外貌與被搭話：實驗組 ρ_A ≥ 0.30，且比對照組高至少 0.15。
2. 外貌與信任變弱：實驗組 ρ_T ≤ ρ_A − 0.15；親和與信任：實驗組 ρ_W 高於對照組 ρ_W（熟了之後看性格）。
3. 高冷被誤讀後翻轉（至少 1 對，列事件 id）：一對 (Y, X)，`talk` 事件的 `truth.impression.misread` 把 Y 對 X 的
   respect 往下推過，第 14 天時 Y 對 X 的 respect 比第 0 天高至少 0.10，且之後有 `truth.impression.revealed` 事件。
4. 好人卡單戀（至少 1 對，列事件 id）：第 14 天，P 的親和 ≥ 0.6 且外貌 ≤ 0.45；P 對 Q 的 attraction ≥ 0.22；
   Q 對 P 的 affection ≥ 0.30，而 Q 對 P 的 attraction < 0.15。
5. 沒啟用的既有配方逐筆不變：`python -m tests.refactor_baseline --check out/refactor_baseline.json` 輸出 identical
   （基準在開工時就記好，且當時是乾淨狀態）。
6. 已記錄的 LLM 世界仍可重播：`python -m channel.studio --mind out/soul/soul503 --out out/tmp_d --no-serve` 逐筆驗證通過。
7. 成年人規則（≥18 才進感情線）、隱私與真人規則不放寬：test_romance、test_persona 全過。

## 2. 設計

### 2.1 三個數字放在哪裡

`contracts/persona.py` 的 `CharacterGenome` 多三個**選用**欄位：`looks`（外貌）、`warmth`（親和）、`talkativeness`（話量），各 0..1，預設 `None`。

- **不進 genome 雜湊。** `hash()` 排除這三個欄位（`IMPRESSION_FIELDS`），所以不論有沒有設定，`genome_id` 都不變。
  原因：計畫要求「補了值也不得改變既有雜湊」，而「None 不入雜湊、有值才入雜湊」這條路做不到：補值後三個內容包 20 個角色的 id 都會變。
  代價：`genome_id` 不再保證「內容相同」涵蓋這三個數字——它們是疊在同一個人身上的呈現層。
- **只在開了 primitive 的配方才寫進世界資料。** `world/personas.py` 的 `stored()`：沒開 `social.impression` 的世界，`character_genomes` 那一列和以前逐字相同
  （三個欄位不寫入），所以 `character_genomes` 的快照雜湊也不變。開了的世界才把內容檔的數字寫進列裡。
- 內容檔（`world/content/genomes/*.json`）用 `EXTRA_PLAIN` 讀入並驗證（0..1 的數字，否則 `PersonaError`）。
  只補了 `town_v1.json` 與 `jianghu_v1.json`；`town_in_jianghu`（以及 `jianghu_story`）沒有自己的 genome 檔，沿用 `town_v1` 的人，所以也有數字。
- **證據圖譜：** `world/persona_evidence.py` 的 `fields()` 在三個欄位有值時把它們列為欄位路徑（`looks`、`warmth`、`talkativeness`），
  `authored()` 會替它們產生作者設定的證據。profile 顯示：套件的 `describe()`（外貌、親和、話量、答話）。
- 角色驗證沿用 `lift`：未知欄位、超出範圍都拒絕。

沒設定時由現有資料推導（`impression.values`）：
- `looks` ＝ `charm`（沒有 genome 時 0.5）。
- `warmth`、`talkativeness` ＝ `derive(temperament, social style)`，固定公式：

```text
style_warm = clamp(0.10 x (暖詞數 - 冷詞數), -0.2, 0.2)      暖詞：熱情 親切 友善 自來熟 八面玲瓏 笑臉 熱心 照顧 寬厚 豪爽 大方 護短
style_talk = clamp(0.10 x (多話詞數 - 少話詞數), -0.2, 0.2)   冷詞：冷淡 防備 傲氣 驕傲 威嚴 霸氣 若即若離 不願牽絆 藏得很深
                                                              多話詞：話多 太黏 黏人 愛誇大 愛逞強 嘴巴壞 熱情 自來熟 八面玲瓏 熱心 豪爽
warmth = 0.15 + 0.40 generosity + 0.20 (1 - temper) + 0.15 honesty + style_warm     少話詞：少 少言 安靜 慢熱 沉默 冷淡 嘴笨 不善表達
talk   = 0.10 + 0.40 gossip + 0.25 curiosity + 0.10 generosity + style_talk         （詞比對 social 的 strangers／friends／intimate；單字詞必須整個詞相等）
```

### 2.2 內容檔的數字（作者依 presence 與個性填的；括號是同一個人用公式推出來的值）

town_v1（也是 jianghu_story 的人）：

| id | 名 | charm | looks | warmth（推導） | talk（推導） | presence |
|---|---|---|---|---|---|---|
| ming | 阿明 | 0.70 | 0.65 | 0.35 (0.41) | 0.80 (0.49) | 站得很直，一開口就像在開會 |
| mei | 小美 | 0.85 | 0.90 | 0.25 (0.32) | 0.15 (0.18) | 不說話的時候最吸引人，像隨時會離開 |
| jun | 阿俊 | 0.45 | 0.35 | 0.65 (0.28) | 0.45 (0.34) | 讓人想幫他一把 |
| lan | 阿蘭 | 0.60 | 0.65 | 0.90 (0.69) | 0.60 (0.58) | 溫柔，卻讓人覺得她很容易受傷 |
| hao | 阿豪 | 0.75 | 0.75 | 0.80 (0.88) | 0.90 (0.95) | 走進來就像把燈打開 |
| yun | 小雲 | 0.55 | 0.55 | 0.30 (0.35) | 0.20 (0.14) | 安靜，讓人忍不住想問她在想什麼 |
| kai | 阿凱 | 0.50 | 0.50 | 0.30 (0.42) | 0.55 (0.59) | 整潔得讓人不敢隨便 |
| ning | 阿寧 | 0.65 | 0.65 | 0.40 (0.51) | 0.20 (0.12) | 內向，像一本不隨便翻開的書 |
| tao | 阿濤 | 0.40 | 0.30 | 0.80 (0.38) | 0.40 (0.30) | 樸實，講話不拐彎讓人安心 |
| rui | 小瑞 | 0.70 | 0.60 | 0.90 (0.95) | 0.65 (0.51) | 讓場面自然變得和氣 |

jianghu_v1：

| id | 名 | charm | looks | warmth（推導） | talk（推導） | presence |
|---|---|---|---|---|---|---|
| lin | 林遠山 | 0.55 | 0.55 | 0.45 (0.55) | 0.35 (0.30) | 不怒自威，所到之處自然安靜 |
| lu | 陸青 | 0.75 | 0.75 | 0.50 (0.35) | 0.40 (0.32) | 武功出眾的光環，卻藏著心虛 |
| su | 蘇小婉 | 0.80 | 0.80 | 0.85 (0.81) | 0.85 (0.63) | 天真熱心，讓人想保護 |
| shi | 石頭 | 0.50 | 0.50 | 0.45 (0.47) | 0.60 (0.30) | 憨直倔強，不服輸 |
| tie | 鐵萬鈞 | 0.60 | 0.55 | 0.40 (0.45) | 0.90 (0.50) | 霸氣外露，進門先占中間的位子 |
| hong | 鐵驚鴻 | 0.80 | 0.85 | 0.25 (0.33) | 0.35 (0.30) | 少年得意，讓人又羨又恨 |
| han | 韓七 | 0.50 | 0.45 | 0.55 (0.57) | 0.65 (0.52) | 客氣得讓人放下戒心 |
| hua | 花三娘 | 0.85 | 0.85 | 0.90 (0.82) | 0.80 (0.68) | 八面玲瓏，誰都覺得被她看重 |
| zhou | 老周 | 0.35 | 0.30 | 0.65 (0.65) | 0.95 (0.94) | 一開口所有人都會靠過來聽 |
| yan | 燕飛 | 0.90 | 0.90 | 0.20 (0.32) | 0.10 (0.15) | 來歷不明，讓人好奇又不敢靠近 |

公式推不出「樣貌普通但性格好」：阿濤的慷慨只有 0.1，公式給他 0.38 的親和，作者才補成 0.80。推導值只是沒人設定時的底。

### 2.3 規則：每條都有「產生」與「讀取」

| 規則 | 產生（誰寫了什麼） | 讀取（誰讀、讀了改什麼） | 位置 |
|---|---|---|---|
| 注意 | 三個數字（genome 或推導）；熟悉度（`social.depth`） | 選誰說話：每個 talk 選項的分數加 `LOOK_ATT×(looks−0.5)×(1−熟)＋WARM_ATT×(warmth−0.5)×熟`，**減去這個人眼前所有對象的平均**（只改「對誰」不改「說多少」；第一版沒有減平均，動作比例被推歪） | `Impression.shape` |
| 話量（開口） | `talkativeness`（genome 或推導） | 主動開口：talk 加 `TALK_DRIVE×(talk−0.5)`，tell 加 `TELL_DRIVE×(talk−0.5)` | `Impression.shape` |
| 話量（回話） | 同上；世界變數 `impression.talk.<pid>`（起始值由風格詞，之後每晚由 `overnight` 校成當日的值，心情差時降到 0.6 倍） | 回應評分：新鉤子 `Domain.reticence`（預設 0.0），`agent/reply.py` 把它加到「不回話」那一項，只有套件覆寫時才生效；回話長短給台詞用的唯讀函式 `reply_length(conn, pid)`（short／normal／long，門檻 0.33／0.67）；**沒改 `narrative/speech.py`** | `Impression.reticence`、`agent/reply.py`、`reply_length` |
| 高冷被誤讀 | `Presence.cold() = looks×(1−talk)×(1−warmth)`，≥ 0.20 才算；熟悉度 | 初期（熟悉度 < 0.20）在不是溫暖語氣的 `talk` 事件裡，對方對他的 respect 與 affection 往下推；事件 `truth.impression.misread` 記下誰讀誰、冷度、熟悉度；熟悉度 ≥ 0.20 後同樣的往來反過來把 respect、affection 往上推（上限約 0.5），記為 `revealed`。用既有欄位 respect、affection，數字都在事件的 `event_deltas`。（沒用 `estimate`：那是「他有多強」的能力估計，不是對他態度的估計。） | `Impression.effects` |
| 被議論 | 外貌 | tell 選項：說的是別人的事時加 `GOSSIP_LOOKS×2×(looks−0.5)`（外貌高的更常被傳，普通的略少） | `Impression.shape` |
| 嫉妒 | 外貌；性別（profile）；在場的人 | 同一地點的 talk／flirt／date／confession（被接受的）事件，被注意的那位（target）和在場、同性、外貌至少低 0.20 的人：對他的 resentment 加 `ENVY×差距`（兩人都被說話的人吸引時 ×2.5）；事件 `truth.impression.envy`。resentment 是既有欄位，會降低吸引、讓語氣變冷（`social.depth`、romance 都讀） | `Impression.effects` |
| 好人卡（好感） | `warmth` | 非敵意、非冷的 talk：對方對他的 affection 加 `WARM_AFFECTION×(warmth−0.45)`；trust 另外隨熟悉度上升 `WARM_TRUST×(warmth−0.45)×熟` | `Impression.effects` |
| 好人卡（吸引） | `looks` | `romance.charm()`：primitive 啟用時讀 `looks` 取代只讀 `charm`；`drawn_level`、示好效果因此跟外貌走，不跟親和走。公式本身沒改（`0.15 + 0.55×charm + 0.30×相容 − …`） | `romance.py` |
| 可拍的場景 | 上面的事件與關係欄位 | `situations`：misread（被誤會）、misread_turn（誤會解開）、friend_zone（被當朋友）給 `narrative/dramaturgy.py` | `Impression.situations` |

沒有改的：`world/attention.py` 的 `noticers`（誰「看見」一件事）。計畫說「誰被看見」也讀外貌，但那個檔案不在這一輪的範圍；
目前外貌只透過「被找來說話」與「被議論」影響注意，沒有進到「誰在旁邊看見」的抽籤。

新增的鉤子只有一個：`Domain.reticence(conn, pid, other, now) -> float`（`world/domains/base.py`，預設 0.0，只增不改；`agent/reply.py` 只在有套件覆寫時才呼叫）。
`shape` 本來就是「選擇前的最後一句話」，注意與話量用它就夠，沒有新增 `attention` 鉤子。

### 2.4 欄位影響表（每個欄位：影響行為／只影響台詞／只影響外觀）

| 欄位 | 只在… | 影響行為 | 只影響台詞（LLM 提示、導播室文字） | 只影響外觀 |
|---|---|---|---|---|
| `looks` | 開了 `social.impression` 的配方 | 是：誰被找說話（隨熟悉度淡出）、被傳話、被同性嫉妒、被吸引的程度（romance） | 否 | 否（`appearance` 才是外觀） |
| `warmth` | 同上 | 是：好感漲得快、熟了之後被信任、熟了之後被注意；高冷被誤讀的判定 | 否 | 否 |
| `talkativeness` | 同上 | 是：主動開口與傳話的機率、回話的機率（`reticence`）、高冷判定、`impression.talk.<pid>`；回話長短（`reply_length`）給台詞用，**台詞端尚未讀** | 回話長短（待 speech.py 接） | 否 |
| `charm` | 所有配方 | 是（感情）：沒開 primitive 時就是被吸引的程度與示好效果；開了之後改讀 `looks`（沒設定時 `looks = charm`） | 否 | 否 |
| `appearance.*`（face、hair、build、marks、looks_age） | 所有配方 | 否 | 否 | 是（角色鎖、設定集；`production/bible.py`） |
| `appearance.presence` | 所有配方 | 否（作者寫三個數字時的依據，不被規則讀） | 否 | 是（設定集的神態一行） |
| `voice.*` | 所有配方 | 否 | 否（設定集的聲音描述） | 是（聲音） |
| `temperament`（honesty、temper、gossip、generosity、curiosity） | 所有配方 | 是（既有規則）；沒設定三個數字時也是推導 `warmth`／`talk` 的輸入 | 是 | 否 |
| `profile.social`（strangers／friends／intimate 詞） | 所有配方 | 只在沒設定三個數字時，經由推導公式影響行為 | 是 | 否 |
| genome 雜湊 | — | 三個欄位**不在**雜湊裡 | | |

## 3. 檔案

- `contracts/persona.py`（三欄位、`IMPRESSION_FIELDS`、`hash()` 排除）、`contracts/schemas/character_genome.schema.json`（重新產生，只有這一個檔案變）。
- `world/personas.py`（`EXTRA_PLAIN`、驗證、`stored`）、`world/persona_evidence.py`（`fields`）。
- `world/content/genomes/town_v1.json`、`jianghu_v1.json`（只加三個欄位）。
- `world/domains/impression.py`（新，約 300 行）、`world/domains/__init__.py`（BUILTIN 加一行）、`world/domains/base.py`（`reticence`）、`world/domains/romance.py`（`charm()`）。
- `agent/reply.py`（`_reticence` 與一處呼叫）。
- `contracts/versions.py`（`impression_model`）、`tests/test_versions.py`、`tests/test_impression.py`（新，45 個測試）。
- 整合：把 `social.impression` 加進正式配方的 `base`（A2 的 `jianghu_drama_v1`）即可；那個內容包若有自己的 genome 檔，在人物下加 `looks`／`warmth`／`talkativeness`。

## 4. 實驗做法

`impression_test_v1`＝`jianghu_story_v1` 的 `base` 加 `social.impression`（`dataclasses.replace`，只在腳本與測試裡註冊）。
VolitionDecider(seed)，14 天，種子 7、11、23，對照組是 `jianghu_story_v1` 同種子。腳本在 scratchpad（`lab.py`、`accept2.py`，不在 repo）。

跑了兩次，兩次都留數字：
- **第一版（run 1）**：注意的加成直接加在 talk 選項上。看副作用時發現動作比例被推歪（三個種子合計 talk 2661→2971 ＋12%，tell 185→120 −35%，goal_change 81→54，accuse 10→6）。
- **第二版（run 2，現行）**：注意改為「減去眼前所有對象的平均」（只改對誰、不改說多少），八卦的外貌項改成雙邊（外貌低的略少）。
  這次修改的理由是動作比例，不是為了驗收數字；改前我已經看過 run 1 的相關係數，這點要講清楚。其餘常數（`LOOK_ATT` 等）沒有調過，都是第一次寫下的值，
  只有 `F_KNOWN = 0.30` 是先看了對照組的熟悉度分布（6 天後中位數 0.16、最大 0.34）才定。

## 5. 結果（run 2，現行程式）

### 5.1 相關係數（Spearman，3 種子合併 n = 30；括號是 bootstrap 90% 區間，2000 次）

| | ρ_A（外貌 vs 前 3 天被搭話） | ρ_T（外貌 vs 第 14 天信任） | ρ_W（親和 vs 第 14 天信任） |
|---|---|---|---|
| 對照（不啟用） | 0.07（−0.30, 0.42） | 0.39（0.08, 0.64） | 0.30（−0.05, 0.59） |
| 啟用 | **0.47（0.19, 0.70）** | **0.15（−0.17, 0.44）** | **0.53（0.27, 0.74）** |

逐種子（啟用）：ρ_A 0.39／0.63／0.49；ρ_T 0.18／0.28／0.03；ρ_W 0.80／0.11／0.77。對照的 ρ_A：−0.12／0.04／0.33。

- 條件 1：ρ_A 0.47 ≥ 0.30，且比對照高 0.40 ≥ 0.15。**通過。**
- 條件 2：ρ_T 0.15 ≤ ρ_A − 0.15 ＝ 0.32；ρ_W 0.53 > 對照 0.30。**通過。** 但樣本小：區間很寬，ρ_W 的兩組區間有重疊。對照的 ρ_T 本來就偏高（0.39），
  是因為那個內容裡外貌高的人（小美、阿蘭、阿豪）恰好也被信任，啟用後降下來是「外貌不再直接買信任」＋「親和買信任」的混合，不能全算在外貌上。

被搭話次數（前 3 天，三種子平均）：小美 17.7（對照 19.7）、阿豪 30.3（19.0）、阿蘭 22.3（15.7）、阿濤 11.0（20.3）、阿俊 17.0（18.3）。
注意：高冷的小美並沒有比對照多被搭話；被找得最多的是**外貌中等偏上又親切、愛說話**的人（阿豪、阿蘭）。外貌最高但冷的人沒有吃到好處，推測是她自己話少、往來少，抵銷了注意力的加成（推測，沒有拆開驗證）。

### 5.2 高冷被誤讀後翻轉（條件 3）：通過

三個種子共 27 對有「先被誤讀、之後被揭曉」的紀錄，其中 7 對第 14 天的 respect 比第 0 天高至少 0.10。前三名：

| 種子 | 讀的人→被讀的人 | 第 0 天 respect | 最低 | 第 14 天 respect | 第一次 misread 事件 | 第一次 revealed 事件 | 同種子對照組第 14 天 respect |
|---|---|---|---|---|---|---|---|
| 23 | 小瑞→小美 | 0.00 | −0.161（事件 1062） | **+0.331** | 27 | 544 | 0.00 |
| 11 | 阿蘭→小美 | 0.00 | −0.115（事件 392） | +0.262 | 94 | 488 | 0.00 |
| 7 | 阿蘭→阿寧 | 0.00 | −0.027（事件 256） | +0.256 | 250 | 694 | 0.00 |

誠實的限制：**初期的往下是淺的**。68 對被誤讀的人，respect 最低點比起點平均只低 0.087（最深 −0.399）；真正大的是之後的翻轉（+0.2～+0.33）。
也就是說「初期偏差」有、可追溯，但幅度小；「翻轉」的幅度比「誤讀」大。種子 11 的阿蘭→小美 respect 翻成 +0.26，affection 卻是 −0.625：respect 的翻轉是規則給的，affection 的暴跌是這個世界別的事件造成的（沒有追究）。

### 5.3 好人卡（條件 4）：**照原條件沒有達到**

原條件（Q 對 P 的 attraction < 0.15，且 P 對 Q ≥ 0.22、Q 對 P 的 affection ≥ 0.30）：三個種子、啟用組 **0 對**（對照組也是 0）。
原因：Q 對 P 的 attraction 低於 0.15 的組合出現過（啟用組 2 對、對照組 3 對，對象都是阿濤、阿俊），但那些對的 affection 都沒到 0.30。
我事先寫的 0.15 太貼近 `drawn_level` 的底（`0.15 + 0.55×looks + …`，再乘熟悉度係數）：被吸引的對象在熟悉度 0.2 時大約落在 0.11–0.27。

事後放寬（**不是原條件，只是找東西看**）：把「低」改成程式自己的界線 `DRAWN = 0.22`（低於它的人不會示好），其他條件不變：
啟用組 3 對、對照組 0 對。

| 種子 | P（外貌／親和）→ Q | 第 14 天：P→Q attraction | Q→P affection | Q→P attraction | 事件 id |
|---|---|---|---|---|---|
| 7 | 阿濤（0.30／0.80）→ 阿寧 | 0.268 | 0.377 | 0.188 | P 的吸引首次 ≥ 0.22：事件 1639（第 10 天）；Q→P affection 從第 0 天就 ≥ 0.30（起始關係，事件 135）；Q→P attraction 最後一次變動：事件 2110 |
| 7 | 阿濤 → 小雲 | 0.248 | 0.334 | 0.190 | 1806（第 11 天）；Q→P affection 首次 ≥ 0.30：事件 1526（第 10 天）；2113 |
| 7 | 小雲（0.55／0.30）→ 阿豪 | 0.232 | 0.345 | 0.192 | 這一對的 P 不是「親和高、外貌低」，不算好人卡，只是同一種結構 |

要看清楚：這三對在 14 天裡**沒有任何示好或告白事件**（flirt／confession／date 都是空的），所以只是「狀態」，還不是故事；
而且阿濤→阿寧那一對，affection 在第 0 天就已經是起始關係給的。親和帶來的 affection 差別有，但小（阿濤、阿俊被其他人的平均 affection：啟用 0.18、對照 0.15；三個種子各兩人，n = 6），
但「好人卡單戀」在 14 天、10 人的世界裡**沒有穩定出現**。要讓它出現，需要改 `drawn_level` 的結構（例如讓外貌的權重更大、或對低外貌者的底更低），那是改感情公式，不在這一輪範圍。

### 5.4 其他規則的可偵測效果（啟用 vs 對照，三種子合計）

- **話量**：ρ(話量, 主動開口 talk 數) 0.91（對照 0.24）。小美 66（對照 95）、阿豪 162（97）。
- **被議論**：ρ(外貌, 被傳話次數) 0.44（對照 −0.08），tell 總數 184 vs 185（動作比例保住）。
- **嫉妒**：被同性壓過至少 0.20 的人對那位的平均 resentment 0.131（其他同性對 0.121）；對照 0.092 對 0.099。差距 +0.010 vs −0.007，**很小**。
- **動作比例**（run 2）：talk 2876 vs 2661（+8%）、tell 184 vs 185、confront 32 vs 27、flirt 19 vs 18、confession 2 vs 2、goal_change 56 vs 81（−31%）、job_search 14 vs 16。
  talk 仍多 8%（話量的雙邊加成經指數權重略偏向開口），goal_change 少了三成：這是已知的副作用，原因沒有追到。

### 5.5 沒啟用的既有配方、LLM 世界

- `python -m tests.refactor_baseline --check out/refactor_baseline.json`：**identical**（town_v1、jianghu_v1、town_spatial_v1，含 `character_genomes` 與 `world_vars`；基準在開工時 identical，結束時再檢查一次）。
- 三十個既有 genome（town_v1、jianghu_v1、jianghu_story_v1 的 30 列）的 `genome_id`，用 HEAD 版的合約重算與現行相同；補了數字的記憶體 genome 的 id 也相同（`tests/test_impression.py` 釘死 4 個）。
- `python -m channel.studio --mind out/soul/soul503 --out out/tmp_d --no-serve`：通過（重播 1102 筆事件、35 個回答，沒有 `MindReplayError`，寫出 `out/tmp_d/soul-503/studio.json`）。
- 成年人規則、真人規則：`tests/test_romance.py`、`tests/test_persona.py` 全過；`test_impression` 另有一個用 17 歲的角色驗證 `drawn_to`／`drawn_level` 仍是 0。

## 6. 沒達到或沒做到的

1. **條件 4（好人卡）照原條件 0 對。** 放寬後 3 對（其中 2 對是好人卡的結構），但 14 天內沒有示好／告白事件，只是狀態。見 5.3。
2. **誤讀的初期偏差很淺**（平均 −0.087，最深 −0.40）；翻轉比誤讀大。
3. **嫉妒效果很小**（+0.010）。常數沒有調。
4. **「誰被看見」沒做**（`world/attention.py` 的 `noticers` 不在範圍）。外貌只透過被找說話與被議論影響注意。
5. **回話長短的台詞端沒接**：只給了 `reply_length` 與 `impression.talk.<pid>`；`narrative/speech.py` 還沒讀它，台詞池也還沒有「冷淡簡短」一組。
6. **副作用**：talk 多 8%、goal_change 少三成，原因沒有追。
7. **樣本小**：3 種子 × 10 人 × 14 天；區間很寬（ρ_A 的下緣 0.19，ρ_T 的區間跨 0）。沒有做更大的樣本。
8. 推導公式推不出「樣貌普通但性格好」這種人（見 2.2 的阿濤），只能由作者補數字。
9. 角色工坊的原型（高冷美人、親切的鄰家、其貌不揚的老好人、萬人迷、毒舌、悶葫蘆）沒有做，那是 C16／C17。
10. `tests/test_domains.py::PacksAreNotASecondCore` 在我結束時有一個失敗：`factions.py` 706 行 > 600（A2 正在改的檔案，不是這一輪的）。
