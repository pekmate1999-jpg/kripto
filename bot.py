#!/usr/bin/env python3
"""
Crypto Portfolio Telegram Reporter v2.1
Küld egy formázott üzenetet a Telegram boton keresztül a CoinGecko API-ból lekérdezett
kriptovaluta árak alapján, és kijelzi a portfólió értékének változását az előző futás óta.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

# ----------------------------- KONFIGURÁCIÓ ---------------------------------

# Alapértelmezett JSON fájlok nevei
DEFAULT_PORTFOLIO_FILE = "portfolio.json"
HISTORY_FILE = "history.json"

# Környezeti változók (GitHub Secrets vagy lokális .env)
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# Logolás beállítása
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Coin nevek szépítése (display name)
COIN_NAMES: Dict[str, str] = {
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
    "solana": "Solana",
    "binancecoin": "Binance Coin",
    "cardano": "Cardano",
    "ripple": "XRP",
    "dogecoin": "Dogecoin",
    "polkadot": "Polkadot",
    "pi-network": "Pi Network",
    # További coinok hozzáadhatók
}


# ----------------------------- SAJÁT KIVÉTEL ---------------------------------
class CryptoReporterError(Exception):
    """Általános kivétel a Crypto Reporter számára."""
    pass


# ----------------------------- ADATKEZELÉS ---------------------------------
def load_portfolio(file_path: str = DEFAULT_PORTFOLIO_FILE) -> Dict[str, float]:
    if not os.path.exists(file_path):
        raise CryptoReporterError(
            f"A portfólió fájl nem található: {file_path}. "
            "Hozz létre egy 'portfolio.json' fájlt."
        )
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
        for coin, amount in portfolio.items():
            if not isinstance(amount, (int, float)):
                raise CryptoReporterError(f"'{coin}' mennyisége nem szám: {amount}")
        return portfolio
    except json.JSONDecodeError as e:
        raise CryptoReporterError(f"JSON hiba a {file_path} fájlban: {e}")

def load_history(file_path: str = HISTORY_FILE) -> Dict[str, Optional[float]]:
    """Betölti az előző futás portfólió összértékét."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Nem sikerült betölteni a history fájlt: {e}")
    return {"previous_usd": None, "previous_huf": None}

def save_history(usd: float, huf: float, file_path: str = HISTORY_FILE) -> None:
    """Elmenti a jelenlegi portfólió összértéket a következő futáshoz."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"previous_usd": usd, "previous_huf": huf}, f)
        logger.info("Későbbi összehasonlításhoz az aktuális értékek elmentve (history.json).")
    except Exception as e:
        logger.error(f"Nem sikerült elmenteni a history fájlt: {e}")


# ----------------------------- API & FORMÁZÁS ---------------------------------
def get_prices(coin_ids: List[str]) -> Dict[str, Dict]:
    ids_param = ",".join(coin_ids)
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids_param}&vs_currencies=usd,huf&include_24hr_change=true"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        missing = [c for c in coin_ids if c not in data]
        if missing:
            logger.warning(f"A következő coinok nem találhatók az API válaszában: {missing}")
        return data
    except requests.exceptions.RequestException as e:
        raise CryptoReporterError(f"CoinGecko API hiba: {e}")

def format_usd(value: float) -> str:
    return f"${value:,.2f}"

def format_huf(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " Ft"

def format_change(change_24h: Optional[float]) -> Tuple[str, str, str]:
    if change_24h is None:
        return "⚪", "❓", "n/a"
    if change_24h >= 0:
        return "🟢", "📈", f"+{change_24h:.2f}%"
    else:
        return "🔴", "📉", f"{change_24h:.2f}%"

def format_diff_usd(diff: float, prev: float) -> str:
    """Megformázza az USD különbséget és a százalékot (+/- jelekkel)."""
    pct_str = ""
    if prev and prev > 0:
        pct = (diff / prev) * 100
        pct_str = f" ({pct:+.2f}%)"
        
    if diff >= 0:
        return f"📈 +${diff:,.2f}{pct_str}"
    else:
        return f"📉 -${abs(diff):,.2f}{pct_str}"

def format_diff_huf(diff: float, prev: float) -> str:
    """Megformázza a HUF különbséget és a százalékot (+/- jelekkel)."""
    pct_str = ""
    if prev and prev > 0:
        pct = (diff / prev) * 100
        pct_str = f" ({pct:+.2f}%)"
        
    formatted_val = f"{abs(diff):,.0f}".replace(",", " ")
    if diff >= 0:
        return f"📈 +{formatted_val} Ft{pct_str}"
    else:
        return f"📉 -{formatted_val} Ft{pct_str}"

# ----------------------------- ÜZENET ÉPÍTÉS ---------------------------------
def build_message(portfolio: Dict[str, float], prices: Dict[str, Dict], history: Dict[str, Optional[float]]) -> Tuple[str, float, float]:
    """Összeállítja az üzenetet és visszatér a szöveggel, valamint az új összértékekkel."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "🚀 <b>NAPI CRYPTO JELENTÉS</b>",
        f"🕒 <i>{now}</i>",
        "",
    ]

    total_usd = 0.0
    total_huf = 0.0

    for coin, amount in portfolio.items():
        display_name = COIN_NAMES.get(coin, coin.replace("_", " ").title())

        if coin not in prices:
            lines.append(f"⚠️ <b>{display_name}</b> – ár nem elérhető\n")
            continue

        price_data = prices[coin]
        price_usd = price_data.get("usd", 0.0)
        price_huf = price_data.get("huf", 0.0)
        change_24h = price_data.get("usd_24h_change")

        value_usd = price_usd * amount
        value_huf = price_huf * amount
        total_usd += value_usd
        total_huf += value_huf

        color_dot, trend, change_str = format_change(change_24h)

        lines.append(f"🪙 <b>Kriptovaluta:</b> {display_name}")
        lines.append(f"💰 <b>Ár:</b> {color_dot} {format_usd(price_usd)}  |  {format_huf(price_huf)}")
        lines.append(f"⚖️ <b>Mennyiség:</b> {amount:g}")
        lines.append(f"💵 <b>Érték:</b> {color_dot} {format_usd(value_usd)}  |  {format_huf(value_huf)}")
        lines.append(f"📊 <b>24h változás:</b> {trend} {change_str}")
        lines.append("")

    # --- Összesítő szekció és Változás kiszámítása ---
    prev_usd = history.get("previous_usd")
    prev_huf = history.get("previous_huf")

    lines.append("💼 <b>PORTFÓLIÓ ÖSSZÉRTÉK</b>")
    
    # USD Kiírás
    lines.append(f"🇺🇸 <b>USD:</b> {format_usd(total_usd)}")
    if prev_usd is not None:
        diff_usd = total_usd - prev_usd
        lines.append(f"   ↳ <i>Változás legutóbb óta: {format_diff_usd(diff_usd, prev_usd)}</i>")
    
    # HUF Kiírás
    lines.append(f"🇭🇺 <b>HUF:</b> {format_huf(total_huf)}")
    if prev_huf is not None:
        diff_huf = total_huf - prev_huf
        lines.append(f"   ↳ <i>Változás legutóbb óta: {format_diff_huf(diff_huf, prev_huf)}</i>")

    lines.append("")
    lines.append("🔗 <i>Adatok forrása: <a href='https://www.coingecko.com/'>CoinGecko</a></i>")

    return "\n".join(lines), total_usd, total_huf


# ----------------------------- TELEGRAM KÜLDÉS ---------------------------------
def send_telegram_msg(text: str) -> None:
    if len(text) > 4000:
        logger.warning("Az üzenet megközelíti a Telegram 4096 karakteres limitjét.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise CryptoReporterError(f"Telegram üzenet küldés sikertelen: {e}")


# ----------------------------- MAIN ---------------------------------
def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TOKEN":
        raise CryptoReporterError("A TELEGRAM_TOKEN nincs beállítva vagy helytelen.")
    if not CHAT_ID or CHAT_ID == "YOUR_CHAT_ID":
        raise CryptoReporterError("A CHAT_ID nincs beállítva vagy helytelen.")

    # 1. Adatok betöltése
    portfolio = load_portfolio()
    history = load_history()
    logger.info(f"Portfólió betöltve: {len(portfolio)} coin")

    # 2. Árak lekérése
    coin_ids = list(portfolio.keys())
    prices = get_prices(coin_ids)
    logger.info(f"Árak lekérve {len(prices)} coinról")

    # 3. Üzenet építése és változók számolása
    message, new_total_usd, new_total_huf = build_message(portfolio, prices, history)

    # 4. Üzenet küldése
    send_telegram_msg(message)
    logger.info("Üzenet sikeresen elküldve")

    # 5. Új állapot mentése
    save_history(new_total_usd, new_total_huf)
    
    # Konzol kimenet ellenőrzéshez
    print(message)


if __name__ == "__main__":
    try:
        main()
    except CryptoReporterError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Váratlan hiba: {e}")
        sys.exit(1)
