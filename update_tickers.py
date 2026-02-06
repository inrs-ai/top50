import yfinance as yf
import pandas as pd
import json
import os

def update_top_50_tickers():
    print("正在从维基百科获取 S&P 500 列表...")
    # 获取 S&P 500 列表作为基础池（覆盖了绝大多数 Top 50）
    table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
    df = table[0]
    tickers = df['Symbol'].tolist()
    
    # 修正一些 yfinance 无法识别的符号（如 BRK.B -> BRK-B）
    tickers = [t.replace('.', '-') for t in tickers]

    print(f"正在获取 {len(tickers)} 家公司的市值数据...")
    data_list = []
    
    # 分批获取数据以提高效率
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i+50]
        for symbol in batch:
            try:
                ticker_obj = yf.Ticker(symbol)
                info = ticker_obj.info
                
                market_cap = info.get('marketCap', 0)
                if market_cap:
                    data_list.append({
                        "symbol": symbol.replace('-', '.'), # 换回原始格式
                        "name": info.get('longName', ''),
                        "industry": info.get('industry', ''),
                        "marketCap": market_cap
                    })
            except Exception as e:
                print(f"无法获取 {symbol} 的数据: {e}")

    # 按市值降序排列并取前 50
    data_list.sort(key=lambda x: x['marketCap'], reverse=True)
    top_50 = data_list[:50]

    # 格式化为最终输出格式（剔除 marketCap 字段，保持与你原始格式一致）
    final_output = [
        {"symbol": x['symbol'], "name": x['name'], "industry": x['industry']} 
        for x in top_50
    ]

    # 写入文件
    with open('tickers.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
    print(f"成功更新 tickers.json，共 {len(final_output)} 个代码。")

if __name__ == "__main__":
    update_top_50_tickers()
