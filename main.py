import discord
from discord.ext import commands
import logging
import sys
from config import Config
from stock_data import get_stock_data, get_trend, get_mtf_ma_analysis, get_detailed_reading, get_mtf_summary, find_code_by_name
from chart import generate_chart


class ChartView(discord.ui.View):
    TF_LABEL = {"1d": "日K", "60m": "60分K", "5m": "5分K"}

    def __init__(self, data: dict, embed: discord.Embed):
        super().__init__(timeout=300)
        self.data = data
        self.embed = embed
        self.current_tf = "1d"
        self._refresh_buttons()

    def _refresh_buttons(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                is_current = child.custom_id == self.current_tf
                child.disabled = is_current
                child.style = discord.ButtonStyle.primary if is_current else discord.ButtonStyle.secondary

    @discord.ui.button(label="日K", custom_id="1d")
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, "1d")

    @discord.ui.button(label="60分K", custom_id="60m")
    async def btn_60m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, "60m")

    @discord.ui.button(label="5分K", custom_id="5m")
    async def btn_5m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, "5m")

    async def _switch(self, interaction: discord.Interaction, tf_key: str):
        tf_data = self.data["tf"].get(tf_key)
        if tf_data is None:
            await interaction.response.send_message(
                f"❌ {self.TF_LABEL[tf_key]} 資料不足", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            chart_buf = generate_chart(
                tf_data["hist"], self.data["code"],
                self.data["name"], tf_data["price"],
            )
        except Exception:
            await interaction.followup.send("⚠️ 圖表產生失敗", ephemeral=True)
            return

        self.current_tf = tf_key
        self._refresh_buttons()
        self.embed.set_footer(
            text=f"資料來源：Yahoo Finance　|　Trader Camp Intelligence　|　{self.TF_LABEL[tf_key]}"
        )
        self.embed.set_image(url="attachment://chart.png")

        await interaction.message.edit(
            embed=self.embed,
            attachments=[discord.File(chart_buf, filename="chart.png")],
            view=self,
        )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents, help_command=None)


async def handle_stock_query(ctx: commands.Context, code: str) -> None:
    query = code.strip()

    # 若輸入非純數字，嘗試用公司名稱反查代號
    if not query.isdigit():
        resolved = find_code_by_name(query)
        if resolved is None:
            await ctx.send(f"❌ 找不到「{query}」，請確認公司名稱或股票代號")
            return
        code = resolved
    else:
        code = query.upper()

    async with ctx.typing():
        data = get_stock_data(code)
        if data is None:
            await ctx.send(f"❌ 查無股票代號 `{code}`，請確認代號是否正確")
            return

        try:
            chart_buf = generate_chart(data["hist"], data["code"], data["name"], data["price"])
        except Exception as e:
            logger.error("圖表產生失敗: %s", e)
            await ctx.send("⚠️ 資料源暫時無法取得，請稍後再試")
            return

    trend = get_trend(data["price"], data["ma5"], data["ma20"], data["ma60"])
    mtf_ma = get_mtf_ma_analysis(data["tf"])
    detailed = get_detailed_reading(data["change_pct"], data["price"], data["ma5"], data["ma20"], data["ma60"], data["volume"], data["avg_volume"])
    summary = get_mtf_summary(data["tf"], data["price"], data["ma5"], data["ma20"], data["ma60"], data["change_pct"])

    is_up = data["change"] >= 0
    color = 0xFF3B30 if is_up else 0x30D158
    arrow = "▲" if is_up else "▼"
    sign = "+" if is_up else ""

    embed = discord.Embed(
        title=f"{'🔴' if is_up else '🟢'} {data['name']}　({data['code']})",
        color=color,
    )
    embed.add_field(
        name="💰 最新價格",
        value=f"**`{data['price']:.2f}`**　{arrow} {sign}{data['change']:.2f}　（{sign}{data['change_pct']:.2f}%）",
        inline=False,
    )
    embed.add_field(name="📈 今日最高", value=f"`{data['high']:.2f}`", inline=True)
    embed.add_field(name="📉 今日最低", value=f"`{data['low']:.2f}`", inline=True)
    embed.add_field(name="📊 成交量", value=f"`{data['volume']:,}`", inline=True)
    embed.add_field(name="🟡 MA5", value=f"`{data['ma5']:.2f}`", inline=True)
    embed.add_field(name="🟠 MA20", value=f"`{data['ma20']:.2f}`", inline=True)
    embed.add_field(
        name="🔵 MA60",
        value=f"`{data['ma60']:.2f}`" if data["ma60"] else "`資料不足`",
        inline=True,
    )
    embed.add_field(name="🧭 趨勢", value=f"**{trend}**", inline=False)
    embed.add_field(name="📐 各週期均線關係", value=mtf_ma, inline=False)
    embed.add_field(name="💬 詳細判讀", value=detailed, inline=False)
    embed.add_field(name="📋 收斂總結", value=summary, inline=False)
    embed.set_image(url="attachment://chart.png")
    embed.set_footer(text="資料來源：Yahoo Finance　|　Trader Camp Intelligence　|　日K")

    view = ChartView(data, embed)
    await ctx.send(embed=embed, file=discord.File(chart_buf, filename="chart.png"), view=view)


@bot.command(name="股")
async def cmd_stock(ctx: commands.Context, code: str = None):
    if not code:
        await ctx.send("請輸入股票代號，例如：`!股 2330`")
        return
    await handle_stock_query(ctx, code)


@bot.command(name="查")
async def cmd_query(ctx: commands.Context, code: str = None):
    if not code:
        await ctx.send("請輸入股票代號，例如：`!查 2330`")
        return
    await handle_stock_query(ctx, code)


@bot.command(name="k")
async def cmd_kline(ctx: commands.Context, code: str = None):
    if not code:
        await ctx.send("請輸入股票代號，例如：`!k 2330`")
        return
    await handle_stock_query(ctx, code)


@bot.command(name="help")
async def cmd_help(ctx: commands.Context):
    embed = discord.Embed(
        title="📖 台股查詢指令",
        description="Trader Camp Intelligence — 凱衛風格台股查詢機器人",
        color=0x64D2FF,
    )
    embed.add_field(
        name="🔍 查詢指令",
        value=(
            "`!股 2330` — 查詢台積電\n"
            "`!查 2330` — 查詢台積電\n"
            "`!k 2330` — 產生 K 線圖\n"
            "`!help` — 顯示此說明"
        ),
        inline=False,
    )
    embed.add_field(
        name="📌 常用代號",
        value="`2330` 台積電　`0050` 元大台灣50\n`2317` 鴻海　`2454` 聯發科　`2382` 廣達",
        inline=False,
    )
    embed.add_field(
        name="📐 技術指標說明",
        value="🟡 MA5 短期　🟠 MA20 中期　🔵 MA60 長期\n🔴 紅K上漲　🟢 綠K下跌（台股慣例）",
        inline=False,
    )
    embed.set_footer(text="Trader Camp Intelligence Bot")
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    logger.info("Bot 已啟動: %s", bot.user)
    logger.info("已加入 %d 個伺服器", len(bot.guilds))


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error("指令錯誤: %s", error)


if __name__ == "__main__":
    Config.validate()
    bot.run(Config.DISCORD_TOKEN)
