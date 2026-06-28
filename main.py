import discord
from discord.ext import commands
import logging
import sys

from config import Config
from stock_data import get_stock_data, find_code_by_name
from chart import generate_chart
from trade_view import build_trade_view


# ────────────────────────────────────────────
# K 線切換 View
# ────────────────────────────────────────────

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
                child.style = (
                    discord.ButtonStyle.primary if is_current
                    else discord.ButtonStyle.secondary
                )

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
            text=(
                f"資料來源：Yahoo Finance｜Trader Camp Intelligence｜"
                f"非投資建議｜{self.TF_LABEL[tf_key]}"
            )
        )
        self.embed.set_image(url="attachment://chart.png")
        await interaction.message.edit(
            embed=self.embed,
            attachments=[discord.File(chart_buf, filename="chart.png")],
            view=self,
        )


# ────────────────────────────────────────────
# Bot 設定
# ────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents, help_command=None)


# ────────────────────────────────────────────
# 核心查詢
# ────────────────────────────────────────────

async def handle_stock_query(ctx: commands.Context, code: str) -> None:
    query = code.strip()

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

        trade = build_trade_view(data)
        embed = _build_embed(data, trade)

    view = ChartView(data, embed)
    await ctx.send(embed=embed, file=discord.File(chart_buf, filename="chart.png"), view=view)


def _build_embed(data: dict, trade: dict) -> discord.Embed:
    embed = discord.Embed(
        title=(
            f"{trade['title_icon']} {data['name']} {data['code']}"
            f"｜{trade['status']}"
        ),
        description=(
            f"現價：{trade['price_line']}\n"
            f"評級：**{trade['rating']}**｜{trade['tagline']}"
        ),
        color=trade["color"],
    )
    embed.add_field(name="🎯 結論",    value=trade["conclusion"],  inline=False)
    embed.add_field(name="🧩 劇本",    value=trade["scenario"],    inline=False)
    embed.add_field(name="🧭 週期",    value=trade["cycles"],      inline=False)
    embed.add_field(name="📐 關鍵價",  value=trade["key_levels"],  inline=False)
    embed.add_field(name="📊 量價",    value=trade["volume"],      inline=False)
    embed.add_field(name="🚦 交易計畫", value=trade["trade_plan"],  inline=False)
    embed.add_field(name="📋 總結",    value=trade["summary"],     inline=False)
    embed.set_image(url="attachment://chart.png")
    embed.set_footer(
        text="資料來源：Yahoo Finance｜Trader Camp Intelligence｜非投資建議｜日K"
    )
    return embed


# ────────────────────────────────────────────
# 指令
# ────────────────────────────────────────────

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
            "`!股 2330` — 查詢股票\n"
            "`!查 2330` — 查詢股票\n"
            "`!k 2330`  — 產生 K 線圖\n"
            "`!help`    — 顯示此說明"
        ),
        inline=False,
    )
    embed.add_field(
        name="📌 支援格式",
        value="股票代號（如 `2330`）或公司名稱（如 `台積電`）",
        inline=False,
    )
    embed.add_field(
        name="🎯 評級說明",
        value="A 可做　B/B- 等修復/觀察　C 觀望/反彈觀察　D 避開",
        inline=False,
    )
    embed.add_field(
        name="📐 技術指標",
        value="🟡 MA5 短期　🟠 MA20 中期　🔵 MA60 長期\n🔴 紅K上漲　🟢 綠K下跌（台股慣例）",
        inline=False,
    )
    embed.set_footer(text="Trader Camp Intelligence Bot｜非投資建議")
    await ctx.send(embed=embed)


# ────────────────────────────────────────────
# 事件
# ────────────────────────────────────────────

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
