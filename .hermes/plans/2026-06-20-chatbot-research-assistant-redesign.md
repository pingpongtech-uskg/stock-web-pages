# Chatbot 改版計畫：從「策略解釋器」到「股票研究助理」

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 將 chatbot 從策略解釋器改版為股票研究助理，重新設計 system prompt 以優先使用 SearXNG 搜尋結果回答股票資訊查詢，並讓 UI 訊息氣泡顏色對比更明顯。

**Architecture:** 修改 2 個檔案：`functions/api/chat.js`（system prompt 重寫 + 搜尋 fallback）和 `src/pages/chat.astro`（歡迎訊息、metadata、CSS 氣泡顏色）。不需要新增檔案或修改 Layout.astro 的 CSS 變數。

**Tech Stack:** Cloudflare Pages Functions (vanilla JS), Astro, CSS custom properties

---

## 涉及檔案

| 檔案 | 路徑 | 行數 | 修改範圍 |
|------|------|------|----------|
| chat.js | `stock-web-pages/functions/api/chat.js` | 208 | 行 88, 90-132 |
| chat.astro | `stock-web-pages/src/pages/chat.astro` | 419 | 行 6-7, 24, 32-44, 53, 65, 269-274, 279-284, 411-418 |

## 現有 CSS 變數參考（Layout.astro，不修改）

| 變數 | Light | Dark |
|------|-------|------|
| `--color-accent` | `#3B82F6` (藍) | `#60A5FA` (亮藍) |
| `--color-surface` | `#faf9f5` (米色) | `#30302e` (深灰) |
| `--color-bg` | `#f5f4ed` (米底) | `#141413` (近黑) |
| `--color-text-inverse` | `#faf9f5` (米色) | `#141413` (近黑) |
| `--color-border-strong` | `#e8e6dc` (暖灰) | `#4d4c48` (中灰) |

**問題：** Light mode 下 AI 氣泡用 `--color-surface` (#faf9f5) 幾乎等同背景 `--color-bg` (#f5f4ed)，看不出差異。User 氣泡的 box-shadow 仍是舊的橘色 `rgba(201,100,66,0.25)`，不匹配現有藍色 accent。

---

## Task 1: 重寫 system prompt（chat.js 行 90-132）

**Objective:** 將 system prompt 從策略解釋器改為股票研究助理，強調使用 SearXNG 搜尋結果

**Files:**
- Modify: `stock-web-pages/functions/api/chat.js:90-132`

### 現有內容（行 90-132）

策略邏輯佔了 40 行（Z-score、篩選管線、排行規則、排查邏輯），搜尋結果只在行 127 一句帶過。

### 替換為

```javascript
    var systemPrompt = "你是台股研究助理「雷達小幫手」，專門幫使用者查找股票的相關資訊。\n" +
      "\n## 你的核心任務\n" +
      "幫使用者查找股票資訊，包括：\n" +
      "- 最新新聞與市場動態\n" +
      "- 財報數據與營收表現\n" +
      "- 法說會（投資人說明會）資訊\n" +
      "- 基本面分析（獲利能力、財務結構、股利政策）\n" +
      "- 產業趨勢與競爭格局\n" +
      "\n## 搜尋結果使用方式（重要）\n" +
      "系統已根據用戶的問題自動搜尋，結果在下方「即時搜尋結果」段落。\n" +
      "**你必須優先使用搜尋結果回答**，因為它們包含最新資訊。\n" +
      "- 搜尋結果與問題相關 → 直接引用結果內容回答，並標註來源\n" +
      "- 搜尋結果不夠完整 → 誠實說明並補充你知道的資訊\n" +
      "- 完全沒有相關結果 → 誠實說「目前搜尋不到相關資訊」，不要編造\n" +
      "\n" +
      "## 今日榜單（" + now + "）\n" + stockTable + "\n" + searchSection + "\n" +
      "## 策略說明（僅在被問到時回答）\n" +
      "如果用戶直接問策略邏輯（例如「什麼是策略A」「Z-score怎麼算」「為什麼用金額排名」），你可以簡潔解釋：\n" +
      "- 策略A：法人初建倉，找投信默默買超但股價還在低檔的股票\n" +
      "- 篩選條件：投信10日買超金額前100 → Z ≤ 0（股價在趨勢線下方）→ G ≥ 80 且 L ≥ 80\n" +
      "- 不主動解釋策略，除非用戶明確問\n" +
      "\n## 回答守則\n" +
      "- 用繁體中文、口語化，像在跟朋友聊天\n" +
      "- 問某檔股票 → 優先用搜尋結果回答（新聞、財報、法說會、產業趨勢）\n" +
      "- 問今天榜單 → 用榜單數據回答（買超金額、Z值、G/L分數、便宜/殖利率分數）\n" +
      "- 問策略邏輯 → 簡潔解釋，不長篇大論\n" +
      "- 沒有資訊就誠實說沒有，不要編造\n" +
      "- 不主動給買賣建議\n";
```

### 設計理由

| 項目 | 舊 | 新 |
|------|-----|-----|
| 身份 | 策略A助手 | 台股研究助理 |
| 策略邏輯 | 40 行詳述 | 3 行摘要，僅在被問到時回答 |
| 搜尋結果 | 行 127 一句帶過 | 獨立段落，6 行明確指示 |
| 核心任務 | 無 | 列出 5 大查找範圍 |
| 回答守則 | 策略導向 | 搜尋優先 |

### 注意

- `now` 變數在行 66 已定義，`stockTable` 在行 69-87 已組好，`searchSection` 在行 88 已組好 — 不需要改動這些
- 組裝結構不變：identity → 搜尋指示 → 今日榜單 + 搜尋結果 → 策略 → 回答守則
- 當 searchSection 為空字串時，「即時搜尋結果」段落不會出現，AI 會依回答守則誠實說沒有

---

## Task 2: 搜尋結果 fallback 訊息（chat.js 行 88）

**Objective:** 當 SearXNG 搜尋無結果時，明確告知 AI 而非讓「即時搜尋結果」段落憑空消失

**Files:**
- Modify: `stock-web-pages/functions/api/chat.js:88`

### 現有

```javascript
    var searchSection = searchContext ? "\n## 即時搜尋結果\n" + searchContext + "\n" : "";
```

### 替換為

```javascript
    var searchSection = searchContext ? "\n## 即時搜尋結果\n" + searchContext + "\n" : "\n## 即時搜尋結果\n（本次搜尋未返回結果，請根據你所知的資訊回答）\n";
```

### 理由

system prompt 明確引用「即時搜尋結果」段落，如果該段落不存在，AI 可能困惑。加 fallback 確保段落永遠存在，AI 知道該如何應對無結果的情況。

---

## Task 3: 更新 chat.astro metadata（行 6-7, 24）

**Objective:** 將頁面標題、描述、badge 從策略導向改為研究助理導向

**Files:**
- Modify: `stock-web-pages/src/pages/chat.astro:6-7, 24`

### 行 6

```
舊: const title = "雷達小幫手 · 策略A聊天室";
新: const title = "雷達小幫手 · 股票研究助理";
```

### 行 7

```
舊: const description = "法人初建倉策略問答 — 投信10日買超TOP100 + Z≤0 + G≥80 & L≥80";
新: const description = "台股研究助理 — 查找新聞、財報、法說會、基本面、產業趨勢";
```

### 行 24

```
舊: <span class="chat-badge">策略A</span>
新: <span class="chat-badge">研究助理</span>
```

---

## Task 4: 更新歡迎訊息（chat.astro 行 32-44）

**Objective:** 歡迎訊息從策略解釋改為股票資訊查找

**Files:**
- Modify: `stock-web-pages/src/pages/chat.astro:32-44`

### 現有（行 32-44）

```html
      <div class="msg msg-bot">
        <div class="msg-bubble">
          <p>👋 你好！我是<b>雷達小幫手</b>，專門解釋「法人初建倉」選股策略。</p>
          <p>你可以問我：</p>
          <ul>
            <li>「今天榜上有哪些股票？」</li>
            <li>「為什麼正新上榜？」</li>
            <li>「Z-score 是什麼意思？」</li>
            <li>「為什麼用金額排名不用張數？」</li>
          </ul>
          <p>儘管問，我用白話解釋給你聽 😊</p>
        </div>
      </div>
```

### 替換為

```html
      <div class="msg msg-bot">
        <div class="msg-bubble">
          <p>👋 你好！我是<b>雷達小幫手</b>，你的台股研究助理。</p>
          <p>我可以幫你查找：</p>
          <ul>
            <li>「2330台積電最近有什麼新聞？」</li>
            <li>「2454聯發科最新財報如何？」</li>
            <li>「今天投信買超哪些股票？」</li>
            <li>「某檔股票的基本面和產業趨勢」</li>
          </ul>
          <p>問我就對了，我幫你找資料 😊</p>
        </div>
      </div>
```

### 理由

- 4 個範例問題中，3 個改為股票資訊查找（新聞、財報、基本面/產業），1 個保留榜單查詢
- 不再提及 Z-score、金額排名等策略術語
- 結語從「白話解釋」改為「幫你找資料」，符合研究助理定位

---

## Task 5: 更新 placeholder 和 hint（chat.astro 行 53, 65）

**Objective:** 輸入框提示和底部 hint 改為研究助理語氣

**Files:**
- Modify: `stock-web-pages/src/pages/chat.astro:53, 65`

### 行 53

```
舊: placeholder="輸入你的問題…"
新: placeholder="輸入股票代號或問題…"
```

### 行 65

```
舊: <p class="chat-hint">以榜單資料為準，僅解釋策略邏輯，不提供買賣建議</p>
新: <p class="chat-hint">AI 搜尋結果僅供參考，不構成投資建議</p>
```

---

## Task 6: 訊息氣泡顏色改版（chat.astro 行 269-290, 411-418）

**Objective:** 讓使用者與 AI 訊息的背景色對比更明顯

**Files:**
- Modify: `stock-web-pages/src/pages/chat.astro:269-290`（light mode 氣泡）
- Modify: `stock-web-pages/src/pages/chat.astro:411-418`（dark mode 覆寫）

### 6a: 使用者氣泡 — Light mode（行 269-277）

#### 現有

```css
  .msg-user .msg-bubble {
    background: var(--color-accent);
    color: var(--color-text-inverse);
    border-bottom-right-radius: 4px;
    box-shadow: 0 4px 14px rgba(201, 100, 66, 0.25);
  }
  .msg-user .msg-bubble p {
    margin: 0;
  }
```

#### 替換為

```css
  .msg-user .msg-bubble {
    background: var(--color-accent);
    color: #ffffff;
    border-bottom-right-radius: 4px;
    box-shadow: 0 4px 14px rgba(59, 130, 246, 0.3);
  }
  .msg-user .msg-bubble p {
    margin: 0;
  }
```

#### 改動

- `color: var(--color-text-inverse)` (#faf9f5 米色) → `color: #ffffff` (純白)，在藍色背景上對比更強
- `box-shadow` 從舊橘色 `rgba(201, 100, 66, 0.25)` → 藍色 `rgba(59, 130, 246, 0.3)`，匹配 accent #3B82F6

### 6b: AI 氣泡 — Light mode（行 279-290）

#### 現有

```css
  .msg-bot .msg-bubble {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-bottom-left-radius: 4px;
    box-shadow: var(--shadow-md);
  }
  .msg-bot .msg-bubble p {
    margin: 0 0 6px;
  }
  .msg-bot .msg-bubble p:last-child {
    margin-bottom: 0;
  }
```

#### 替換為

```css
  .msg-bot .msg-bubble {
    background: #e8e6dc;
    border: 1px solid #d4d1c2;
    border-bottom-left-radius: 4px;
    box-shadow: var(--shadow-md);
  }
  .msg-bot .msg-bubble p {
    margin: 0 0 6px;
  }
  .msg-bot .msg-bubble p:last-child {
    margin-bottom: 0;
  }
```

#### 改動

- `background: var(--color-surface)` (#faf9f5，幾乎等同背景 #f5f4ed) → `#e8e6dc`（暖灰色，等同 `--color-border-strong`，與背景對比明顯）
- `border: 1px solid var(--color-border)` (#f0eee6，太淡) → `1px solid #d4d1c2`（稍深的暖灰邊框，增加卡片感）

### 6c: Dark mode 覆寫（行 411-418）

#### 現有

```css
  @media (prefers-color-scheme: dark) {
    .chat-input-wrap {
      background: rgba(255,255,255,0.06);
    }
    .msg-user .msg-bubble {
      box-shadow: 0 4px 14px rgba(217, 119, 87, 0.2);
    }
  }
```

#### 替換為

```css
  @media (prefers-color-scheme: dark) {
    .chat-input-wrap {
      background: rgba(255,255,255,0.06);
    }
    .msg-user .msg-bubble {
      box-shadow: 0 4px 14px rgba(96, 165, 250, 0.25);
    }
    .msg-bot .msg-bubble {
      background: #3d3d3a;
      border: 1px solid #4d4c48;
    }
  }
```

#### 改動

- User 氣泡 shadow：舊橘色 `rgba(217, 119, 87, 0.2)` → 暗模式藍色 `rgba(96, 165, 250, 0.25)`，匹配 dark mode accent #60A5FA
- 新增 bot 氣泡 dark mode 覆寫：`#3d3d3a` 背景（比 dark bg #141413 明顯更亮）+ `#4d4c48` 邊框

### 改版前後對比

| | Light mode 背景 | Light mode 對比 | Dark mode 背景 | Dark mode 對比 |
|---|---|---|---|---|
| **頁面底** | #f5f4ed | — | #141413 | — |
| **User 氣泡（舊）** | #3B82F6 藍 + 米色字 + 橘影 | 尚可 | #60A5FA 藍 + 暗字 + 橘影 | 尚可 |
| **User 氣泡（新）** | #3B82F6 藍 + 純白字 + 藍影 | ✅ 更強 | #60A5FA 藍 + 暗字 + 藍影 | ✅ 更強 |
| **Bot 氣泡（舊）** | #faf9f5 ≈ 背景 | ❌ 幾乎看不到 | #30302e | 尚可 |
| **Bot 氣泡（新）** | #e8e6dc 暖灰 + 深邊框 | ✅ 明顯卡片 | #3d3d3a + #4d4c48 邊框 | ✅ 明顯卡片 |

---

## Task 7: 驗證

**Objective:** 確認所有修改正確且可運作

**Steps:**

1. 確認 chat.js 行 88 和 90-132 已替換
2. 確認 chat.astro 行 6-7, 24, 32-44, 53, 65, 269-290, 411-418 已替換
3. 本地 build 測試：
   ```bash
   cd stock-web-pages
   npm run build
   ```
4. 部署後測試場景：
   - 問「2330台積電最近有什麼新聞？」→ AI 應引用搜尋結果回答
   - 問「今天榜上有哪些股票？」→ AI 應引用榜單數據回答
   - 問「什麼是策略A？」→ AI 應簡短解釋（3-4 句），不長篇大論
   - 問一檔不存在的股票 → AI 應誠實說搜尋不到
   - 確認使用者訊息靠右、藍底白字；AI 訊息靠左、灰底卡片

---

## 未納入本次改版（記錄供未來參考）

| 項目 | 說明 | 優先級 |
|------|------|--------|
| 搜尋查詢優化 | 目前用 `message` 原文搜尋，若用戶問「為什麼2330沒上榜」搜尋效果差。可未來從訊息中提取股票代號構建更好的搜尋 query | 中 |
| max_tokens 提升 | 行 171 `max_tokens: 1200`，研究助理需綜合搜尋結果，1200 可能不夠。可提升至 2000 | 低 |
| 搜尋結果數量 | 行 56 `results.slice(0, 5)` 取前 5 筆，若需更豐富可提升至 8 | 低 |
| Session memory | 前端 history 維護 + 後端取最新 10 筆，機制確認無問題，不需修改 | — |
