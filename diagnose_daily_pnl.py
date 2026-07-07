"""
=============================================================
 DIAGNOSTIC P&L QUOTIDIEN — identifie précisément quels deals
 sont comptés ou exclus par _recover_daily_pnl(), et pourquoi.
 Ne modifie rien, lecture MT5 seule.
=============================================================
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")
MT5_PATH     = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe")
MAGIC_NUMBER = int(os.getenv("MAGIC_NUMBER", "20250226"))
TRADING_START_HOUR = int(os.getenv("TRADING_START_HOUR", "3"))


def get_trading_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=TRADING_START_HOUR, minute=0, second=0, microsecond=0)
    if now.hour < TRADING_START_HOUR:
        start = start - timedelta(days=1)
    return start


if not mt5.initialize(path=MT5_PATH, login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
    print(f"❌ Échec connexion MT5 : {mt5.last_error()}")
    sys.exit(1)

acc = mt5.account_info()
print(f"✅ Connecté — compte {acc.login} | Serveur MT5 : {MT5_SERVER}")

# Heure serveur MT5 actuelle (via le dernier tick disponible)
symbols_test = ["XAUUSDm", "XAUUSD"]
server_time = None
for s in symbols_test:
    tick = mt5.symbol_info_tick(s)
    if tick:
        server_time = datetime.fromtimestamp(tick.time, tz=timezone.utc)
        print(f" Heure serveur MT5 (via tick {s}) : {server_time} (equiv. UTC)")
        break

start_bot = get_trading_day_start()
now_utc = datetime.now(timezone.utc)
print(f"\n Fenêtre du bot ([TRADING_START_HOUR={TRADING_START_HOUR}h UTC]) :")
print(f"   {start_bot}  →  {now_utc}")

# On élargit la recherche à 48h pour capturer aussi les trades ouverts avant la fenêtre du bot
search_start = now_utc - timedelta(hours=48)
deals = mt5.history_deals_get(search_start, now_utc)

if deals is None:
    print("❌ Aucun deal trouvé ou erreur MT5:", mt5.last_error())
    sys.exit(1)

print(f"\n{len(deals)} deals trouvés sur les dernières 48h (tous symboles/magics confondus)\n")
print(f"{'Heure (UTC)':<20} {'Ticket':<12} {'Symbole':<10} {'Magic':<12} {'Comment':<15} {'Type':<8} {'Profit':>10}  Statut")
print("-" * 115)

total_bot_window = 0.0
total_all_magic_match = 0.0

for deal in sorted(deals, key=lambda d: d.time):
    dt = datetime.fromtimestamp(deal.time, tz=timezone.utc)
    entry_type = "OUT" if deal.entry == mt5.DEAL_ENTRY_OUT else ("IN" if deal.entry == mt5.DEAL_ENTRY_IN else "OTHER")

    if entry_type != "OUT":
        continue  # on ne s'intéresse qu'aux clôtures

    magic_match = (deal.magic == MAGIC_NUMBER)
    in_bot_window = (dt >= start_bot)

    if magic_match:
        total_all_magic_match += deal.profit
        if in_bot_window:
            total_bot_window += deal.profit

    reasons = []
    if not magic_match:
        reasons.append(f"magic≠{MAGIC_NUMBER} (magic réel={deal.magic})")
    if not in_bot_window:
        reasons.append(f"AVANT la fenêtre du bot ({TRADING_START_HOUR}h UTC)")
    statut = "✅ COMPTÉ" if (magic_match and in_bot_window) else f"❌ EXCLU — {' + '.join(reasons)}"

    print(f"{str(dt):<20} {deal.position_id:<12} {deal.symbol:<10} {deal.magic:<12} "
          f"{deal.comment:<15} {entry_type:<8} {deal.profit:>10.2f}  {statut}")

print("-" * 115)
print(f"\n TOTAL compté par le bot (magic OK + dans la fenêtre)      : {total_bot_window:+.2f}$")
print(f" TOTAL magic OK mais SANS restriction de fenêtre horaire   : {total_all_magic_match:+.2f}$")
print(f" Écart dû UNIQUEMENT à la fenêtre horaire (3h UTC)         : {total_all_magic_match - total_bot_window:+.2f}$")

mt5.shutdown()
