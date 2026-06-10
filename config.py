import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    COMMAND_PREFIX: str = "!"
    CHART_DAYS: int = 60

    @classmethod
    def validate(cls) -> None:
        if not cls.DISCORD_TOKEN:
            raise ValueError("缺少必要環境變數: DISCORD_TOKEN")
