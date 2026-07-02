import discord
from discord.ext import commands
import logging
import sys

from config import Config
from stock_data import get_stock_data, find_code_by_name
from chart import generate_chart
from trade_view import build_trade_view
from market_data import get_special_market_data, is_special_market_query
from realtime_quote import patch_realtime_quote


# ────────────────────────────────────────────
# 股票名稱顯示：優先使用 twstock 中文名
# ────────────────────────────────────────────

def _plain_code(code: object) -> str:
    raw = str(code or "").upper().strip()
    return raw.replace(".TW", "").replace(".TWO", "")


def _resolve_chinese_name(data: dict, fallback_code: str = "") -> str:
    """UI 顯示優先用中文公司名稱；抓不到才回退 data['name']。"""
    code = _plain_code(data.get("code") or fallback_code)

    try:
        import twstock  # type: ignore
        stock = twstock.codes.get(code)
        name = getattr(stock, "name", None)
        if name:
            return str(name)
    except Exception:
        pass

    name = str(data.get("name") or "").strip()
    return name or code or "未知股票"


# ────────────────────────────────────────────
# Embed 組裝
# ────────────────────────────────────────────

def _footer_text(trade: dict, tf_label: str) -> str:
    meta = str(trade.get("footer_meta") or "").strip()
    if meta:
        return f"Yahoo Finance｜Trader Camp Intelligence｜非投資建議｜{tf_label}｜{meta}"
    return f"Yahoo Finance｜Trader Camp Intelligence｜非投資建議｜{tf_label}"


def _build_embed(data: dict, trade: dict, has_chart: bool = True, detail: bool = False, tf_label: str = "日K") -> discord.Embed:
    display_name = data.get("display_name") or _resolve_chinese_name(data)
    embed = discord.Embed(
        title=f"{trade['title_icon']} {display_name} {data['code']}｜{trade['status']}",
        description=(
            f"💰 **{trade['price_line']}**\n"
            f"趨勢：**{trade['trend_rating']}**｜買點：**{trade['entry_rating']}**｜階段：**{trade.get('operation_stage', '等待')}**"
        ),
        color=trade["color"],
    )

    embed.add_field(name="🎯 一句話", value=trade["headline"], inline=False)
    embed.add_field(name="🧩 劇本", value=trade["scenario"], inline=False)
    embed.add_field(name="📍 位置", value=trade["position"], inline=False)
    embed.add_field(name="🚦 計畫", value=trade["trade_plan"], inline=False)
    embed.add_field(name="📊 補充", value=trade["extra"], inline=False)

    if detail:
        detail_text = str(trade.get("detail") or "暫無額外細節").strip()
        # Discord field value 1024 字限制；先截短，避免爆掉。
        if len(detail_text) > 1000:
            detail_text = detail_text[:997] + "..."
        embed.add_field(name="🔎 詳細判斷", value=detail_text, inline=False)

    if has_chart:
        embed.set_image(url="attachment://chart.png")
    embed.set_footer(text=_footer_text(trade, tf_label if has_chart else "文字卡"))
    return embed


# ────────────────────────────────────────────
# K 線切換 + 詳細/精簡 View
# ────────────────────────────────────────────

class ChartView(discord.ui.View):
    TF_LABEL = {"1d": "日K", "60m": "60分K", "5m": "5分K"}

    def __init__(self, data: dict, trade: dict, has_chart: bool = True):
        super().__init__(timeout=300)
        self.data = data
        self.trade = trade
        self.has_chart = has_chart
        self.current_tf = "1d"
        self.detail = False
        self._refresh_buttons()

    def _refresh_buttons(self):
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if child.custom_id in self.TF_LABEL:
                is_current = child.custom_id == self.current_tf
                child.disabled = is_current or not self.has_chart
                child.style = discord.ButtonStyle.primary if is_current else discord.ButtonStyle.secondary
            elif child.custom_id == "toggle_detail":
                child.label = "精簡" if self.detail else "詳細"
                child.style = discord.ButtonStyle.success if self.detail else discord.ButtonStyle.secondary

    @discord.ui.button(label="日K", custom_id="1d")
    async def btn_daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, "1d")

    @discord.ui.button(label="60分K", custom_id="60m")
    async def btn_60m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, "60m")

    @discord.ui.button(label="5分K", custom_id="5m")
    async def btn_5m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._switch(interaction, "5m")

    @discord.ui.button(label="詳細", custom_id="toggle_detail")
    async def btn_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.detail = not self.detail
        self._refresh_buttons()
        embed = _build_embed(
            self.data,
            self.trade,
            has_chart=self.has_chart,
            detail=self.detail,
            tf_label=self.TF_LABEL.get(self.current_tf, "日K"),
        )
        await interaction.message.edit(embed=embed, view=self)

    async def _switch(self, interaction: discord.Interaction, tf_key: str):
        tf_data = (self.data.get("tf") or {}).get(tf_key)
        if tf_data is None:
            await interaction.response.send_message(f"❌ {self.TF_LABEL[tf_key]} 資料不足", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            chart_buf = generate_chart(
                tf_data["hist"],
                self.data["code"],
                self.data.get("display_name") or self.data.get("name"),
                tf_data["price"],
            )
        except Exception:
            await interaction.followup.send("⚠️ 圖表產生失敗", ephemeral=True)
            return

        self.current_tf = tf_key
        self.has_chart = True
        self._refresh_buttons()
        embed = _build_embed(
            self.data,
            self.trade,
            has_chart=True,
            detail=self.detail,
            tf_label=self.TF_LABEL[tf_key],
        )
        await interaction.message.edit(
            embed=embed,
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
    query = (code or "").strip()

    if not query:
        await ctx.send("請輸入股票代號、公司名稱或大盤項目，例如：`/K2330`、`/K台積電`、`/K加權`")
        return

    async with ctx.typing():
        if is_special_market_query(query):
            data = get_special_market_data(query)
            if data is None:
                await ctx.send(f"❌ `{query}` 資料暫時無法取得，請稍後再試")
                return
            code = str(data.get("code") or query)
        else:
            if not query.isdigit():
                resolved = find_code_by_name(query)
                if resolved is None:
                    await ctx.send(f"❌ 找不到「{query}」，請確認公司名稱或股票代號")
                    return
                code = resolved
            else:
                code = query.upper()

            data = get_stock_data(code)
            if data is None:
                await ctx.send(f"❌ 查無股票代號 `{code}`，請確認代號是否正確")
                return

            data["display_name"] = _resolve_chinese_name(data, code)
            data = patch_realtime_quote(data, code)

        data["display_name"] = data.get("display_name") or _resolve_chinese_name(data, code)

        chart_buf = None
        chart_ok = False
        try:
            hist = data.get("hist")
            if hist is not None and not getattr(hist, "empty", True):
                chart_buf = generate_chart(hist, data["code"], data["display_name"], data["price"])
                chart_ok = True
        except Exception as e:
            logger.warning("圖表產生失敗，改送文字卡: %s", e)

        trade = build_trade_view(data)
        embed = _build_embed(data, trade, has_chart=chart_ok, detail=False, tf_label="日K")

    view = ChartView(data, trade, has_chart=chart_ok)
    if chart_ok and chart_buf is not None:
        await ctx.send(embed=embed, file=discord.File(chart_buf, filename="chart.png"), view=view)
    else:
        await ctx.send(embed=embed, view=view)


# ────────────────────────────────────────────
# 新指令：/K<股票代號或公司名稱>
# ────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = (message.content or "").strip()
    lower = content.lower()

    # 支援：/K2330、/K 2330、/k台積電、/k 台積電、/K小台
    if lower.startswith("/k"):
        query = content[2:].strip()
        if not query:
            await message.channel.send("請輸入股票代號、公司名稱或大盤項目，例如：`/K2330`、`/K台積電`、`/K小台`")
            return
        ctx = await bot.get_context(message)
        await handle_stock_query(ctx, query)
        return

    await bot.process_commands(message)


# ────────────────────────────────────────────
# 舊指令保留
# ────────────────────────────────────────────

@bot.command(name="股")
async def cmd_stock(ctx: commands.Context, code: str = None):
    if not code:
        await ctx.send("請輸入股票代號、公司名稱或大盤項目，例如：`/K2330`、`/K台積電`、`/K加權`")
        return
    await handle_stock_query(ctx, code)


@bot.command(name="查")
async def cmd_query(ctx: commands.Context, code: str = None):
    if not code:
        await ctx.send("請輸入股票代號、公司名稱或大盤項目，例如：`/K2330`、`/K台積電`、`/K加權`")
        return
    await handle_stock_query(ctx, code)


@bot.command(name="k")
async def cmd_kline(ctx: commands.Context, code: str = None):
    if not code:
        await ctx.send("請輸入股票代號、公司名稱或大盤項目，例如：`/K2330`、`/K台積電`、`/K加權`")
        return
    await handle_stock_query(ctx, code)


@bot.command(name="help")
async def cmd_help(ctx: commands.Context):
    embed = discord.Embed(
        title="📖 台股查詢指令",
        description="Trader Camp Intelligence — 台股波段決策卡片",
        color=0x64D2FF,
    )
    embed.add_field(
        name="🔍 查詢指令",
        value=(
            "`/K2330` — 用股票代號查詢\n"
            "`/K台積電` — 用公司名稱查詢\n"
            "`/K加權`、`/K櫃買`、`/K小台` — 查詢大盤項目"
        ),
        inline=False,
    )
    embed.add_field(
        name="📌 顯示內容",
        value="一句話｜劇本｜位置｜計畫｜補充；按鈕可切換日K、60分K、5分K與詳細模式。",
        inline=False,
    )
    embed.add_field(
        name="🎯 評級說明",
        value="趨勢評級看強弱；買點評級看位置；階段顯示等待、試單、加碼、持有、防守或失效。",
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
