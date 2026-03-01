"""
update_tickers.py
使用 Financial Modeling Prep (FMP) 免费 API 更新美股市值 Top 50 列表
建议每月执行一次，通过 cron 或 GitHub Actions 定时触发
"""

import requests
import json
import os
import sys
import shutil
from datetime import datetime


# ======================== 配置 ========================
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
OUTPUT_FILE = "tickers.json"
BACKUP_FILE = "tickers.json.bak"
TOP_N = 50
# 市值门槛（美元），设为 500 亿作为缓冲，确保能覆盖 Top 50
MARKET_CAP_FLOOR = 50_000_000_000


def fetch_large_cap_stocks(api_key: str) -> list:
    """
    调用 FMP Stock Screener API
    一次请求获取所有市值 > 阈值的美股（通常 80~120 家）
    """
    url = "https://financialmodelingprep.com/api/v3/stock-screener"
    params = {
        "marketCapMoreThan": MARKET_CAP_FLOOR,
        "exchange": "NYSE,NASDAQ",       # 仅美股主要交易所
        "isEtf": False,                  # 排除 ETF
        "isFund": False,                 # 排除基金
        "isActivelyTrading": True,       # 仅活跃交易的股票
        "limit": 200,                    # 留足余量
        "apikey": api_key,
    }

    print(f"  请求 URL: {url}")
    print(f"  筛选条件: 市值 > ${MARKET_CAP_FLOOR / 1e9:.0f}B, 交易所=NYSE/NASDAQ")

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # ---------- 错误检测 ----------
    # FMP 在 Key 无效/过期时返回 {"Error Message": "..."}
    if isinstance(data, dict):
        if "Error Message" in data:
            raise ValueError(f"FMP API 错误: {data['Error Message']}")
        raise ValueError(f"API 返回了意外的字典: {data}")

    if not isinstance(data, list):
        raise ValueError(f"API 返回了意外的数据类型: {type(data)}")

    # ---------- 二次过滤（防御性编程）----------
    cleaned = []
    for stock in data:
        mc = stock.get("marketCap") or 0
        symbol = stock.get("symbol", "")
        # 排除无市值、无代码、含特殊字符的条目（如优先股 XXX-PA）
        if mc > 0 and symbol and "-" not in symbol and "." not in symbol:
            cleaned.append(stock)

    return cleaned


def build_output(stocks: list) -> list:
    """
    按市值降序排列，取前 TOP_N 条，格式化为目标 JSON 结构
    """
    stocks.sort(key=lambda x: x.get("marketCap", 0) or 0, reverse=True)
    top = stocks[:TOP_N]

    result = []
    for s in top:
        result.append({
            "symbol":   s.get("symbol", ""),
            "name":     s.get("companyName", ""),
            "industry": s.get("industry", ""),
        })
    return result


def show_diff(old_file: str, new_data: list):
    """
    对比新旧数据，打印成分股变动
    """
    if not os.path.exists(old_file):
        return

    try:
        with open(old_file, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    old_symbols = {item["symbol"] for item in old_data}
    new_symbols = {item["symbol"] for item in new_data}

    added   = sorted(new_symbols - old_symbols)
    removed = sorted(old_symbols - new_symbols)

    if added:
        print(f"\n  📈 新进入 Top {TOP_N}: {', '.join(added)}")
    if removed:
        print(f"  📉 退出 Top {TOP_N}: {', '.join(removed)}")
    if not added and not removed:
        print(f"\n  成分股无变化（排名可能有调整）")


def main():
    print("=" * 56)
    print(f"  美股市值 Top {TOP_N} 更新工具 (FMP API)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 56)

    # ---- 1. 检查 API Key ----
    if not FMP_API_KEY:
        print("\n❌ 错误：未设置 FMP_API_KEY 环境变量。")
        print("   1) 前往 https://financialmodelingprep.com/register 注册")
        print("   2) 复制你的 API Key")
        print("   3) 运行: export FMP_API_KEY=你的Key")
        sys.exit(1)

    # ---- 2. 备份旧文件 ----
    if os.path.exists(OUTPUT_FILE):
        shutil.copy2(OUTPUT_FILE, BACKUP_FILE)
        print(f"\n已备份 {OUTPUT_FILE} → {BACKUP_FILE}")

    # ---- 3. 调用 API ----
    print(f"\n正在从 Financial Modeling Prep 获取数据...\n")
    try:
        stocks = fetch_large_cap_stocks(FMP_API_KEY)
    except requests.exceptions.HTTPError as e:
        print(f"\n❌ HTTP 请求失败: {e}")
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
            if status == 401:
                print("   → API Key 无效或已过期，请检查。")
            elif status == 403:
                print("   → 免费额度可能已用完，请明天再试或升级。")
            elif status == 429:
                print("   → 请求过于频繁，请稍后重试。")
        return
    except ValueError as e:
        print(f"\n❌ 数据异常: {e}")
        return
    except Exception as e:
        print(f"\n❌ 未知错误: {e}")
        return

    print(f"  获取到 {len(stocks)} 家公司（市值 > ${MARKET_CAP_FLOOR / 1e9:.0f}B）")

    # ---- 4. 校验数据量 ----
    if len(stocks) < TOP_N:
        print(f"\n⚠️  警告：仅获取到 {len(stocks)} 条记录，不足 {TOP_N} 条。")
        print(f"   可能原因：API Key 权限受限 / 市值阈值过高 / 网络问题")
        if len(stocks) == 0:
            print("   终止更新。")
            return
        print(f"   将以 {len(stocks)} 条记录继续...")

    # ---- 5. 构建输出 ----
    final_output = build_output(stocks)

    # ---- 6. 对比变化 ----
    show_diff(BACKUP_FILE, final_output)

    # ---- 7. 写入文件 ----
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    # ---- 8. 打印结果 ----
    print(f"\n{'—' * 56}")
    print(f"✅ 成功更新 {OUTPUT_FILE}，共 {len(final_output)} 条记录\n")

    # 打印完整列表
    print(f"{'排名':>4}  {'代码':<7} {'公司名称'}")
    print(f"{'—' * 56}")
    for i, item in enumerate(final_output, 1):
        print(f"{i:>4}. {item['symbol']:<7} {item['name']}")

    print(f"\n更新完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
