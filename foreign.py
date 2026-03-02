import discord
from discord.ext import commands, tasks
import yfinance as yf
import datetime
import asyncio
import requests
from bs4 import BeautifulSoup
import re
import logging
import os
from dotenv import load_dotenv

# 載入 .env 檔案 (在 Railway 上執行時，這行不會報錯，會自動去抓 Railway 後台的變數)
load_dotenv()

# 關閉 yfinance 煩人的警告訊息
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

# ================= 設定區 =================
# 1. 透過環境變數安全讀取 Token (請在 .env 或 Railway 後台設定 DISCORD_TOKEN)
TOKEN = os.getenv('DISCORD_TOKEN')

# 安全機制：如果抓不到 Token，直接停止執行並報錯
if not TOKEN:
    raise ValueError("❌ 找不到 DISCORD_TOKEN！請確認 .env 檔案或 Railway 環境變數是否已設定。")

# 2. 請貼上你要發送訊息的 Discord 頻道 ID
TARGET_CHANNEL_ID = 1478050181126688870

# 3. 自動播報時間設定 (外資數據通常下午出來，建議設定 18:00 之後)
REPORT_TIME = "20:00"

# ✅ 建立台灣專屬時區 (UTC+8)
tw_tz = datetime.timezone(datetime.timedelta(hours=8))
# =========================================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8'
}

# ================= 終極 Discord 完美對齊工具 =================
def to_full_width(text):
    """將半形英數字轉換為全形，確保在 Discord 中絕對對齊"""
    res = ""
    for c in text:
        if 33 <= ord(c) <= 126:
            res += chr(ord(c) + 65248) # 將 ASCII 轉為全形
        elif c == ' ':
            res += '　' # 空白轉為全形空白
        else:
            res += c
    return res

def format_stock_name(name, length=6):
    """名稱轉全形並固定長度為 6，不足補全形空白"""
    fw_name = to_full_width(name)[:length]
    return fw_name + '　' * (length - len(fw_name))
# =======================================================

def fetch_foreign_data():
    """使用富邦證券(MoneyDJ)的雙軌抓取引擎"""
    ANSI_RED = "\u001b[0;31m"    
    ANSI_GREEN = "\u001b[0;32m"  
    ANSI_YELLOW = "\u001b[0;33m" 
    ANSI_WHITE = "\u001b[0;37m"  
    ANSI_RESET = "\u001b[0m"

    print("開始從富邦證券掃描外資買賣超排行榜...")
    url = "https://fubon-ebrokerdj.fbs.com.tw/Z/ZG/ZGK_D.djhtm"
    
    top_buy = []
    top_sell = []
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = 'big5' # ✨ 解決富邦亂碼的魔法設定
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 10:
                text1 = tds[0].text.strip()
                if text1.isdigit():
                    
                    # --- 處理左半邊：買超 ---
                    if len(top_buy) < 12:
                        buy_name_full = tds[1].text.strip()
                        buy_vol = tds[2].text.strip().replace(',', '')
                        buy_match = re.match(r'^([A-Z0-9]+)(.*)$', buy_name_full)
                        if buy_match:
                            top_buy.append({
                                'ticker': buy_match.group(1),
                                'name': buy_match.group(2).strip(),
                                'net_vol': buy_vol
                            })
                            
                    # --- 處理右半邊：賣超 ---
                    if len(top_sell) < 12:
                        sell_name_full = tds[6].text.strip() 
                        sell_vol = tds[7].text.strip().replace(',', '').replace('-', '') 
                        sell_match = re.match(r'^([A-Z0-9]+)(.*)$', sell_name_full)
                        if sell_match:
                            top_sell.append({
                                'ticker': sell_match.group(1),
                                'name': sell_match.group(2).strip(),
                                'net_vol': sell_vol
                            })
    except Exception as e:
        print(f"富邦網頁爬取失敗: {e}")

    all_targets = {"🔥 外資狂掃貨 (買超排行)": top_buy, "🧊 外資大逃殺 (賣超排行)": top_sell}
    results = {}

    for title, target_list in all_targets.items():
        block_content = "```ansi\n"
        for item in target_list:
            try:
                ticker_tw = f"{item['ticker']}.TW"
                df = yf.Ticker(ticker_tw).history(period="2d")
                if df.empty:
                    ticker_two = f"{item['ticker']}.TWO"
                    df = yf.Ticker(ticker_two).history(period="2d")
                
                if len(df) >= 2:
                    close = df['Close'].iloc[-1]
                    prev_close = df['Close'].iloc[-2]
                    chg_pct = ((close - prev_close) / prev_close) * 100
                    
                    if chg_pct > 0: color = ANSI_RED
                    elif chg_pct < 0: color = ANSI_GREEN
                    else: color = ANSI_WHITE
                    
                    # 1. 代號固定 6 格 (向左對齊，補半形空白)
                    str_ticker = item['ticker'].ljust(6)
                    
                    # 2. 名稱固定 6 格 (全部轉全形，補全形空白，無敵對齊法)
                    str_name = format_stock_name(item['name'], 6)
                    
                    # 3. 價格與漲跌幅固定長度 (向右對齊)
                    str_price = f"${close:.2f}".rjust(8)
                    str_pct = f"{chg_pct:+.2f}%".rjust(8)
                    
                    # 4. 張數把千分位逗號加回來，數字向右對齊後再補上"張"
                    str_vol = f"{int(item['net_vol']):,}".rjust(9) + "張"
                    
                    block_content += f"{str_ticker} {str_name} {str_price}  {color}{str_pct}{ANSI_RESET} | {ANSI_YELLOW}{str_vol}{ANSI_RESET}\n"
            except Exception:
                pass
        block_content += "```"
        results[title] = block_content

    data_date = datetime.datetime.now(tw_tz).strftime("%Y-%m-%d")
    return results, data_date

async def send_foreign_report(channel):
    msg = await channel.send("🕵️‍♂️ **正在啟動隱形雷達，潛入富邦證券抓取外資籌碼，請稍候...**")
    
    try:
        results, data_date = await asyncio.to_thread(fetch_foreign_data)
        
        embed = discord.Embed(
            title=f"🌐 台股外資主力買賣超雷達 | {data_date}",
            description="透過 AI 穿透富邦券商庫，追蹤外資今日最真實的籌碼佈局！",
            color=0x3498db
        )

        for title, content in results.items():
            if "```ansi\n```" not in content:
                embed.add_field(name=title, value=content, inline=False)

        embed.set_footer(text="數據來源：富邦證券/yfinance ｜ 紅色=上漲 ｜ 綠色=下跌")
        
        await msg.edit(content=None, embed=embed)
    except Exception as e:
        await msg.edit(content=f"❌ 抓取外資籌碼時發生錯誤：`{e}`")

@tasks.loop(minutes=1)
async def schedule_task():
    now = datetime.datetime.now(tw_tz).strftime("%H:%M")
    if now == REPORT_TIME and TARGET_CHANNEL_ID:
        ch = bot.get_channel(TARGET_CHANNEL_ID)
        if ch: 
            await send_foreign_report(ch)
        await asyncio.sleep(61) 

@bot.command()
async def foreign(ctx):
    await send_foreign_report(ctx.channel)

@bot.event
async def on_ready():
    print(f'🌐 治癒強迫症版引擎(富邦專武) {bot.user} 已上線！')
    if not schedule_task.is_running():
        schedule_task.start()


bot.run(TOKEN)
