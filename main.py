import os
import json
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone

# ========== 配置部分 ==========

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
TO_EMAIL = os.getenv("TO_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY") 
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

# ========== 工具函数 ==========

def get_beijing_now():
    """获取当前北京时间"""
    utc_now = datetime.now(timezone.utc)
    bj_now = utc_now + timedelta(hours=8)
    return bj_now

def load_tickers():
    """加载 tickers.json 中的公司列表"""
    with open("tickers.json", "r", encoding="utf-8") as f:
        return json.load(f)

def fetch_market_data(tickers):
    """
    使用 yfinance 获取当日收盘价和涨跌幅
    返回 DataFrame: [symbol, name, industry, close, pct_change]
    """
    symbols = [t["symbol"] for t in tickers]
    # 使用 yfinance 批量下载最近 3 天数据（确保涵盖周末/节假日逻辑）
    data = yf.download(
        tickers=" ".join(symbols),
        period="3d",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        threads=True
    )

    rows = []
    for t in tickers:
        symbol = t["symbol"]
        name = t["name"]
        industry = t["industry"]

        try:
            if len(symbols) == 1:
                df = data
            else:
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
            print(f"Error fetching data for {symbol}: {e}")

    df_result = pd.DataFrame(rows)
    if not df_result.empty:
        df_result = df_result.sort_values(by="pct_change", ascending=False).reset_index(drop=True)
    return df_result

def fetch_news():
    """
    使用 Newsdata.io 获取当日美国商业/财经新闻标题
    注意：Newsdata.io 免费版每天限制 200 次请求
    """
    if not NEWSDATA_API_KEY:
        return []

    url = "https://newsdata.io/api/1/news"
    params = {
        "apikey": NEWSDATA_API_KEY,
        "country": "us",
        "category": "business",
        "language": "en",
        "size": 10  # 限制返回条数，节省 token 和阅读量
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        # Newsdata.io 的返回结构是 'results' 列表
        articles = data.get("results", [])
        headlines = []
        for a in articles:
            title = a.get("title")
            # source_id 通常是媒体名称 (如 cnn, bloomberg)
            source = a.get("source_id", "Unknown")
            if title:
                headlines.append(f"{title} ({source})")
        return headlines
    except Exception as e:
        print(f"Error fetching news from Newsdata.io: {e}")
        return []

def build_stocks_markdown(df):
    """
    将股票数据转为文本表格，供 AI 分析 & 邮件展示
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
    修改 5: 调用 Google Gemini API
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set, skip AI analysis.")
        return "（未配置 GEMINI_API_KEY，暂无法生成 AI 分析。）"

    stocks_table = build_stocks_markdown(df)

    news_text = ""
    if news_headlines:
        news_text = "\n\n近期与市场相关的新闻标题包括：\n" + "\n".join(
            [f"- {h}" for h in news_headlines]
        )

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
- 使用中文撰写；
- 结构清晰，有小标题或分段；
- 语言专业但通俗易懂；
- 字数不超过 1000 字。
"""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.6
        }
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        # 这里的 URL 已经在配置部分包含了 API Key
        resp = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        
        # 解析 Gemini 的响应结构
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return content.strip()
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        # 如果出错，打印详细信息以便调试
        try:
            print(resp.text)
        except:
            pass
        return "（AI 分析生成失败，请检查 LLM 配置或稍后重试。）"

def build_email_html(df, analysis, bj_now):
    """
    构建适配手机的 HTML 邮件模板
    - 移除收盘价列
    - 将行业和涨跌幅合并到名称下方
    - 移除冗余标签
    """
    date_str = bj_now.strftime("%Y-%m-%d")
    time_str = bj_now.strftime("%Y-%m-%d %H:%M")

    # 构建表格 HTML
    rows_html = ""
    for i, row in df.iterrows():
        # 涨跌幅颜色逻辑
        if row["pct_change"] > 0:
            color = "#16a34a" # 绿色
            sign = "+"
        elif row["pct_change"] < 0:
            color = "#dc2626" # 红色
            sign = ""
        else:
            color = "#6b7280" # 灰色
            sign = ""
        
        # 格式化涨跌幅字符串
        pct_str = f"{sign}{row['pct_change']}%"

        rows_html += f"""
        <tr>
          <td style="padding:12px 4px;font-size:13px;color:#9ca3af;vertical-align:middle;text-align:center;width:30px;">
            {i+1}
          </td>
          
          <td style="padding:12px 8px;font-size:14px;color:#111827;font-weight:700;vertical-align:middle;width:50px;">
            {row['symbol']}
          </td>
          
          <td style="padding:12px 4px;vertical-align:middle;">
            <div style="font-size:14px;color:#111827;margin-bottom:2px;line-height:1.4;">
                {row['name']}
            </div>
            <div style="font-size:12px;color:#6b7280;line-height:1.4;">
                {row['industry']} 
                <span style="margin:0 4px;color:#e5e7eb;">|</span> 
                <span style="font-weight:600;color:{color};">{pct_str}</span>
            </div>
          </td>
        </tr>
        <tr><td colspan="3" style="border-bottom:1px solid #f3f4f6;"></td></tr>
        """

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Top 50 Stocks - {date_str}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
    <tr>
      <td align="center" style="padding:12px;">
        <table cellpadding="0" cellspacing="0" width="100%" style="max-width:600px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.05);">
          
          <tr>
            <td style="padding:20px;background-color:#1e293b;">
              <div style="font-size:18px;font-weight:700;color:#ffffff;">🌿 Top 50 Stocks</div>
              <div style="margin-top:4px;font-size:12px;color:#94a3b8;">{date_str} · Market Pulse</div>
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
            <td style="padding:24px 20px 8px 20px;">
              <div style="font-size:15px;color:#111827;font-weight:700;margin-bottom:8px;padding-left:10px;border-left:4px solid #3b82f6;">
                📊 市场归纳分析
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:0 20px 24px 20px;">
              <div style="font-size:14px;color:#374151;line-height:1.7;white-space:pre-wrap;background-color:#f9fafb;padding:12px;border-radius:8px;">
                {analysis}
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:16px 20px;background-color:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
              <div style="font-size:11px;color:#94a3b8;">
                Updated at {time_str} (Beijing Time)
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
    if not RESEND_API_KEY or not TO_EMAIL or not FROM_EMAIL:
        raise RuntimeError("RESEND_API_KEY / TO_EMAIL / FROM_EMAIL 未正确配置。")

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

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    try:
        resp.raise_for_status()
        print("Email sent successfully.")
    except Exception as e:
        print("Failed to send email:", resp.text)
        raise e

# ========== 主流程 ==========

def main():
    # 第一步：加载美股市值前 50 名公司名单
    tickers = load_tickers()

    # 第二步 & 第三步：获取当日收盘数据
    df = fetch_market_data(tickers)
    if df.empty:
        print("No market data fetched. Abort.")
        return

    # 获取新闻
    news_headlines = fetch_news()

    # 第四步：调用 Gemini 进行归纳分析
    analysis = call_llm_analysis(df, news_headlines)

    # 时间 & 标题
    bj_now = get_beijing_now()
    date_str = bj_now.strftime("%Y-%m-%d")
    subject = f"🌸 Top 50 Stocks - {date_str}"

    # 构建 HTML 邮件
    html_body = build_email_html(df, analysis, bj_now)

    # 第五步 & 第六步：发送邮件
    send_email(subject, html_body)


if __name__ == "__main__":
    main()
