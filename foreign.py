import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import datetime
import requests
import pandas as pd

# 載入 .env 變數 (雲端部署時會自動抓取 Railway 上的變數)
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')

intents = discord.Intents.default()
# 因為要讀取你輸入的指令，確保 message_content 權限有開啟
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)

# 設定台灣時間 (UTC+8) 晚上 8 點播報
tz = datetime.timezone(datetime.timedelta(hours=8))
report_time = datetime.time(hour=20, minute=0, tzinfo=tz)

@bot.event
async def on_ready():
    print(f'機器人已成功登入：{bot.user}')
    if not daily_report.is_running():
        daily_report.start()
        print("已啟動每晚 8 點的外資籌碼排程播報任務。")

# --- 【新增的手動觸發指令】 ---
@bot.command(name='籌碼', help='手動查詢今日外資買賣超前十名')
async def manual_report(ctx):
    today = datetime.datetime.now(tz)
    await ctx.send("🔄 正在手動抓取今日外資買賣超資料，請稍候...")
    try:
        report_message = fetch_foreign_investor_data(today)
        await ctx.send(report_message)
    except Exception as e:
        await ctx.send(f"⚠️ 抓取資料時發生錯誤：{e}\n(可能今日未開盤或交易所尚未更新資料)")
# -----------------------------

@tasks.loop(time=report_time)
async def daily_report():
    today = datetime.datetime.now(tz)
    # 週末不播報 (0=週一, 6=週日)
    if today.weekday() >= 5: 
        return

    if not CHANNEL_ID:
        print("錯誤：找不到 CHANNEL_ID")
        return
        
    channel = bot.get_channel(int(CHANNEL_ID))
    if channel:
        await channel.send("🔄 定時任務：正在抓取今日外資買賣超資料...")
        try:
            report_message = fetch_foreign_investor_data(today)
            await channel.send(report_message)
        except Exception as e:
            await channel.send(f"⚠️ 抓取資料時發生錯誤：{e}\n(可能今日未開盤或交易所尚未更新資料)")

def fetch_foreign_investor_data(date_obj):
    # 轉換日期格式
    twse_date = date_obj.strftime("%Y%m%d")          # 上市格式: 20240304
    tpex_date = f"{date_obj.year - 1911}/{date_obj.strftime('%m/%d')}"  # 上櫃格式: 113/03/04

    msg = f"📊 **【外資今日買賣超前十檔統整】** ({date_obj.strftime('%Y-%m-%d')})\n\n"

    # --- 1. 抓取上市 (TWSE) 資料 ---
    try:
        twse_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={twse_date}&selectType=ALL&response=json"
        res = requests.get(twse_url).json()
        if res.get('stat') == 'OK':
            df_twse = pd.DataFrame(res['data'], columns=res['fields'])
            net_col = [c for c in df_twse.columns if '外陸資買賣超股數(不含外資自營商)' in c or '買賣超股數' in c][0]
            df_twse = df_twse[['證券代號', '證券名稱', net_col]].copy()
            df_twse.columns = ['Code', 'Name', 'Net']
            
            df_twse['Net'] = df_twse['Net'].astype(str).str.replace(',', '').astype(float) / 1000
            df_twse = df_twse[df_twse['Code'].str.len() == 4] # 篩選一般股票

            top_buy_twse = df_twse.nlargest(10, 'Net')
            top_sell_twse = df_twse.nsmallest(10, 'Net')

            msg += "**📈 上市外資買超前十名**\n"
            for i, row in enumerate(top_buy_twse.itertuples(), 1):
                msg += f"{i}. {row.Name} ({row.Code})：{int(row.Net):,} 張\n"
            
            msg += "\n**📉 上市外資賣超前十名**\n"
            for i, row in enumerate(top_sell_twse.itertuples(), 1):
                msg += f"{i}. {row.Name} ({row.Code})：{int(row.Net):,} 張\n"
        else:
            msg += "⚠️ 查無今日上市資料 (可能為假日或未更新)\n"
    except Exception as e:
        msg += f"⚠️ 上市資料抓取失敗 ({e})\n"

    msg += "\n-----------------------\n\n"

    # --- 2. 抓取上櫃 (TPEx) 資料 ---
    try:
        tpex_url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={tpex_date}"
        res = requests.get(tpex_url).json()
        if res.get('aaData'):
            df_tpex = pd.DataFrame(res['aaData'])
            df_tpex = df_tpex[[0, 1, 4]].copy()
            df_tpex.columns = ['Code', 'Name', 'Net']
            
            df_tpex['Net'] = df_tpex['Net'].astype(str).str.replace(',', '').astype(float) / 1000
            df_tpex = df_tpex[df_tpex['Code'].str.len() == 4] 

            top_buy_tpex = df_tpex.nlargest(10, 'Net')
            top_sell_tpex = df_tpex.nsmallest(10, 'Net')

            msg += "**📈 上櫃外資買超前十名**\n"
            for i, row in enumerate(top_buy_tpex.itertuples(), 1):
                msg += f"{i}. {row.Name} ({row.Code})：{int(row.Net):,} 張\n"
            
            msg += "\n**📉 上櫃外資賣超前十名**\n"
            for i, row in enumerate(top_sell_tpex.itertuples(), 1):
                msg += f"{i}. {row.Name} ({row.Code})：{int(row.Net):,} 張\n"
        else:
            msg += "⚠️ 查無今日上櫃資料\n"
    except Exception as e:
        msg += f"⚠️ 上櫃資料抓取失敗 ({e})\n"

    return msg

if __name__ == "__main__":
    if not TOKEN:
        print("請確認已設置 DISCORD_TOKEN 環境變數！")
    else:
        bot.run(TOKEN)
