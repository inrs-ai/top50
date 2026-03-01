"""
update_tickers.py
使用 Financial Modeling Prep (FMP) 免费 API 更新美股市值 Top 50 列表
工作流程：
  1. 从维基百科获取 S&P 500 成分股列表（免费、稳定）
  2. 通过 FMP /quote 批量接口获取各股市值（免费计划可用）
  3. 按市值降序排列，取前 50 名
  4. 通过 FMP /profile 批量接口获取公司名称和行业
  5. 写入 tickers.json
依赖：pip install requests pandas lxml
环境变量：FMP_API_KEY
"""

import requests
import pandas as pd
import json
import os
import sys
import shutil
import time
from datetime import datetime

# ======================== 配置 ========================
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FMP_BASE = "https://financialmodelingprep.com/api/v3"
OUTPUT_FILE = "tickers.json"
BACKUP_FILE = "tickers.json.bak"
TOP_N = 50
BATCH_SIZE = 30          # 每批查询的股票数
REQUEST_DELAY = 0.4      # 批次间隔（秒）


# ======================== 工具函数 ========================

def fmp_get(endpoint: str) -> list:
    """
    FMP API 通用 GET 请求
    自动附带 apikey，统一处理错误
    """
    url = f"{FMP_BASE}/{endpoint}"
    params = {"apikey": FMP_API_KEY}

    resp = requests.get(url, params=params, timeout=30)

    if resp.status_code == 403:
        raise PermissionError(
            f"FMP 返回 403（{endpoint}）\n"
            "    该接口可能不在免费计划内，请确认你的订阅等级。\n"
            "    免费计划支持的接口: quote, profile 等基础接口\n"
            "    不支持的接口: stock-screener, bulk 等高级接口"
        )
    resp.raise_for_status()

    data = resp.json()

    if isinstance(data, dict) and "Error Message" in data:
        raise ValueError(f"FMP 错误: {data['Error Message']}")

    return data if isinstance(data, list) else []


def sym_to_fmp(symbol: str) -> str:
    """维基百科格式 → FMP 格式：BRK.B → BRK-B"""
    return symbol.replace(".", "-")


def sym_from_fmp(symbol: str) -> str:
    """FMP 格式 → 标准格式：BRK-B → BRK.B"""
    return symbol.replace("-", ".")


# ======================== 数据获取 ========================

def fetch_sp500_from_wikipedia() -> dict:
    """
    从维基百科获取 S&P 500 成分股
    返回 {symbol: {name, industry}}，symbol 为维基百科原始格式
    """
    print("步骤 1: 从维基百科获取 S&P 500 成分股列表...")

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df = tables[0]

    wiki_data = {}
    for _, row in df.iterrows():
        symbol = str(row["Symbol"]).strip()
        wiki_data[symbol] = {
            "name": str(row.get("Security", "")).strip(),
            "industry": str(row.get("GICS Sub-Industry", "")).strip(),
        }

    print(f"  ✔ 获取到 {len(wiki_data)} 个成分股")
    return wiki_data


def fetch_market_caps(symbols: list) -> dict:
    """
    使用 FMP /quote/{batch} 批量获取市值
    参数：symbols 为维基百科格式的 symbol 列表
    返回：{fmp_symbol: market_cap}
    """
    fmp_syms = [sym_to_fmp(s) for s in symbols]
    results = {}
    total_batches = (len(fmp_syms) + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"\n步骤 2: 通过 FMP /quote 获取市值（共 {total_batches} 批）...")

    for i in range(0, len(fmp_syms), BATCH_SIZE):
        batch = fmp_syms[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        batch_str = ",".join(batch)

        try:
            data = fmp_get(f"quote/{batch_str}")
            for item in data:
                sym = item.get("symbol", "")
                mc = item.get("marketCap") or 0
                if sym and mc > 0:
                    results[sym] = mc
        except PermissionError:
            raise                          # 权限错误，直接终止
        except Exception as e:
            print(f"  ⚠ 批次 {batch_num} 失败: {e}")

        # 进度显示
        if batch_num % 5 == 0 or batch_num == total_batches:
            print(f"  进度: {batch_num}/{total_batches} 批, "
                  f"已获取 {len(results)} 个市值")

        time.sleep(REQUEST_DELAY)

    print(f"  ✔ 共获取到 {len(results)} 个有效市值")
    return results


def fetch_profiles(fmp_symbols: list) -> dict:
    """
    使用 FMP /profile/{batch} 获取公司名称和行业
    返回：{fmp_symbol: {name, industry}}
    """
    results = {}
    total_batches = (len(fmp_symbols) + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"\n步骤 3: 通过 FMP /profile 获取 Top {TOP_N} 详情"
          f"（共 {total_batches} 批）...")

    for i in range(0, len(fmp_symbols), BATCH_SIZE):
        batch = fmp_symbols[i : i + BATCH_SIZE]
        batch_str = ",".join(batch)

        try:
            data = fmp_get(f"profile/{batch_str}")
            for item in data:
                sym = item.get("symbol", "")
                if sym:
                    results[sym] = {
                        "name": item.get("companyName", ""),
                        "industry": item.get("industry", ""),
                    }
        except PermissionError:
            print("  ⚠ /profile 接口不可用，将使用维基百科数据替代")
            break
        except Exception as e:
            print(f"  ⚠ profile 批次失败: {e}")

        time.sleep(REQUEST_DELAY)

    print(f"  ✔ 获取到 {len(results)} 个公司详情")
    return results


# ======================== 对比与输出 ========================

def show_diff(old_file: str, new_data: list):
    """对比新旧数据，打印成分股变动"""
    if not os.path.exists(old_file):
        return

    try:
        with open(old_file, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    old_set = {item["symbol"] for item in old_data}
    new_set = {item["symbol"] for item in new_data}

    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)

    if added:
        print(f"  📈 新进入 Top {TOP_N}: {', '.join(added)}")
    if removed:
        print(f"  📉 退出 Top {TOP_N}: {', '.join(removed)}")
    if not added and not removed:
        print(f"  成分股无变化（排名可能有调整）")


# ======================== 主流程 ========================

def main():
    print("=" * 56)
    print(f"  美股市值 Top {TOP_N} 更新工具 (FMP API)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 56)

    # ---- 0. 检查 API Key ----
    if not FMP_API_KEY:
        print("\n❌ 未设置 FMP_API_KEY 环境变量")
        print("   export FMP_API_KEY=你的密钥")
        sys.exit(1)

    # ---- 1. 备份旧文件 ----
    if os.path.exists(OUTPUT_FILE):
        shutil.copy2(OUTPUT_FILE, BACKUP_FILE)
        print(f"\n已备份 {OUTPUT_FILE} → {BACKUP_FILE}")

    # ---- 2. 获取 S&P 500 列表 ----
    try:
        wiki_data = fetch_sp500_from_wikipedia()
    except Exception as e:
        print(f"\n❌ 获取 S&P 500 列表失败: {e}")
        return

    symbols = list(wiki_data.keys())

    # ---- 3. 获取市值 ----
    try:
        market_caps = fetch_market_caps(symbols)
    except PermissionError as e:
        print(f"\n❌ {e}")
        print("\n💡 请先手动测试你的 API Key 是否可用：")
        print(f"   curl \"{FMP_BASE}/quote/AAPL?apikey=你的Key\"")
        return
    except Exception as e:
        print(f"\n❌ 获取市值失败: {e}")
        return

    if len(market_caps) < TOP_N:
        print(f"\n❌ 仅获取到 {len(market_caps)} 个有效市值，不足 {TOP_N}，终止更新。")
        return

    # ---- 4. 排序取 Top N ----
    sorted_syms = sorted(market_caps, key=market_caps.get, reverse=True)
    top_syms = sorted_syms[:TOP_N]

    # ---- 5. 获取 Top N 公司详情 ----
    profiles = fetch_profiles(top_syms)

    # ---- 6. 组装最终结果 ----
    final_output = []
    for fmp_sym in top_syms:
        std_sym = sym_from_fmp(fmp_sym)

        # 优先使用 FMP profile 数据
        if fmp_sym in profiles and profiles[fmp_sym]["name"]:
            name = profiles[fmp_sym]["name"]
            industry = profiles[fmp_sym]["industry"]
        else:
            # Fallback: 维基百科数据
            wiki_entry = wiki_data.get(std_sym, {})
            name = wiki_entry.get("name", std_sym)
            industry = wiki_entry.get("industry", "")

        final_output.append({
            "symbol": std_sym,
            "name": name,
            "industry": industry,
        })

    # ---- 7. 对比变化 ----
    if os.path.exists(BACKUP_FILE):
        print(f"\n与上次对比:")
        show_diff(BACKUP_FILE, final_output)

    # ---- 8. 写入文件 ----
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    # ---- 9. 打印结果 ----
    print(f"\n{'─' * 56}")
    print(f"✅ 成功更新 {OUTPUT_FILE}，共 {len(final_output)} 条\n")

    print(f"{'排名':>4}  {'代码':<7} {'公司名称'}")
    print(f"{'─' * 56}")
    for i, item in enumerate(final_output, 1):
        print(f"{i:>4}. {item['symbol']:<7} {item['name']}")

    print(f"\n完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
