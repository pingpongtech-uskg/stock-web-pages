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

    // Search SearXNG with 8s timeout
    var searchContext = null;
    var searchController = new AbortController();
    var searchTimeout = setTimeout(function () { searchController.abort(); }, 8000);
    try {
      var baseUrl = env.SEARXNG_URL;
      if (baseUrl) {
        var cfId = env.CF_ACCESS_CLIENT_ID;
        var cfSecret = env.CF_ACCESS_CLIENT_SECRET;
        if (cfId && cfSecret) {
          var searchRes = await fetch(baseUrl + encodeURIComponent(message), {
            headers: { "CF-Access-Client-Id": cfId, "CF-Access-Client-Secret": cfSecret },
            signal: searchController.signal,
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
    clearTimeout(searchTimeout);

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
        var cs = s.cheap_score != null ? s.cheap_score : "—";
        var ds = s.dividend_score != null ? s.dividend_score : "—";
        var cd = Array.isArray(s.cheap_detail) ? s.cheap_detail.slice(0,3).join("; ") : "—";
        var dd = Array.isArray(s.dividend_detail) ? s.dividend_detail.slice(0,3).join("; ") : "—";
        var v = (s.valuation != null && typeof s.valuation === "object") ? s.valuation : null;
        var pegy = (v && v.peg_y != null) ? v.peg_y.toFixed(2) : "—";
        var peg = (v && v.peg != null) ? v.peg.toFixed(2) : "—";
        var dy = (v && v.div_yield_3y_pct != null) ? v.div_yield_3y_pct.toFixed(1) + "%" : "—";
        var fill = (v && v.avg_fill_days != null) ? Math.round(v.avg_fill_days) + "天" : "—";
        var price = s.cur_price != null ? s.cur_price : "—";
        var chg = s.change_pct != null ? (s.change_pct > 0 ? "+" : "") + s.change_pct.toFixed(1) + "%" : "—";
        return "- " + s.code + " " + name + "：投信10日買超 **" + amt + "**｜Z=" + z + "｜G=" + g + " L=" + l + "｜便宜" + cs + "分(" + cd + ")｜殖利率" + ds + "分(" + dd + ")｜PEGY=" + pegy + "(PE調整後)｜PEG=" + peg + "｜3年均殖利率" + dy + "｜平均填息" + fill + "｜" + price + "（" + chg + "）";
      }).join("\n");
    } else {
      stockTable = "（今日暫無上榜股票）";
    }
    var searchSection = searchContext ? "\n## 即時搜尋結果\n" + searchContext + "\n" : "\n## 即時搜尋結果\n（本次搜尋未返回結果，請根據你所知的資訊回答）\n";

    var systemPrompt = "你是台股研究助理「雷達小幫手」，專門幫使用者查找股票的相關資訊。\n" +
      "\n## 主要功能\n" +
      "你可以幫助使用者查詢台股個股的相關資訊，包括：\n" +
      "- 股價與技術分析（含樂活五線譜 Z-score）\n" +
      "- 基本面（營收、EPS、本益比、成長性、安全性評分）\n" +
      "- 法人籌碼（投信、外資買賣超）\n" +
      "- 新聞與法說會資訊\n" +
      "- 產業趨勢與同業比較\n" +
      "\n" +
      "## 搜尋結果使用方式（重要）\n" +
      "下方「即時搜尋結果」段落包含系統已根據用戶問題自動搜尋的結果。\n" +
      "**你必須優先使用搜尋結果回答**，因為它們包含最新資訊。\n" +
      "- 搜尋結果與問題相關 → 直接引用結果內容回答，並標註來源\n" +
      "- 搜尋結果不夠完整 → 誠實說明並補充你知道的資訊\n" +
      "- 完全沒有相關結果 → 誠實說「目前搜尋不到相關資訊」，不要編造\n" +
      "\n" +
      "## 策略說明（僅在被問到時回答）\n" +
      "如果用戶直接問策略邏輯（例如「什麼是策略A」「Z-score怎麼算」），你可以簡潔解釋：\n" +
      "- 策略A：法人初建倉，找投信默默買超但股價還在低檔的股票\n" +
      "- 篩選條件：投信10日買超金額前100 → Z ≤ 0（股價在趨勢線下方）→ G ≥ 80 且 L ≥ 80\n" +
      "- 不主動解釋策略，除非用戶明確問\n" +
      "\n" +
      "## 今日榜單（" + now + "）\n" + stockTable + "\n" + searchSection + "\n" +
      "## 回答守則\n" +
      "- 用繁體中文、口語化、像在跟家人聊天\n" +
      "- 問某檔股票 → 優先用搜尋結果回答（新聞、財報、法說會、產業趨勢）\n" +
      "- 問今天榜單 → 用榜單數據回答（買超金額、Z值、G/L分數、便宜/殖利率分數、PEGY/殖利率/填息補充資料）\n" +
      "\n## PEGY 指標說明（榜單中的補充估值資料）\n" +
      "PEGY = 本益比 ÷ (EPS成長率% + 殖利率%)，是 Lynch 殖利率調整版 PEG，適合台股高配息文化。\n" +
      "判讀：低於 0.75 便宜（祖魯法則門檻）、0.75~1 合理偏高、大於 1 偏貴。PEG（未調整版）在 EPS 負成長時會顯示 — 。此為補充參考資料，非篩選條件，回答時註明即可。\n" +
      "- 問策略邏輯 → 簡潔解釋，不長篇大論\n" +
      "- 沒有資訊就誠實說沒有，不要編造\n" +
      "- 不主動給買賣建議\n";

    // Build messages array
    var messages = [{ role: "system", content: systemPrompt }];

    // Include history
    var history = body.history;
    if (history && Array.isArray(history)) {
      for (var i = Math.max(0, history.length - 10); i < history.length; i++) {
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

    // Call LLM with 25s timeout
    var controller = new AbortController();
    var timeoutId = setTimeout(function () { controller.abort(); }, 25000);
    var r = await fetch(apiEndpoint, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: model,
        messages: messages,
        max_tokens: 3000,
        temperature: 0.7,
      }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

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
    if (err.name === "AbortError") {
      return new Response(JSON.stringify({ reply: "查詢時間過長，請試著縮短問題或簡化關鍵字 🙇" }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
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
