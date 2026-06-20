/**
 * Cloudflare Pages Function — /api/chat
 * 
 * Strategy A chatbot with SearXNG web search integration.
 * 1. User asks question
 * 2. Search SearXNG for relevant info
 * 3. Feed search results + live screening data → LLM
 * 4. Return answer in conversational Chinese
 * 
 * Env vars (set in Cloudflare Pages dashboard):
 *   CHAT_API_KEY          — API key for LLM
 *   CHAT_API_ENDPOINT     — LLM endpoint
 *   CHAT_MODEL            — Model name (default: deepseek-v4-flash)
 *   SEARXNG_URL           — SearXNG search endpoint
 *   CF_ACCESS_CLIENT_ID   — Cloudflare Zero Trust service token ID
 *   CF_ACCESS_CLIENT_SECRET — Cloudflare Zero Trust service token secret
 */

function fmtAmount(v) {
  if (!v && v !== 0) return "—";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + " 億";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + " 萬";
  return Number(v).toLocaleString("zh-TW");
}

async function searchSearXNG(query, env) {
  const baseUrl = env.SEARXNG_URL;
  if (!baseUrl) return null;

  const cfId = env.CF_ACCESS_CLIENT_ID;
  const cfSecret = env.CF_ACCESS_CLIENT_SECRET;
  if (!cfId || !cfSecret) return null;

  try {
    const url = baseUrl + encodeURIComponent(query);
    const res = await fetch(url, {
      headers: {
        "CF-Access-Client-Id": cfId,
        "CF-Access-Client-Secret": cfSecret,
      },
    });

    if (!res.ok) return null;

    const data = await res.json();
    const results = data.results || [];

    return results.slice(0, 5).map((r, i) =>
      `[${i + 1}] ${r.title}\n${r.content || r.snippet || ""}\n來源: ${r.url}`
    ).join("\n\n");
  } catch {
    return null;
  }
}

function buildSystemPrompt(stocks, searchContext) {
  const now = new Date().toLocaleDateString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "long",
  });

  let stockTable = "";
  if (stocks && stocks.length > 0) {
    stockTable = stocks
      .map((s) => {
        const name = s.name_zh || s.code || "—";
        const amt = fmtAmount(s.net_amount_10d);
        const z = (s.regression_z ?? 0).toFixed(2);
        const g = (s.g_score ?? 0).toFixed(0);
        const l = (s.l_score ?? 0).toFixed(0);
        const price = s.cur_price ?? "—";
        const chg = s.change_pct != null ? `${s.change_pct > 0 ? "+" : ""}${s.change_pct.toFixed(1)}%` : "—";
        return `- ${s.code} ${name}：投信10日買超 **${amt}**｜Z=${z}｜成長G=${g}分 安全L=${l}分｜股價 ${price}（${chg}）`;
      })
      .join("\n");
  } else {
    stockTable = "（今日暫無上榜股票）";
  }

  let searchSection = "";
  if (searchContext) {
    searchSection = `\n## 即時搜尋結果\n以下是針對用戶問題的即時搜尋結果，請參考這些資訊回答：\n\n${searchContext}\n`;
  }

  return `你是台股投資策略助手，暱稱「雷達小幫手」，專門幫助用戶理解「法人初建倉」選股策略，並能查詢個股新聞與基本資訊。

## 你的角色
用戶多半是對股票有興趣但非專業投資人（可能是家人長輩），請用**繁體中文、口語化、像在聊天**的方式解釋。避免術語轟炸，每次只解釋對方問的部分就好。

## 策略說明：法人初建倉（策略A）
這是一套機械化掃描全市場（上市+上櫃約1937檔）的選股流程：

1. **全市場掃描** — 每天計算所有上市櫃股票「投信近10日淨買超金額」（買進張數 × 成交股價，不是只看張數）
2. **金額排序** — 全市場按買超金額從大到小排，沒有硬性數量限制，只要金額為正都納入候選
3. **基本面濾網** — FinMind 評分系統對候選股票打分數：
   - 成長力 G ≥ 80 分（營收、獲利在成長）
   - 安全力 L ≥ 80 分（財務體質健康、不太會倒）
   - 兩項都要 ≥ 80 才算通過
4. **技術面輔助** — Z-score ≤ 0（股價在回歸線下方，代表相對便宜，不是追高）

**通過所有濾網的股票就是「上榜」，沒有數量上限**。

**重要觀念：** 排行用「金額」而非「張數」，因為高價權值股（像台積電一張60萬）張數雖少但金額大，更能捕捉法人真正佈局的力道。

## 今日榜單（${now}）
${stockTable}
${searchSection}
## 回答守則
- 用戶問某檔股票的新聞、法說會、財報 → 參考上方「即時搜尋結果」回答，並摘要重點
- 如果搜尋結果為空或不相關 → 誠實說「目前沒有找到相關資訊」，不要瞎掰
- 用戶問某檔股票為什麼在/不在榜上 → 根據榜單資料解釋
- 用戶問策略邏輯 → 用白話解釋
- **不要主動給買賣建議**（不要說「可以買」、「建議賣」）
- **不要說**「我不是財務顧問」、「投資有風險」這類生硬的免責聲明
- 保持友善、耐心，像在跟家人聊天`;
}

export async function onRequestPost(context) {
  try {
    const { request, env } = context;

    // Parse request body
    let body;
    try {
      body = await request.json();
    } catch {
      return new Response(JSON.stringify({ reply: "訊息格式錯誤，請再試一次。" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const message = (body.message || "").trim();
    if (!message) {
      return new Response(JSON.stringify({ reply: "請輸入你想問的問題 😊" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (message.length > 2000) {
      return new Response(JSON.stringify({ reply: "訊息太長了，請縮短到2000字以內 🙏" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // ── Fetch live screening data ──
    let activeStocks = [];
    try {
      // Use relative URL for same-origin fetch within CF Pages
      const dataRes = await fetch(new URL("/data/screener_history.json", request.url));
      if (dataRes.ok) {
        const json = await dataRes.json();
        activeStocks = json.active || [];
      }
    } catch (e) {
      // Degraded mode — no screening data available
      console.warn("Could not fetch screening data:", e.message);
    }

    // ── Search SearXNG ──
    let searchContext = null;
    try {
      searchContext = await searchSearXNG(message, env);
    } catch (e) {
      console.warn("Search failed:", e.message);
    }

    // ── Build system prompt ──
    const systemPrompt = buildSystemPrompt(activeStocks, searchContext);

    // ── Build messages array ──
    const messages = [
      { role: "system", content: systemPrompt },
    ];

    // Include conversation history
    const history = body.history;
    if (history && Array.isArray(history)) {
      for (const h of history.slice(-10)) {
        if (h && h.role && h.content) {
          messages.push({ role: h.role, content: h.content });
        }
      }
    }

    // Current message
    messages.push({ role: "user", content: message });

    // ── Get API config ──
    const apiKey = env.CHAT_API_KEY || "";
    if (!apiKey) {
      return new Response(JSON.stringify({
        reply: "⚠️ 系統尚未設定 API 金鑰。請管理員在 Cloudflare Pages Dashboard → Settings → Environment variables 中設定 CHAT_API_KEY。",
      }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }

    const apiEndpoint = env.CHAT_API_ENDPOINT || "https://opencode.ai/zen/go/v1/chat/completions";
    const model = env.CHAT_MODEL || "deepseek-v4-flash";

    // ── Call LLM ──
    const r = await fetch(apiEndpoint, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
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
      const errText = await r.text().catch(() => "");
      console.error(`LLM API error ${r.status}: ${errText.slice(0, 200)}`);
      return new Response(JSON.stringify({
        reply: "抱歉，AI 服務暫時出了點問題，請稍後再試 🙇",
      }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await r.json();
    const reply = data.choices?.[0]?.message?.content?.trim();

    if (!reply) {
      return new Response(JSON.stringify({ reply: "抱歉，我沒有產生回應，請再問一次。" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ reply }), {
      headers: { "Content-Type": "application/json" },
    });

  } catch (err) {
    console.error("Chat function error:", err && err.message ? err.message : String(err));
    return new Response(JSON.stringify({
      reply: "網路連線暫時不穩，請稍後再試 🙇",
    }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
