import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import datetime
import requests
from bs4 import BeautifulSoup

# 載入 .env 變數
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')

intents = discord.Intents.default()
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

@bot.command(name='籌碼', help='手動查詢最新外資買賣超前十名')
async def manual_report(ctx):
    await ctx.send("🔄 正在從富邦 MoneyDJ 抓取最新外資買賣超資料，請稍候...")
    try:
        report_message = fetch_fubon_moneydj_data()
        await ctx.send(report_message)
    except Exception as e:
        await ctx.send(f"⚠️ 抓取資料時發生錯誤：{e}")

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
            report_message = fetch_fubon_moneydj_data()
            await channel.send(report_message)
        except Exception as e:
            await channel.send(f"⚠️ 抓取資料時發生錯誤：{e}")

def fetch_fubon_moneydj_data():
    twse_url = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A=D&B=0&C=1"
    tpex_url = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A=D&B=1&C=1"
    
    # 加上偽裝瀏覽器的標頭，避免被當作機器人阻擋
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }
    
    msg = f"📊 **【外資買賣超前十檔統整】**\n*(資料來源：富邦/MoneyDJ)*\n\n"
    
    for market, url in [("上市", twse_url), ("上櫃", tpex_url)]:
        try:
            res = requests.get(url, headers=headers)
            # MoneyDJ 的網頁編碼通常是 Big5
            res.encoding = 'big5'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 嘗試抓取網頁上的「資料日期」
            date_text = ""
            for div in soup.find_all('div'):
                if div.text and '資料日期' in div.text:
                    date_text = div.text.strip().replace('資料日期：', '')
                    break
            
            msg += f"📅 **{market}資料日期：{date_text}**\n"
            
            buy_list = []
            sell_list = []
            
            # 尋找所有表格行 (tr)
            rows = soup.find_all('tr')
            for row in rows:
                # 取出該行所有的儲存格 (td)
                cols = [td.text.strip() for td in row.find_all('td')]
                
                # 富邦資料表的特徵：長度 >= 6，且第一欄為數字(名次)
                # 欄位對應：[0]名次, [1]股票(買超), [2]買超張數, [3]名次, [4]股票(賣超), [5]賣超張數
                if len(cols) >= 6 and cols[0].isdigit():
                    if len(buy_list) < 10:
                        buy_list.append(f"{cols[0]}. {cols[1]}：{cols[2]} 張")
                    
                    if cols[3].isdigit() and len(sell_list) < 10:
                        sell_list.append(f"{cols[3]}. {cols[4]}：{cols[5]} 張")
                        
                # 抓滿十名就提早結束迴圈
                if len(buy_list) >= 10 and len(sell_list) >= 10:
                    break
                    
            msg += f"**📈 {market}外資買超前十名**\n" + "\n".join(buy_list) + "\n\n"
            msg += f"**📉 {market}外資賣超前十名**\n" + "\n".join(sell_list) + "\n"
            msg += "\n-----------------------\n\n"
            
        except Exception as e:
            msg += f"⚠️ {market}資料抓取失敗 ({e})\n\n"
            
    return msg

if __name__ == "__main__":
    if not TOKEN:
        print("請確認已設置 DISCORD_TOKEN 環境變數！")
    else:
        bot.run(TOKEN)
