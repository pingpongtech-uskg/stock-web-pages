/**
 * Cloudflare Pages Function — /api/chat
 * Strategy A chatbot with SearXNG web search + conversation memory.
 * Deployed via wrangler pages deploy (Direct Upload).
 */

export async function onRequest(context) {
  if (context.request.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  try {
    var request = context.request;
    var env = context.env;

    var body = await request.json();
    var message = (body.message || "").trim();
    if (!message) {
      return new Response(JSON.stringify({ reply: "请输入问题 😊" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (message.length > 2000) {
      return new Response(JSON.stringify({ reply: "訊息太長 🙏" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Fetch live screening data
    var activeStocks = [];
    try {
      var dataRes = await fetch(new URL("/data/screener_history.json", request.url));
      if (dataRes.ok) {
        var json = await dataRes.json();
        activeStocks = json.active || [];
      }
    } catch (e) {}

    // Search SearXNG
    var searchContext = null;
    try {
      var baseUrl = env.SEARXNG_URL;
      if (baseUrl) {
        var cfId = env.CF_ACCESS_CLIENT_ID;
        var cfSecret = env.CF_ACCESS_CLIENT_SECRET;
        if (cfId && cfSecret) {
          var searchRes = await fetch(baseUrl + encodeURIComponent(message), {
            headers: { "CF-Access-Client-Id": cfId, "CF-Access-Client-Secret": cfSecret },
          });
          if (searchRes.ok) {
            var searchData = await searchRes.json();
            var results = searchData.results || [];
            if (results.length > 0) {
              searchContext = results.slice(0, 5).map(function (r, i) {
                return "[" + (i + 1) + "] " + r.title + "\n" + (r.content || r.snippet || "") + "\n來源: " + r.url;
              }).join("\n\n");
            }
          }
        }
      }
    } catch (e) {}

    // Build system prompt
    var now = new Date().toLocaleDateString("zh-TW", {
      year: "numeric", month: "2-digit", day: "2-digit", weekday: "long",
    });
    var stockTable = "";
    if (activeStocks.length > 0) {
      stockTable = activeStocks.map(function (s) {
        var name = s.name_zh || s.code || "—";
        var amt = fmtAmount(s.net_amount_10d);
        var z = (s.regression_z != null ? s.regression_z : 0).toFixed(2);
        var g = (s.g_score != null ? s.g_score : 0).toFixed(0);
        var l = (s.l_score != null ? s.l_score : 0).toFixed(0);
        var price = s.cur_price != null ? s.cur_price : "—";
        var chg = s.change_pct != null ? (s.change_pct > 0 ? "+" : "") + s.change_pct.toFixed(1) + "%" : "—";
        return "- " + s.code + " " + name + "：投信10日買超 **" + amt + "**｜Z=" + z + "｜成長G=" + g + "分 安全L=" + l + "分｜股價 " + price + "（" + chg + "）";
      }).join("\n");
    } else {
      stockTable = "（今日暫無上榜股票）";
    }
    var searchSection = searchContext ? "\n## 即時搜尋結果\n" + searchContext + "\n" : "";

    var systemPrompt = "你是台股投資策略助手「雷達小幫手」，專門幫助用戶理解「法人初建倉」選股策略。\n" +
      "\n## 策略完整邏輯（策略D：價值篩選）\n" +
      "\n### 篩選管線（依序執行，任一關未過即淘汰）\n" +
      "1. 全市場掃描：TWSE（上市）+ TPEx（上櫃）全部約1,900檔，每天計算投信近10日淨買超金額\n" +
      "   公式：淨買超金額 = Σ(每日淨買超股數 × 當日收盤價)，不是單純算張數\n" +
      "2. 金額排名：全市場按買超金額從大排到小，取前100檔進入下一關\n" +
      "   注意：是「金額」排名（股數×股價），不是張數排名。這確保高價電子股不會被低價金融股淹沒\n" +
      "3. 技術面 Z-score ≤ 0：計算樂活五線譜 Z =（目前股價 − 3.5年趨勢線）/ 標準差\n" +
      "   這是「主力篩選器」。Z ≤ 0 表示股價在趨勢線下方（相對便宜），Z > 0 直接淘汰\n" +
      "4. 基本面濾網：對 Z 通過的股票跑 FinMind 評分，G ≥ 80（成長）且 L ≥ 80（安全），缺一不可\n" +
      "\n" +
      "### 排行規則（絕對不可違反）\n" +
      "- 金額排名，絕不用張數排名\n" +
      "- 不遞補：當天符合全部條件的股票有幾檔就顯示幾檔，不硬湊固定數量\n" +
      "- 全市場覆蓋：TWSE上市 + TPEx上櫃全部納入，不截斷\n" +
      "- 週末/假日台股未開盤，無新數據，榜單為空是正常的\n" +
      "- 財報季節 FinMind 評分可能缺資料，該欄位顯示「—」而非0分\n" +
      "\n" +
      "### 為什麼榜上多為中小型股？（策略設計意圖）\n" +
      "策略D的核心篩選器是「Z ≤ 0」。大型權值股（如2330台積電、2454聯發科）長期走多頭，\n" +
      "股價幾乎永遠在3.5年趨勢線上方（Z > 0），因此被 Z ≤ 0 這關自動排除。\n" +
      "這不是 bug，是策略刻意設計：專門找「投信默默吃貨、但股價還在低檔尚未反應」的中小型價值股。\n" +
      "策略D與傳統「強者恆強」的追漲策略相反，它反著做：找投信在買但市場還沒發現的標的。\n" +
      "\n" +
      "### 回答用戶「為什麼某檔股票沒上榜」的邏輯\n" +
      "按以下順序排查，不要自己腦補：\n" +
      "1. 今天是週末/假日嗎？→ 台股未開盤，沒有新數據，榜單為空很正常\n" +
      "2. 該股票投信10日淨買超金額夠大嗎？→ 金額排名必須進前100\n" +
      "3. Z-score 是否 ≤ 0？→ Z > 0 就直接淘汰。大型權值股幾乎必卡這關\n" +
      "4. FinMind G/L 是否 ≥ 80？→ 基本面不過也會淘汰\n" +
      "優先懷疑 Z > 0（對權值股）或金額排名不夠（對冷門股），不要亂猜其他原因\n" +
      "\n" +
      "## 今日榜單（" + now + "）\n" + stockTable + "\n" + searchSection + "\n" +
      "## 回答守則\n" +
      "- 用繁體中文、口語化、像在跟家人聊天\n" +
      "- 問新聞/法說會→參考搜尋結果回答，無相關資訊就誠實說沒有\n" +
      "- 問為何上榜→根據榜單資料解釋（每檔有：代號、名稱、買超金額、Z值、G/L分數）\n" +
      "- 問為何某檔沒上榜→按照上方「排查邏輯」依序推理，只說能確定的原因，不瞎猜\n" +
      "- 榜單為空時→直接說「今天台股未開盤，沒有新數據」，不要猜測任何股票為何不在榜上\n" +
      "- 不主動給買賣建議";

    // Build messages array
    var messages = [{ role: "system", content: systemPrompt }];

    // Include history
    var history = body.history;
    if (history && Array.isArray(history)) {
      for (var i = 0; i < history.length && i < 10; i++) {
        var h = history[i];
        if (h && h.role && h.content) {
          messages.push({ role: h.role, content: h.content });
        }
      }
    }
    messages.push({ role: "user", content: message });

    // Get API config
    var apiKey = env.CHAT_API_KEY || "";
    if (!apiKey) {
      return new Response(JSON.stringify({ reply: "⚠️ 尚未設定 API 金鑰。請在 CF Pages Dashboard 設定 CHAT_API_KEY。" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }

    var apiEndpoint = env.CHAT_API_ENDPOINT || "https://opencode.ai/zen/go/v1/chat/completions";
    var model = env.CHAT_MODEL || "deepseek-v4-flash";

    // Call LLM
    var r = await fetch(apiEndpoint, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: model,
        messages: messages,
        max_tokens: 1200,
        temperature: 0.7,
      }),
    });

    if (!r.ok) {
      return new Response(JSON.stringify({ reply: "抱歉，AI 服務暫時出了點問題 🙇" }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    var data = await r.json();
    var reply = "";
    if (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) {
      reply = data.choices[0].message.content.trim();
    }
    if (!reply) {
      reply = "抱歉，沒有產生回應。";
    }

    return new Response(JSON.stringify({ reply: reply }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return new Response(JSON.stringify({ reply: "網路連線不穩，請稍後再試 🙇" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

function fmtAmount(v) {
  if (!v && v !== 0) return "—";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + " 億";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + " 萬";
  return Number(v).toLocaleString("zh-TW");
}
