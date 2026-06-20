/**
 * Cloudflare Pages Function — /api/chat  
 * Strategy A chatbot with SearXNG web search + conversation memory.
 */

function fmtAmount(v) {
  if (!v && v !== 0) return "—";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + " 億";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + " 萬";
  return Number(v).toLocaleString("zh-TW");
}

async function searchSearXNG(query, env) {
  var baseUrl = env.SEARXNG_URL;
  if (!baseUrl) return null;
  var cfId = env.CF_ACCESS_CLIENT_ID;
  var cfSecret = env.CF_ACCESS_CLIENT_SECRET;
  if (!cfId || !cfSecret) return null;
  try {
    var res = await fetch(baseUrl + encodeURIComponent(query), {
      headers: { "CF-Access-Client-Id": cfId, "CF-Access-Client-Secret": cfSecret },
    });
    if (!res.ok) return null;
    var data = await res.json();
    return (data.results || []).slice(0, 5).map(function(r, i) {
      return "[" + (i + 1) + "] " + r.title + "\n" + (r.content || r.snippet || "") + "\n來源: " + r.url;
    }).join("\n\n");
  } catch (e) { return null; }
}

function buildSystemPrompt(stocks, searchContext) {
  var now = new Date().toLocaleDateString("zh-TW", {
    year: "numeric", month: "2-digit", day: "2-digit", weekday: "long",
  });
  var stockTable = "";
  if (stocks && stocks.length > 0) {
    stockTable = stocks.map(function(s) {
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
  return "你是台股投資策略助手「雷達小幫手」，專門幫助用戶理解「法人初建倉」選股策略。\n\n## 策略說明\n1. 全市場掃描：每天計算投信近10日淨買超金額（買進張數×成交股價）\n2. 金額排序：全市場按買超金額從大排到小\n3. 基本面濾網：FinMind評分 G≥80 & L≥80\n4. 技術面：Z-score≤0\n\n**排行用「金額」而非「張數」**\n\n## 今日榜單（" + now + "）\n" + stockTable + "\n" + searchSection + "\n## 回答守則\n- 用繁體中文、口語化、像在跟家人聊天\n- 問新聞/法說會→參考搜尋結果回答，無相關資訊就誠實說沒有\n- 問為何上榜→根據榜單資料解釋\n- 不主動給買賣建議";
}

async function handleChat(request, env) {
  try {
    var body;
    try { body = await request.json(); } catch (e) {
      return new Response(JSON.stringify({ reply: "訊息格式錯誤" }), { status: 400, headers: { "Content-Type": "application/json" } });
    }
    var message = (body.message || "").trim();
    if (!message) return new Response(JSON.stringify({ reply: "請輸入問題 😊" }), { status: 400, headers: { "Content-Type": "application/json" } });
    if (message.length > 2000) return new Response(JSON.stringify({ reply: "訊息太長 🙏" }), { status: 400, headers: { "Content-Type": "application/json" } });

    // Fetch screening data
    var activeStocks = [];
    try {
      var dataRes = await fetch(new URL("/data/screener_history.json", request.url));
      if (dataRes.ok) { var json = await dataRes.json(); activeStocks = json.active || []; }
    } catch (e) {}

    // Search
    var searchContext = null;
    try { searchContext = await searchSearXNG(message, env); } catch (e) {}

    // Build messages
    var messages = [{ role: "system", content: buildSystemPrompt(activeStocks, searchContext) }];
    var history = body.history;
    if (history && Array.isArray(history)) {
      for (var i = 0; i < history.length && i < 10; i++) {
        var h = history[i];
        if (h && h.role && h.content) messages.push({ role: h.role, content: h.content });
      }
    }
    messages.push({ role: "user", content: message });

    // API config
    var apiKey = env.CHAT_API_KEY || "";
    if (!apiKey) {
      return new Response(JSON.stringify({ reply: "⚠️ 尚未設定 API 金鑰。請在 CF Pages Dashboard → Settings → Environment variables 設定 CHAT_API_KEY。" }), { status: 500, headers: { "Content-Type": "application/json" } });
    }
    var apiEndpoint = env.CHAT_API_ENDPOINT || "https://opencode.ai/zen/go/v1/chat/completions";
    var model = env.CHAT_MODEL || "deepseek-v4-flash";

    // Call LLM
    var r = await fetch(apiEndpoint, {
      method: "POST",
      headers: { "Authorization": "Bearer " + apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({ model: model, messages: messages, max_tokens: 1200, temperature: 0.7 }),
    });
    if (!r.ok) {
      return new Response(JSON.stringify({ reply: "抱歉，AI 服務暫時出了點問題 🙇" }), { status: 502, headers: { "Content-Type": "application/json" } });
    }
    var data = await r.json();
    var reply = (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content || "").trim() || "抱歉，沒有產生回應。";
    return new Response(JSON.stringify({ reply: reply }), { headers: { "Content-Type": "application/json" } });
  } catch (err) {
    return new Response(JSON.stringify({ reply: "網路連線不穩，請稍後再試 🙇" }), { status: 502, headers: { "Content-Type": "application/json" } });
  }
}

// Cloudflare Pages Functions — onRequest handler
export async function onRequest(context) {
  if (context.request.method === "POST") {
    return handleChat(context.request, context.env);
  }
  return new Response("Method not allowed", { status: 405 });
}
