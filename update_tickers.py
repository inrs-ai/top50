"""
update_tickers.py

数据来源：
  排名 + symbol + name → companiesmarketcap.com（1 次请求）
  industry             → 维基百科 S&P 500 表格 （1 次请求）

总计 2 次 HTTP 请求，耗时 2-3 秒，无需任何 API Key

依赖：pip install requests beautifulsoup4 pandas lxml
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import os
import sys
import shutil
from io import StringIO
from datetime import datetime


# ======================== 配置 ========================
OUTPUT_FILE = "tickers.json"
BACKUP_FILE = "tickers.json.bak"
TOP_N = 50

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


# ======================== 数据抓取 ========================

def fetch_top_n_from_cmc(n: int = TOP_N) -> list:
    """
    从 companiesmarketcap.com 抓取美股市值前 N 名
    返回 [{"symbol": "AAPL", "name": "Apple"}, ...]
    """
    print(f"步骤 1/3: 从 companiesmarketcap.com 获取市值排名...")

    url = ("https://companiesmarketcap.com/usa/"
           "largest-companies-in-the-usa-by-market-cap/")

    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # ---- 解析策略 ----
    # 该网站的每行公司信息包含:
    #   .company-name  → 公司名称
    #   .company-code  → 股票代码
    # 它们按市值降序排列，直接取前 N 个即可

    name_tags = soup.select(".company-name")
    code_tags = soup.select(".company-code")

    # ---- 解析失败时输出诊断信息 ----
    if not name_tags or not code_tags:
        # 可能页面结构已变更，输出线索帮助排查
        all_classes = set()
        for tag in soup.find_all(True, class_=True):
            for cls in tag.get("class", []):
                if "company" in cls.lower() or "name" in cls.lower():
                    all_classes.add(cls)
        print(f"  ⚠ .company-name/.company-code 选择器失效")
        print(f"  页面中包含 'company/name' 的 class: {all_classes or '无'}")
        raise ValueError(
            "无法解析 companiesmarketcap.com，页面结构可能已变更"
        )

    results = []
    for name_tag, code_tag in zip(name_tags, code_tags):
        symbol = code_tag.get_text(strip=True)
        name = name_tag.get_text(strip=True)
        if symbol and name:
            results.append({"symbol": symbol, "name": name})
        if len(results) >= n:
            break

    print(f"  ✔ 获取到前 {len(results)} 名公司")

    if results:
        print(f"  第 1 名: {results[0]['symbol']} ({results[0]['name']})")
        print(f"  第{len(results):>2} 名: "
              f"{results[-1]['symbol']} ({results[-1]['name']})")

    return results


def fetch_industry_from_wikipedia() -> dict:
    """
    从维基百科获取 S&P 500 行业分类映射表
    返回 {"AAPL": "Technology Hardware, Storage & Peripherals", ...}
    """
    print(f"\n步骤 2/3: 从维基百科获取行业分类...")

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]

    industry_map = {}
    for _, row in df.iterrows():
        symbol = str(row["Symbol"]).strip()
        industry = str(row.get("GICS Sub-Industry", "")).strip()
        industry_map[symbol] = industry

    print(f"  ✔ 获取到 {len(industry_map)} 个行业分类")
    return industry_map


# ======================== 辅助函数 ========================

def normalize_symbol(symbol: str) -> str:
    """
    统一符号格式，处理不同来源的差异
    companiesmarketcap 可能用 BRK-B，维基百科用 BRK.B
    """
    return symbol.replace("-", ".").strip()


def show_diff(old_file: str, new_data: list):
    """对比新旧列表的成分股变动"""
    if not os.path.exists(old_file):
        return

    try:
        with open(old_file, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    old_set = {item["symbol"] for item in old_data}
    new_set = {item["symbol"] for item in new_data}

    added   = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)

    if added:
        print(f"  📈 新进入 Top {TOP_N}: {', '.join(added)}")
    if removed:
        print(f"  📉 退出 Top {TOP_N}: {', '.join(removed)}")
    if not added and not removed:
        print(f"  ✔ 成分股无变化（排名可能有调整）")


# ======================== 主流程 ========================

def main():
    print("=" * 56)
    print(f"  美股市值 Top {TOP_N} 更新工具")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 56)

    # ---- 0. 备份旧文件 ----
    if os.path.exists(OUTPUT_FILE):
        shutil.copy2(OUTPUT_FILE, BACKUP_FILE)
        print(f"\n已备份 {OUTPUT_FILE} → {BACKUP_FILE}")

    # ---- 1. 获取市值排名 ----
    try:
        top_list = fetch_top_n_from_cmc(TOP_N)
    except Exception as e:
        print(f"\n❌ 获取市值排名失败: {e}")
        sys.exit(1)

    if len(top_list) < TOP_N:
        print(f"\n❌ 仅获取到 {len(top_list)} 条，不足 {TOP_N}，终止更新")
        sys.exit(1)

    # ---- 2. 获取行业分类 ----
    try:
        industry_map = fetch_industry_from_wikipedia()
    except Exception as e:
        print(f"\n⚠ 获取行业分类失败: {e}")
        print("  将以空白行业继续...")
        industry_map = {}

    # ---- 3. 合并数据 ----
    print(f"\n步骤 3/3: 合并数据并写入文件...")

    final_output = []
    no_industry = []

    for item in top_list:
        raw_symbol = item["symbol"]
        std_symbol = normalize_symbol(raw_symbol)

        # 尝试多种格式匹配维基百科的行业数据
        industry = (
            industry_map.get(std_symbol) or
            industry_map.get(raw_symbol) or
            industry_map.get(std_symbol.replace(".", "-")) or
            ""
        )

        if not industry:
            no_industry.append(std_symbol)

        final_output.append({
            "symbol": std_symbol,
            "name": item["name"],
            "industry": industry,
        })

    if no_industry:
        print(f"  ⚠ 以下股票未匹配到行业: {', '.join(no_industry)}")
        print(f"    （可能不在 S&P 500 中）")

    # ---- 4. 对比变化 ----
    if os.path.exists(BACKUP_FILE):
        show_diff(BACKUP_FILE, final_output)

    # ---- 5. 写入文件 ----
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    # ---- 6. 打印结果 ----
    print(f"\n{'─' * 56}")
    print(f"✅ 已更新 {OUTPUT_FILE}，共 {len(final_output)} 条\n")

    print(f"{'排名':>4}  {'代码':<7} {'行业':<30} {'公司名称'}")
    print(f"{'─' * 80}")
    for i, item in enumerate(final_output, 1):
        ind = item['industry'][:28] if item['industry'] else "(未分类)"
        print(f"{i:>4}. {item['symbol']:<7} {ind:<30} {item['name']}")

    print(f"\n完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
