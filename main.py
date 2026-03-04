import os
import json
import requests
import yfinance as yf
import pandas as pd
import markdown
from datetime import datetime, timedelta, timezone

# ========== 配置部分 ==========

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
TO_EMAIL = os.getenv("TO_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"

# ========== 工具函数 ==========

def get_beijing_now():
    """获取当前北京时间"""
    utc_now = datetime.now(timezone.utc)
    bj_now = utc_now + timedelta(hours=8)
    return bj_now

def load_tickers():
    """加载 tickers.json 中的公司列表"""
    if not os.path.exists("tickers.json"):
        print("Warning: tickers.json not found.")
        return []
        
    with open("tickers.json", "r", encoding="utf-8") as f:
        return json.load(f)

def fetch_market_data(tickers):
    """
    使用 yfinance 获取当日收盘价和涨跌幅
    返回 DataFrame: [symbol, name, industry, close, pct_change]
    """
    if not tickers:
        return pd.DataFrame()

    symbols = [t["symbol"] for t in tickers]
    
    # 使用 yfinance 批量下载最近 5 天数据（增加天数以防长假）
    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True
        )
    except Exception as e:
        print(f"yfinance download error: {e}")
        return pd.DataFrame()

    rows = []
    for t in tickers:
        symbol = t["symbol"]
        name = t["name"]
        industry = t["industry"]

        try:
            # 处理多层级索引或单层级索引
            if len(symbols) == 1:
                df = data
            else:
                # 检查 symbol 是否在列中
                if symbol not in data.columns.levels[0]:
                    continue
                df = data[symbol]

            df = df.dropna()
            if len(df) < 2:
                continue

            latest = df.iloc[-1]
            prev = df.iloc[-2]

            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            pct_change = (close - prev_close) / prev_close * 100.0

            rows.append({
                "symbol": symbol,
                "name": name,
                "industry": industry,
                "close": round(close, 2),
                "pct_change": round(pct_change, 2)
            })
        except Exception as e:
            # 静默失败，继续处理下一个
            continue

    df_result = pd.DataFrame(rows)
    if not df_result.empty:
        df_result = df_result.sort_values(by="pct_change", ascending=False).reset_index(drop=True)
    return df_result

def fetch_news():
    if not NEWSDATA_API_KEY:
        return []
    
    url = "https://newsdata.io/api/1/latest"
    params = {
        "apikey": NEWSDATA_API_KEY,
        "q": "business",
    }
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        
        # 添加详细的错误信息
        if resp.status_code == 422:
            error_data = resp.json()
            print(f"422 Error Details: {error_data}")
            # 根据错误信息调整参数
        
        resp.raise_for_status()
        data = resp.json()
        
        # 检查是否有错误信息
        if "error" in data:
            print(f"API Error: {data['error']}")
            return []
            
        articles = data.get("results", [])
        headlines = []
        for a in articles:
            title = a.get("title")
            source = a.get("source_id", "Unknown")
            if title:
                headlines.append(f"{title} ({source})")
        return headlines
        
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response content: {resp.text}")
        return []
    except Exception as e:
        print(f"Error fetching news from Newsdata.io: {e}")
        return []

def build_stocks_markdown(df):
    """
    将股票数据转为文本表格，供 AI 分析
    """
    lines = []
    lines.append("排名 | 代码 | 名称 | 细分行业 | 收盘价 | 涨跌幅(%)")
    lines.append("--- | --- | --- | --- | --- | ---")
    for i, row in df.iterrows():
        lines.append(
            f"{i+1} | {row['symbol']} | {row['name']} | {row['industry']} | {row['close']} | {row['pct_change']}"
        )
    return "\n".join(lines)

def call_llm_analysis(df, news_headlines):
    """
    调用 Google Gemini API
    """
    if not GEMINI_API_KEY:
        return "（未配置 GEMINI_API_KEY，暂无法生成 AI 分析。）"

    stocks_table = build_stocks_markdown(df)

    news_text = ""
    if news_headlines:
        news_text = "\n\n近期与市场相关的新闻标题包括：\n" + "\n".join(
            [f"- {h}" for h in news_headlines]
        )

    # 提示词微调：要求使用 Markdown 格式
    prompt = f"""
你是一名专业的全球宏观与行业分析师。

下面是一份美股市值前 50 名公司在当日收盘时的表现数据（已按涨跌幅从高到低排序）：

{stocks_table}

{news_text}

请你结合：
1. 当前全球及美国的宏观经济环境（如利率、通胀、就业、货币政策等）；
2. 近期的政治与地缘风险（如选举、监管、国际关系等）；
3. 各细分行业的周期位置与景气度变化；
4. 这些龙头公司的典型商业模式与基本面特征（如盈利能力、估值水平、成长性等）；

对上述股票当日的整体表现进行归纳分析，重点回答：
- 哪些板块/行业表现相对更强或更弱，可能的原因是什么？
- 是否可以看出市场在风险偏好、风格（成长 vs 价值、大盘 vs 中小盘）上的偏移？
- 是否有个别公司或板块的表现明显偏离大盘，可能与哪些事件或基本面预期变化有关？
- 对未来短期市场可能的演绎路径，给出审慎的观察要点（而非投资建议）。

要求：
1. **使用 Markdown 格式**（使用 ### 作为小标题，**加粗**重点，- 列表项）；
2. 结构清晰，语言专业简练，中文撰写，字数 1200 字以内。
"""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 1.0
        }
    }

    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return content.strip()
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return "（AI 分析生成失败，请检查 LLM 配置或稍后重试。）"

def build_email_html(df, analysis_text, bj_now):
    """
    构建适配手机的 HTML 邮件模板
    """
    date_str = bj_now.strftime("%Y-%m-%d")
    time_str = bj_now.strftime("%Y-%m-%d %H:%M")

    # ========== 将 Markdown 转换为 HTML ==========
    # 使用 extensions 增强列表和换行处理
    analysis_html = markdown.markdown(analysis_text, extensions=['nl2br', 'sane_lists'])

    # 构建表格 HTML
    rows_html = ""
    for i, row in df.iterrows():
        # 涨跌幅颜色逻辑
        pct = row["pct_change"]
        if pct > 0:
            color = "#16a34a" # 绿色
            sign = "+"
            bg_color = "#f0fdf4" # 浅绿背景
        elif pct < 0:
            color = "#dc2626" # 红色
            sign = ""
            bg_color = "#fef2f2" # 浅红背景
        else:
            color = "#6b7280" # 灰色
            sign = ""
            bg_color = "transparent"
        
        pct_str = f"{sign}{pct}%"

        rows_html += f"""
        <tr>
          <td style="padding:12px 4px;font-size:13px;color:#9ca3af;text-align:center;width:30px;border-bottom:1px solid #f3f4f6;">
            {i+1}
          </td>
          
          <td style="padding:12px 8px;font-size:14px;color:#111827;font-weight:700;width:50px;border-bottom:1px solid #f3f4f6;">
            {row['symbol']}
          </td>
          
          <td style="padding:12px 4px;border-bottom:1px solid #f3f4f6;">
            <div style="font-size:14px;color:#111827;margin-bottom:2px;">
                {row['name']}
            </div>
            <div style="font-size:12px;color:#6b7280;">
                {row['industry']} 
                <span style="display:inline-block;margin-left:8px;padding:2px 6px;border-radius:4px;font-weight:600;color:{color};background-color:{bg_color};font-size:11px;">
                    {pct_str}
                </span>
            </div>
          </td>
        </tr>
        """

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Top 50 Stocks - {date_str}</title>
  <style>
    /* 针对 AI 分析生成的 HTML 进行样式美化 */
    .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
        color: #111827;
        margin-top: 24px;
        margin-bottom: 12px;
        font-size: 16px;
        font-weight: 700;
        line-height: 1.4;
    }}
    .markdown-body p {{
        margin-bottom: 16px;
        line-height: 1.7;
        color: #374151;
    }}
    .markdown-body ul, .markdown-body ol {{
        margin-bottom: 16px;
        padding-left: 20px;
        color: #374151;
    }}
    .markdown-body li {{
        margin-bottom: 6px;
        line-height: 1.6;
    }}
    .markdown-body strong {{
        color: #000000;
        font-weight: 700;
    }}
    .markdown-body blockquote {{
        border-left: 4px solid #e5e7eb;
        padding-left: 16px;
        margin-left: 0;
        color: #6b7280;
        font-style: italic;
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
    <tr>
      <td align="center" style="padding:12px;">
        <table cellpadding="0" cellspacing="0" width="100%" style="max-width:600px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.05);">
          
          <tr>
            <td style="padding:24px;background-color:#1e293b;">
              <div style="font-size:20px;font-weight:700;color:#ffffff;">🌿 Market Pulse</div>
              <div style="margin-top:4px;font-size:13px;color:#94a3b8;">Top 50 US Stocks · {date_str}</div>
            </td>
          </tr>

          <tr>
            <td style="padding:0 16px;">
              <table cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">
                <thead>
                  <tr>
                    <th align="center" style="padding:12px 4px;font-size:11px;color:#9ca3af;font-weight:500;border-bottom:2px solid #f3f4f6;">#</th>
                    <th align="left" style="padding:12px 8px;font-size:11px;color:#9ca3af;font-weight:500;border-bottom:2px solid #f3f4f6;">Symbol</th>
                    <th align="left" style="padding:12px 4px;font-size:11px;color:#9ca3af;font-weight:500;border-bottom:2px solid #f3f4f6;">Name / Ind / %</th>
                  </tr>
                </thead>
                <tbody>
                  {rows_html}
                </tbody>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:32px 20px 8px 20px;">
              <div style="font-size:16px;color:#111827;font-weight:700;margin-bottom:16px;padding-left:10px;border-left:4px solid #3b82f6;">
                📊 市场归纳分析 (AI)
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:0 20px 32px 20px;">
              <div class="markdown-body" style="font-size:14px;background-color:#f9fafb;padding:16px;border-radius:8px;">
                {analysis_html}
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:20px;background-color:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
              <div style="font-size:12px;color:#94a3b8;">
                Generated at {time_str} (Beijing Time)
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return html

def send_email(subject, html_body):
    """
    使用 Resend API 发送邮件
    """
    if not RESEND_API_KEY:
        print("RESEND_API_KEY missing, skipping email.")
        # 如果是本地测试，可以将 html_body 写入文件查看效果
        # with open("test_email.html", "w", encoding="utf-8") as f: f.write(html_body)
        return

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "from": f"Market Pulse <{FROM_EMAIL}>",
        "to": [TO_EMAIL],
        "subject": subject,
        "html": html_body
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")
        if hasattr(resp, 'text'):
            print(resp.text)

# ========== 主流程 ==========

def main():
    print("Starting process...")
    # 1. 加载名单
    tickers = load_tickers()
    if not tickers:
        print("Ticker list is empty.")
        return

    # 2. 获取数据
    print("Fetching market data...")
    df = fetch_market_data(tickers)
    if df.empty:
        print("No market data fetched.")
        return

    # 3. 获取新闻
    print("Fetching news...")
    news_headlines = fetch_news()

    # 4. AI 分析
    print("Analyzing with Gemini...")
    analysis_text = call_llm_analysis(df, news_headlines)

    # 5. 构建邮件
    bj_now = get_beijing_now()
    date_str = bj_now.strftime("%Y-%m-%d")
    subject = f"🌸 Top 50 US Stocks - {date_str}"
    
    html_body = build_email_html(df, analysis_text, bj_now)

    # 6. 发送
    print("Sending email...")
    send_email(subject, html_body)
    print("Done.")

if __name__ == "__main__":
    main()
