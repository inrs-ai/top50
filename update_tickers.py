import yfinance as yf
import pandas as pd
import json
import time
import random
import os

def update_top_50_tickers():
    print("正在从维基百科获取 S&P 500 列表...")
    try:
        table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
        df = table[0]
        tickers = df['Symbol'].tolist()
    except Exception as e:
        print(f"获取 S&P 500 列表失败: {e}")
        return

    # 修正符号格式
    tickers = [t.replace('.', '-') for t in tickers]

    print(f"正在获取 {len(tickers)} 家公司的市值数据（已启用延迟）...")
    data_list = []
    
    for index, symbol in enumerate(tickers):
        try:
            ticker_obj = yf.Ticker(symbol)
            # 访问 info 属性会触发网络请求
            info = ticker_obj.info
            
            market_cap = info.get('marketCap', 0)
            if market_cap:
                data_list.append({
                    "symbol": symbol.replace('-', '.'),
                    "name": info.get('longName', ''),
                    "industry": info.get('industry', ''),
                    "marketCap": market_cap
                })
            
            # 每查询 10 个打印一次进度
            if (index + 1) % 10 == 0:
                print(f"进度: {index + 1}/{len(tickers)}")

            # --- 核心改进：添加随机休眠 ---
            # 基础休眠 0.5 秒，加上 0 到 1 秒之间的随机抖动
            time.sleep(0.5 + random.random())

        except Exception as e:
            print(f"无法获取 {symbol} 的数据: {e}")
            # 如果报错，多等一会儿再继续
            time.sleep(5)

    # 按市值降序排列并取前 50
    data_list.sort(key=lambda x: x['marketCap'], reverse=True)
    top_50 = data_list[:50]

    final_output = [
        {"symbol": x['symbol'], "name": x['name'], "industry": x['industry']} 
        for x in top_50
    ]

    with open('tickers.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
    print(f"成功更新 tickers.json，共 {len(final_output)} 个代码。")

if __name__ == "__main__":
    update_top_50_tickers()
