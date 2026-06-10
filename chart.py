import io
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def generate_chart(hist: pd.DataFrame, code: str, name: str, latest_price: float) -> io.BytesIO:
    df = hist.tail(60).copy()

    mc = mpf.make_marketcolors(
        up="#FF3B30",
        down="#30D158",
        edge={"up": "#FF3B30", "down": "#30D158"},
        wick={"up": "#FF3B30", "down": "#30D158"},
        volume={"up": "#FF3B3088", "down": "#30D15888"},
    )
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mc,
        facecolor="#1C1C1E",
        figcolor="#1C1C1E",
        gridcolor="#2C2C2E",
        gridstyle="--",
        gridaxis="both",
        y_on_right=True,
        rc={
            "axes.labelcolor": "#EBEBF5",
            "xtick.color": "#EBEBF599",
            "ytick.color": "#EBEBF599",
            "axes.edgecolor": "#3A3A3C",
        },
    )

    addplots = []
    if not df["MA5"].isna().all():
        addplots.append(mpf.make_addplot(df["MA5"], color="#FFD60A", width=1.2, label="MA5"))
    if not df["MA20"].isna().all():
        addplots.append(mpf.make_addplot(df["MA20"], color="#FF9F0A", width=1.5, label="MA20"))
    if not df["MA60"].isna().all():
        addplots.append(mpf.make_addplot(df["MA60"], color="#64D2FF", width=1.8, label="MA60"))

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        addplot=addplots,
        volume=True,
        figsize=(13, 8),
        title=f"\n{name}  ({code})  Latest: {latest_price:.2f}",
        returnfig=True,
        datetime_format="%m/%d",
        xrotation=0,
        tight_layout=True,
    )

    axes[0].title.set_color("#EBEBF5")
    axes[0].title.set_fontsize(13)

    legend_patches = [
        mpatches.Patch(color="#FFD60A", label="MA5"),
        mpatches.Patch(color="#FF9F0A", label="MA20"),
        mpatches.Patch(color="#64D2FF", label="MA60"),
    ]
    axes[0].legend(
        handles=legend_patches,
        loc="upper left",
        framealpha=0.3,
        facecolor="#2C2C2E",
        edgecolor="#3A3A3C",
        labelcolor="#EBEBF5",
        fontsize=9,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="#1C1C1E")
    buf.seek(0)
    plt.close(fig)

    return buf
