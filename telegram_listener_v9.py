"""
=============================================================
 TELEGRAM → MT5 | Bot Trading
 Version 9.0.0 — BUG FIXES SESSION (5 bugs corrigés)
 MODIFICATIONS v9.0.0 :
 - FIX #1 : Race condition dans _cancel_pending_orders_for_entry (cancel échoué → résolution immédiate)
 - FIX #2 : BE LATE — protection des limits remplis après le BE initial
 - FIX #3 : TP_TRIGGER nettoyage immédiat de self.active
 - FIX #4 : SL_MOVE met à jour les ordres pending
 - FIX #5 : Alerte BE LATE avec ancien/nouveau target_gain
 - FIX #6 : Fusion QA — limit rempli non géré (_resolve_order + quick_limit_filled)
=============================================================
"""

import subprocess, sys
_deps = {"dotenv": "python-dotenv", "telethon": "telethon", "MetaTrader5": "MetaTrader5"}
for _mod, _pkg in _deps.items():
    try:
        __import__(_mod)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", _pkg, "-q"])

import asyncio
import re
import logging
import time
import json
import urllib.request
import os
import threading
import ssl
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple  # ← IMPORT ESSENTIEL
from dotenv import load_dotenv

from telethon import TelegramClient, events
import MetaTrader5 as mt5

sys.stdout.reconfigure(line_buffering=True)

# Constantes
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
ORDER_FILLING_RETURN = 0
ORDER_FILLING_FOK = 1
ORDER_FILLING_IOC = 2

load_dotenv()

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
CHANNEL_NAME = os.getenv("TG_CHANNEL_1", os.getenv("TG_CHANNEL", ""))
CHANNEL_NAME_2 = os.getenv("TG_CHANNEL_2", "")
CHANNEL_NAME_3 = os.getenv("TG_CHANNEL_3", "")
CHANNEL_NAME_4 = os.getenv("TG_CHANNEL_4", "")
CHANNEL_NAME_5 = os.getenv("TG_CHANNEL_5", "")
CHANNEL_NAME_6 = os.getenv("TG_CHANNEL_6", "")
CHANNEL_NAME_7 = os.getenv("TG_CHANNEL_7", "")
CHANNEL_NAME_8 = os.getenv("TG_CHANNEL_8", "")
CHANNEL_NAME_9 = os.getenv("TG_CHANNEL_9", "")

# Mapping canal → numéro
CHANNEL_NUM_MAP = {}
for _i, _name in enumerate([CHANNEL_NAME, CHANNEL_NAME_2, CHANNEL_NAME_3,
                             CHANNEL_NAME_4, CHANNEL_NAME_5, CHANNEL_NAME_6,
                             CHANNEL_NAME_7, CHANNEL_NAME_8, CHANNEL_NAME_9], 1):
    if _name:
        CHANNEL_NUM_MAP[_name] = _i
        if _name.lstrip("-").isdigit():
            CHANNEL_NUM_MAP[_name.lstrip("-")] = _i
            if _name not in CHANNEL_NUM_MAP:
                CHANNEL_NUM_MAP[_name] = _i

MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")
MT5_PATH     = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe")

MAGIC_NUMBER = int(os.getenv("MAGIC_NUMBER", "20250226"))
SLIPPAGE = int(os.getenv("SLIPPAGE", "20"))
ORDER_EXPIRY_MIN = int(os.getenv("ORDER_EXPIRY_MINUTES", "240"))
LOT_SIZE = float(os.getenv("LOT_TOTAL", "0.01"))
LOT_UNIQUE_TRADE = float(os.getenv("LOT_UNIQUE_TRADE", "0.01"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
MAX_SPREAD_POINTS = float(os.getenv("MAX_SPREAD_POINTS", "50"))

# === GAIN FIXE ===
TP_FIXED_ENABLED = os.getenv("TP_FIXED_ENABLED", "true").lower() == "true"
TP_FIXED_GAIN_USD = float(os.getenv("TP_FIXED_GAIN_USD", "15.0"))
PNL_TRIGGER_USD = float(os.getenv("PNL_TRIGGER_USD", "8.0"))
BE_TP_TRIGGER_PCT = float(os.getenv("BE_TP_TRIGGER_PCT", "0.5"))  # 50% du chemin vers TP1

# === FILTRES ===
TIME_FILTER_ENABLED = os.getenv("TIME_FILTER_ENABLED", "true").lower() == "true"
TRADING_START_HOUR = int(os.getenv("TRADING_START_HOUR", "3"))
TRADING_END_HOUR = int(os.getenv("TRADING_END_HOUR", "20"))
DAILY_PROFIT_LIMIT = float(os.getenv("DAILY_PROFIT_LIMIT", "30.0"))

# === CACHE TTL ===


# === HEARTBEAT ===
HEARTBEAT_INTERVAL_MIN = int(os.getenv("HEARTBEAT_INTERVAL_MIN", "10"))  # minutes

# === PARAMÈTRES SL (définis dans .env) ===
SL_PRIX_UNIQUE = float(os.getenv("SL_PRIX_UNIQUE", "15.0"))
SL_PLUS_PROCHE = float(os.getenv("SL_PLUS_PROCHE", "10.0"))

# === AUTRES ===
TG_ALERT_CHANNEL = os.getenv("TG_ALERT_CHANNEL", "")
ACTIVE_GRADE = os.getenv("ACTIVE_GRADE", "false").lower() == "true"
NUM_CHANEL_GRADE = int(os.getenv("NUM_CHANEL_GRADE", "0"))
REVERSE_PRICE = float(os.getenv("REVERSE_PRICE", "2.0"))
REALISED_GRADE = float(os.getenv("REALISED_GRADE", "3.0"))
MAX_GRADE_POSITIONS = int(os.getenv("MAX_GRADE_POSITIONS", "10"))
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
NEWS_ENABLED = os.getenv("NEWS_FILTER_ENABLED", "false").lower() == "true"
NEWS_BLOCK_MIN = int(os.getenv("NEWS_WINDOW_BEFORE_BLOCK", "15"))
NEWS_CLOSE_MIN = int(os.getenv("NEWS_WINDOW_BEFORE_CLOSE", "5"))
NEWS_AFTER_MIN = int(os.getenv("NEWS_WINDOW_AFTER", "15"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "1"))
RUNTIME_MINUTES = int(os.getenv("RUNTIME_MINUTES", "0"))

START_TIME = datetime.now(timezone.utc)

# =============================================================
# LOGGING
# =============================================================
class OrderFilter(logging.Filter):
    HIDE = ["[SPAM]", "[CYCLE]"]
    def filter(self, record):
        msg = record.getMessage()
        for tag in self.HIDE:
            if tag in msg:
                return False
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot_trading.log", encoding="utf-8")],
)
log = logging.getLogger(__name__)

class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

for handler in log.handlers[:]:
    if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
        log.removeHandler(handler)
flush_handler = FlushStreamHandler(sys.stdout)
flush_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
flush_handler.addFilter(OrderFilter())
log.addHandler(flush_handler)

# =============================================================
# HELPERS
# =============================================================
def get_trading_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=TRADING_START_HOUR, minute=0, second=0, microsecond=0)
    if now.hour < TRADING_START_HOUR:
        start = start - timedelta(days=1)
    return start

def in_blocked_window() -> tuple[bool, str]:
    if not TIME_FILTER_ENABLED:
        return False, ""
    now = datetime.now(timezone.utc)
    if TRADING_START_HOUR <= now.hour < TRADING_END_HOUR:
        return False, ""
    return True, f"Hors plage {TRADING_START_HOUR}h-{TRADING_END_HOUR}h UTC"

# =============================================================
# TELEGRAM ALERTS
# =============================================================
_alert_client = None
_main_loop = None

def send_alert_sync(message: str):
    if not TG_ALERT_CHANNEL or not _alert_client or not _main_loop:
        return
    try:
        coro = _alert_client.send_message(TG_ALERT_CHANNEL, message)
        future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
        future.result(timeout=15)  # ✅ 15s au lieu de 5s
    except TimeoutError:
        log.warning(f"[ALERT] Timeout envoi alerte Telegram (15s)")
    except Exception as e:
        log.warning(f"[ALERT] Erreur envoi alerte Telegram: {type(e).__name__}: {e}")

# =============================================================
# PERFORMANCE TRACKER
# =============================================================
class PerformanceTracker:
    def __init__(self):
        self._trades_cache = []
        self._report_sent = False

    def log_trade_open(self, entry):
        sig = entry["signal"]
        now = datetime.now(timezone.utc)
        row = {
            "canal": sig.get("source_channel", "Inconnu"),
            "symbol": sig["symbol"],
            "action": sig["action"],
            "result": "OPEN",
            "pnl": 0.0,
            "duree_min": 0,
            "_entry_time": now,
            "_entry": entry,
        }
        self._trades_cache.append(row)

    def log_trade_close(self, entry, total_pnl):
        sig = entry["signal"]
        canal = sig.get("source_channel", "Inconnu")
        now = datetime.now(timezone.utc)
        result = "WIN" if total_pnl > 0 else ("BE" if total_pnl == 0 else "LOSS")
        for t in reversed(self._trades_cache):
            if (t["canal"] == canal and
                t["symbol"] == sig["symbol"] and
                t["action"] == sig["action"] and
                t["result"] == "OPEN"):
                entry_time = t.get("_entry_time", now)
                duree = (now - entry_time).total_seconds() / 60
                t["result"] = result
                t["pnl"] = round(total_pnl, 2)
                t["duree_min"] = round(duree, 1)
                break

    def format_session_summary(self) -> str:
        if not self._trades_cache:
            return "📊 Aucun trade cette session."
        wins = sum(1 for t in self._trades_cache if t["result"] == "WIN")
        losses = sum(1 for t in self._trades_cache if t["result"] == "LOSS")
        be = sum(1 for t in self._trades_cache if t["result"] == "BE")
        still_open = sum(1 for t in self._trades_cache if t["result"] == "OPEN")
        total_pnl = sum(t["pnl"] for t in self._trades_cache)
        lines = [
            "📊 RÉSUMÉ SESSION",
            "━━━━━━━━━━━━━━━━━━",
            f"✅ Wins : {wins}",
            f"❌ Losses : {losses}",
            f"⬜ Breakeven : {be}",
            f"🔵 Ouverts : {still_open}",
            f"💰 P&L session : {total_pnl:+.2f}$",
        ]
        return "\n".join(lines)

    def print_final_report(self):
        if self._report_sent:
            return
        self._report_sent = True
        log.info("<<<<< INFO >>>>> Rapport final :")
        summary = self.format_session_summary()
        for line in summary.split("\n"):
            log.info(f"<<<<< INFO >>>>> {line}")

# =============================================================
# SIGNAL PARSER
# =============================================================
from signal_parser import SignalParser, is_spam, TradeSignal

# =============================================================
# NEWS MANAGER
# =============================================================
class NewsManager:
    FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    def __init__(self, bridge):
        self.bridge = bridge
        self.manager = None
        self._news = []
        self._blocked = False
        self._stop = False
        self._task = None

    def set_manager(self, manager):
        self.manager = manager

    def is_blocked(self) -> bool:
        return self._blocked

    async def start(self):
        self._task = asyncio.create_task(self._loop_async())

    async def _loop_async(self):
        while not self._stop:
            try:
                await asyncio.to_thread(self._fetch_news)
                await asyncio.to_thread(self._check_news)
            except Exception as e:
                log.error(f"NewsManager erreur: {e}")
            await asyncio.sleep(1800)

    def _fetch_news(self):
        if not NEWS_ENABLED:
            return
        try:
            ssl_context = ssl._create_unverified_context()
            req = urllib.request.Request(
                self.FF_URL, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as r:
                data = json.loads(r.read().decode())
            self._news = [
                n for n in data
                if n.get("impact", "").lower() == "high"
                and n.get("currency", "") in ("USD", "XAU")
            ]
            log.info(f"<<<<< INFO >>>>> {len(self._news)} news HIGH impact chargées")
        except Exception as e:
            log.error(f"[NEWS] Erreur fetch: {e}")

    def _check_news(self):
        if not NEWS_ENABLED:
            return
        now = datetime.now(timezone.utc)
        for news in self._news:
            try:
                news_time = datetime.fromisoformat(news["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            diff_minutes = (news_time - now).total_seconds() / 60
            if -NEWS_AFTER_MIN <= diff_minutes < 0 and self._blocked:
                remaining = NEWS_AFTER_MIN + diff_minutes
                if remaining <= 0:
                    self._blocked = False
                    log.info(f"<<<<< INFO >>>>> {news.get('title', '?')} terminé → reprise")
                    break
            if 0 < diff_minutes <= NEWS_CLOSE_MIN:
                if not self._blocked:
                    self._blocked = True
                    log.info(f"<<<<< INFO >>>>> {news.get('title', '?')} dans {diff_minutes:.0f} min → fermeture positions")
                    if self.manager:
                        self._close_all()
                    break
            elif NEWS_CLOSE_MIN < diff_minutes <= NEWS_BLOCK_MIN:
                if not self._blocked:
                    self._blocked = True
                    log.info(f"<<<<< INFO >>>>> {news.get('title', '?')} dans {diff_minutes:.0f} min → signaux bloqués")
                    break

    def _close_all(self):
        if self.manager:
            for entry in list(self.manager.active):
                for o in entry.get("orders", []):
                    self.bridge.cancel_order(o["order"])
                entry["orders"] = []
            self.bridge.close_all()

    def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()

# =============================================================
# MT5 BRIDGE
# =============================================================
class MT5Bridge:
    _sym_cache: dict = {}

    def connect(self) -> bool:
        if mt5.initialize():
            info = mt5.account_info()
            if info and info.login > 0:
                log.info(f"MT5 déjà connecté → {info.name} | Balance: {info.balance} {info.currency}")
                return self._check_algo()
        mt5.shutdown()
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER,
                              path=MT5_PATH if os.path.exists(MT5_PATH) else None):
            log.error(f"MT5 initialize failed: {mt5.last_error()}")
            return False
        info = mt5.account_info()
        log.info(f"MT5 connecté → {info.name} | Balance: {info.balance} {info.currency}")
        return self._check_algo()

    def _check_algo(self) -> bool:
        terminal = mt5.terminal_info()
        try:
            algo_ok = bool(getattr(terminal, "trade_expert", True))
        except Exception:
            algo_ok = True
        if not algo_ok:
            log.warning("Algo Trading désactivé — activez manuellement le bouton vert dans MT5")
        else:
            log.info("Algo Trading actif ✅")
        return True

    def disconnect(self):
        mt5.shutdown()

    def _sym(self, symbol: str):
        if symbol in self._sym_cache:
            return mt5.symbol_info(self._sym_cache[symbol])
        info = mt5.symbol_info(symbol)
        if info is None:
            for sfx in ["m", "m+", ".a", "pro", "+", ".", "z", "micro", "#", ""]:
                info = mt5.symbol_info(symbol + sfx)
                if info:
                    log.debug(f"Symbole résolu : {symbol} → {symbol + sfx}")
                    break
        if info is None and symbol.endswith("m"):
            info = mt5.symbol_info(symbol[:-1])
            if info:
                log.debug(f"Symbole résolu : {symbol} → {symbol[:-1]}")
        if info is None:
            all_syms = mt5.symbols_get()
            if all_syms:
                matches = [s for s in all_syms if s.name.upper().startswith(symbol.upper()[:6])]
                if matches:
                    info = matches[0]
                    log.debug(f"Symbole trouvé par recherche : {info.name}")
        if info is None:
            log.error(f"Symbole introuvable : {symbol}")
            return None
        self._sym_cache[symbol] = info.name
        if not info.visible:
            mt5.symbol_select(info.name, True)
            time.sleep(0.5)
        return mt5.symbol_info(info.name)

    def _get_filling(self, sym_info) -> int:
        filling = sym_info.filling_mode
        if filling & SYMBOL_FILLING_FOK:
            return ORDER_FILLING_FOK
        if filling & SYMBOL_FILLING_IOC:
            return ORDER_FILLING_IOC
        return ORDER_FILLING_RETURN

    def current_price(self, symbol: str, action: str) -> float | None:
        sym_info = self._sym(symbol)
        if sym_info is None:
            return None
        tick = mt5.symbol_info_tick(sym_info.name)
        if not tick:
            return None
        return tick.ask if action == "BUY" else tick.bid

    def _validate_volume(self, sym_info, lot: float) -> float:
        vol_min = sym_info.volume_min
        vol_max = sym_info.volume_max
        vol_step = sym_info.volume_step
        if lot < vol_min:
            lot = vol_min
        elif lot > vol_max:
            lot = vol_max
        if vol_step > 0:
            lot = round(lot / vol_step) * vol_step
            lot = round(lot, 8)
        return lot

    def place_market_order(self, signal: dict, lot: float, tp: float, sl: float = 0.0, comment: str = "TG-market") -> int | None:
        sym = self._sym(signal["symbol"])
        if not sym:
            return None
        lot = self._validate_volume(sym, lot)
        action = signal["action"]
        tick = mt5.symbol_info_tick(sym.name)
        if not tick:
            return None
        price = tick.ask if action == "BUY" else tick.bid
        otype = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        filling_modes = []
        filling = sym.filling_mode
        if filling & SYMBOL_FILLING_FOK:
            filling_modes.append(ORDER_FILLING_FOK)
        if filling & SYMBOL_FILLING_IOC:
            filling_modes.append(ORDER_FILLING_IOC)
        filling_modes.append(ORDER_FILLING_RETURN)
        if sl == 0.0:
            sl = signal.get("sl", 0.0)
        for fill_mode in filling_modes:
            result = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": sym.name,
                "volume": lot,
                "type": otype,
                "price": price,
                "sl": round(sl, sym.digits) if sl else 0,
                "tp": round(tp, sym.digits) if tp else 0,
                "deviation": SLIPPAGE,
                "magic": MAGIC_NUMBER,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_mode,
            })
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.debug(f"MARKET {action} {sym.name} lot={lot} @{price} ticket#{result.order}")
                return result.order
        return None

    def place_limit_order(self, signal: dict, lot: float, price: float, tp: float, expiry: datetime, comment: str = "TG-limit") -> int | None:
        sym = self._sym(signal["symbol"])
        if not sym:
            return None
        lot = self._validate_volume(sym, lot)
        action = signal["action"]
        if tp:
            if action == "BUY" and tp <= price:
                return None
            if action == "SELL" and tp >= price:
                return None
        otype = mt5.ORDER_TYPE_BUY_LIMIT if action == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        filling = self._get_filling(sym)
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": sym.name,
            "volume": lot,
            "type": otype,
            "price": round(price, sym.digits),
            "sl": round(signal.get("sl", 0), sym.digits) if signal.get("sl", 0) else 0,
            "tp": round(tp, sym.digits) if tp else 0,
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_SPECIFIED,
            "expiration": int(expiry.timestamp()),
            "type_filling": filling,
        })
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            log.debug(f"LIMIT {action} {sym.name} lot={lot} @{price} TP={tp} order#{result.order}")
            return result.order
        return None

    def cancel_order(self, order_ticket: int) -> bool:
        result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket})
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        log.debug(f"{'OK' if ok else 'FAIL'} Annulation #{order_ticket}")
        return ok

    def close_position(self, ticket: int, comment: str = "close") -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        cprice = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        ctype = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        filling = self._get_filling(mt5.symbol_info(pos.symbol))
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": ctype,
            "position": ticket,
            "price": cprice,
            "deviation": SLIPPAGE,
            "magic": MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.debug(f"Fermeture #{ticket} ({comment}) P&L={pos.profit:.2f}")
        return ok

    def modify_sl(self, ticket: int, new_sl: float, label: str = "") -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        sym = mt5.symbol_info(pos.symbol)
        if sym is None:
            return False
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": round(new_sl, sym.digits),
            "tp": pos.tp,
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.debug(f"SL modifié #{ticket} → {new_sl} {label}")
        return ok

    def modify_sl_tp(self, ticket: int, new_sl: float, new_tp: float, label: str = "") -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        sym = mt5.symbol_info(pos.symbol)
        if sym is None:
            return False
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": round(new_sl, sym.digits),
            "tp": round(new_tp, sym.digits),
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.debug(f"SL/TP modifiés #{ticket} → SL={new_sl} TP={new_tp} {label}")
        return ok

    def modify_pending_order(self, order_ticket: int, new_sl: float, new_tp: float, label: str = "") -> bool:
        orders = mt5.orders_get(ticket=order_ticket)
        if not orders:
            log.warning(f"Ordre pending #{order_ticket} introuvable")
            return False
        order = orders[0]
        sym = mt5.symbol_info(order.symbol)
        if sym is None:
            log.warning(f"Symbole introuvable pour l'ordre #{order_ticket}")
            return False
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_MODIFY,
            "order": order_ticket,
            "price": order.price_open,
            "sl": round(new_sl, sym.digits),
            "tp": round(new_tp, sym.digits),
            "type_time": order.type_time,
            "expiration": order.time_expiration,
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.debug(f"Ordre pending modifié #{order_ticket} → SL={new_sl} TP={new_tp} {label}")
        else:
            log.error(f"Échec modification ordre pending #{order_ticket}")
        return ok

    def update_sl_by_channel(self, new_sl: float, channel_num: int):
        positions = mt5.positions_get()
        if not positions:
            return
        updated = 0
        for pos in positions:
            if pos.magic != MAGIC_NUMBER:
                continue
            if not pos.comment.startswith(f"CH{channel_num}-"):
                continue
            sym = mt5.symbol_info(pos.symbol)
            if sym is None:
                continue
            result = mt5.order_send({
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": pos.ticket,
                "sl": round(new_sl, sym.digits),
                "tp": pos.tp,
            })
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                updated += 1
                log.debug(f"SL modifié #{pos.ticket} (canal CH{channel_num}) → {new_sl}")
        log.info(f"<<<<< INFO >>>>> SL MOVE canal {channel_num} → {new_sl} sur {updated} positions")

    def update_sl_all(self, new_sl: float):
        updated = 0
        positions = mt5.positions_get()
        if positions:
            for pos in positions:
                if pos.magic != MAGIC_NUMBER:
                    continue
                sym = mt5.symbol_info(pos.symbol)
                if not sym:
                    continue
                result = mt5.order_send({
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": pos.symbol,
                    "position": pos.ticket,
                    "sl": round(new_sl, sym.digits),
                    "tp": pos.tp,
                })
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
        log.info(f"<<<<< INFO >>>>> SL MOVE global → {new_sl} sur {updated} positions")

    def close_all(self, symbol: str | None = None, channel_num: int | None = None):
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not positions:
            return
        for pos in positions:
            if pos.magic != MAGIC_NUMBER:
                continue
            if channel_num is not None:
                if not pos.comment.startswith(f"CH{channel_num}-"):
                    continue
            self.close_position(pos.ticket, comment="close-all")

# =============================================================
# AJUSTEMENT DYNAMIQUE DU SL (utilise SL_PLUS_PROCHE)
# =============================================================
def adjust_sl_to_nearest_entry(prices: List[float], sl: float, action: str, max_distance: float = None) -> float:
    if max_distance is None:
        max_distance = SL_PLUS_PROCHE
    if not prices:
        return sl
    nearest = min(prices, key=lambda p: abs(p - sl))
    distance = abs(nearest - sl)
    if distance > max_distance:
        if action == "BUY":
            new_sl = nearest - max_distance
            # BUY: SL sous le prix. max() prend le SL le plus haut = le plus resserré ✓
            return max(new_sl, sl)
        else:  # SELL
            new_sl = nearest + max_distance
            # SELL: SL au-dessus du prix. min() prend le SL le plus bas = le plus resserré ✓
            return min(new_sl, sl)
    return sl

# =============================================================
# TRADE MANAGER (avec whitelist BE)
# =============================================================
class TradeManager:
    def __init__(self, bridge: MT5Bridge, tracker=None):
        self.bridge = bridge
        self.tracker = tracker
        self.active = []
        self._lock = threading.Lock()
        self._daily_lock = threading.Lock()
        self._stop = False
        self._task = None

        # ★★★ WHITELIST des rôles autorisés à déclencher le BE ★★★
        self._be_allowed_roles = {
            "market_single",       # Prix Unique S1
            "limit_single",        # Prix Unique S2
            "market_cas1",         # CAS 1
            "market_cas2",         # CAS 2-a
            "limit_1",             # CAS 2-b
            "quick_market",        # Quick Alert market
            "quick_limit_filled",  # Quick Alert limit rempli
            "merge_limit",         # Fusion QA → limit
        }

        self._daily_pnl = self._recover_daily_pnl()
        self._daily_pnl_day = get_trading_day_start().day
        log.info(f"<<<<< INFO >>>>> P&L quotidien récupéré : {self._daily_pnl:.2f}$")



    # =============================================================
    # P&L QUOTIDIEN (avec verrouillage)
    # =============================================================
    def _recover_daily_pnl(self) -> float:
        start = get_trading_day_start()
        deals = mt5.history_deals_get(start, datetime.now(timezone.utc))
        if deals is None or len(deals) == 0:
            return 0.0
        total = 0.0
        for deal in deals:
            if deal.magic == MAGIC_NUMBER and deal.entry == mt5.DEAL_ENTRY_OUT:
                total += deal.profit
        return total

    def _get_floating_pnl(self) -> float:
        positions = mt5.positions_get()
        if not positions:
            return 0.0
        total = 0.0
        for pos in positions:
            if pos.magic == MAGIC_NUMBER:
                total += pos.profit
        return total

    def _update_daily_pnl(self, pnl: float):
        with self._daily_lock:
            start = get_trading_day_start()
            if start.day != self._daily_pnl_day:
                self._daily_pnl = 0.0
                self._daily_pnl_day = start.day
                log.info(f"<<<<< INFO >>>>> Reset journalier à {TRADING_START_HOUR}h UTC")
            self._daily_pnl += pnl
            total = self._daily_pnl + self._get_floating_pnl()
        log.info(f"<<<<< INFO >>>>> P&L quotidien : réalisé {self._daily_pnl:.2f}$ | flottant {self._get_floating_pnl():.2f}$ | total {total:.2f}$")

    def _check_daily_pnl_limit(self) -> bool:
        with self._daily_lock:
            start = get_trading_day_start()
            if start.day != self._daily_pnl_day:
                self._daily_pnl = 0.0
                self._daily_pnl_day = start.day
                log.info(f"<<<<< INFO >>>>> Reset journalier à {TRADING_START_HOUR}h UTC")
            total_pnl = self._daily_pnl + self._get_floating_pnl()
            if DAILY_PROFIT_LIMIT > 0 and total_pnl >= DAILY_PROFIT_LIMIT:
                log.info(f"<<<<< INFO >>>>> Limite quotidienne atteinte : {total_pnl:.2f}$ / {DAILY_PROFIT_LIMIT}$")
                return False
        return True

    # =============================================================
    # SL MOVE — Mettre à jour le SL des pending orders
    # =============================================================
    def update_pending_orders_sl(self, channel_num: int, new_sl: float):
        updated = 0
        with self._lock:
            for entry in self.active:
                signal = entry.get("signal", {})
                canal = signal.get("source_channel", "Inconnu")
                ch = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), None))
                if ch != channel_num:
                    continue
                # Mettre à jour le SL dans le signal dict
                signal["sl"] = new_sl
                # Modifier les ordres pending dans MT5
                for o in entry.get("orders", []):
                    order_ticket = o.get("order", 0)
                    tp = o.get("tp_final", 0)
                    if order_ticket and tp:
                        if self.bridge.modify_pending_order(order_ticket, new_sl, tp, f"[SL-MOVE @{new_sl}]"):
                            updated += 1
        if updated:
            log.info(f"<<<<< INFO >>>>> SL MOVE pending orders canal {channel_num} → {new_sl} sur {updated} ordres")

    # =============================================================
    # ARRÊT QUOTIDIEN
    # =============================================================
    def _cancel_all_pending_orders(self) -> int:
        orders = mt5.orders_get()
        if not orders:
            return 0
        cancelled = 0
        for order in orders:
            if order.magic == MAGIC_NUMBER:
                if self.bridge.cancel_order(order.ticket):
                    cancelled += 1

        log.debug(f"Annulation de {cancelled} ordre(s) pending (tous signaux)")
        return cancelled

    def _close_all_positions(self) -> float:
        positions = mt5.positions_get()
        if not positions:
            return 0.0
        total_pnl = 0.0
        for pos in positions:
            if pos.magic == MAGIC_NUMBER:
                ticket = pos.ticket
                if self.bridge.close_position(ticket, comment="DAILY-LIMIT-CLOSE"):
                    deals = mt5.history_deals_get(symbol=pos.symbol, from_time=get_trading_day_start())
                    if deals:
                        for deal in reversed(deals):
                            if deal.position_id == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
                                total_pnl += deal.profit
                                log.debug(f"Fermeture #{ticket} (P&L={deal.profit:.2f})")
                                break
                    else:
                        total_pnl += pos.profit
                        log.debug(f"Fermeture #{ticket} (P&L={pos.profit:.2f})")
        log.debug(f"Fermeture de toutes les positions")
        return total_pnl

    def _clear_all_entries(self):
        with self._lock:
            for entry in self.active:
                entry["orders"] = []
                for t in entry.get("tickets", []):
                    t["_daily_limit_closed"] = True
            self.active.clear()
        log.debug("Liste des entrées vidée")

    def _shutdown_for_daily_limit(self):
        log.info("<<<<< INFO >>>>> OBJECTIF QUOTIDIEN ATTEINT")
        log.info(f"<<<<< INFO >>>>> Limite: {DAILY_PROFIT_LIMIT}$")

        positions = mt5.positions_get()
        nb_positions = len([p for p in positions if p.magic == MAGIC_NUMBER]) if positions else 0

        cancelled = self._cancel_all_pending_orders()
        total_pnl = self._close_all_positions()
        
        with self._daily_lock:
            self._update_daily_pnl(total_pnl)
            total = self._daily_pnl + self._get_floating_pnl()
        
        self._clear_all_entries()

        log.info(f"===== | DAILY-LIMIT | =====")
        log.info(f"P&L: {total:.2f}$ | {nb_positions} positions fermées | {cancelled} ordres annulés")

        send_alert_sync(
            f"🚨 OBJECTIF QUOTIDIEN ATTEINT\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"P&L total: {total:.2f}$ / Limite: {DAILY_PROFIT_LIMIT}$\n"
            f"Positions fermées : {nb_positions}\n"
            f"Ordres annulés : {cancelled}\n"
            f"⏸️ Trading arrêté pour aujourd'hui"
        )

    # =============================================================
    # GESTION DU BE (avec whitelist)
    # =============================================================
    def _cancel_pending_orders_for_entry(self, entry: dict):
        # ★★★ FIX : vérifier si les ordres sont déjà remplis avant d'annuler ★★★
        # Le délai MT5 history peut faire qu'un ordre rempli n'est pas encore détecté.
        # On vérifie via mt5.orders_get() si l'ordre existe encore.
        orders_to_cancel = []
        already_filled = []
        for o in entry.get("orders", []):
            order_ticket = o.get("order", 0)
            if not order_ticket:
                continue
            # Vérifier si l'ordre existe encore dans MT5
            mt5_order = mt5.orders_get(ticket=order_ticket)
            if mt5_order:
                # L'ordre est toujours pending → on peut l'annuler
                orders_to_cancel.append(order_ticket)
            else:
                # L'ordre n'existe plus → il a été rempli !
                # Chercher la position correspondante
                symbol = entry.get("signal", {}).get("symbol", "")
                pos = self._resolve_order(order_ticket, symbol)
                if pos:
                    tk = {
                        "ticket": pos.ticket, "lot": o["lot"], "role": o["role"],
                        "entry_price": pos.price_open,
                        "tp_index": o.get("tp_index", 0), "tp_target": o.get("tp_target", 0),
                        "tp3": o.get("tp3", 0), "tp_final": o.get("tp_final", 0),
                        "sl_step": 0, "trail_active": False, "be_active": False, "be_sl": 0,
                    }
                    entry["tickets"].append(tk)
                    already_filled.append(order_ticket)
                    log.info(f"[BE] Ordre #{order_ticket} déjà rempli → ticket #{pos.ticket} ajouté")

        if already_filled:
            log.info(f"[BE] {len(already_filled)} ordre(s) déjà rempli(s) → ajoutés aux tickets")

        if not orders_to_cancel:
            return

        log.debug(f"Annulation de {len(orders_to_cancel)} ordre(s) pending")
        symbol = entry.get("signal", {}).get("symbol", "")
        for ticket in orders_to_cancel:
            ok = self.bridge.cancel_order(ticket)
            if not ok:
                # ★★★ FIX : cancel échoué → l'ordre s'est rempli entre le check et le cancel ★★★
                pos = self._resolve_order(ticket, symbol)
                if pos:
                    # Trouver l'order dict correspondant pour récupérer les métadonnées
                    o_data = next((o for o in entry["orders"] if o.get("order") == ticket), None)
                    if o_data:
                        tk = {
                            "ticket": pos.ticket, "lot": o_data["lot"], "role": o_data["role"],
                            "entry_price": pos.price_open,
                            "tp_index": o_data.get("tp_index", 0), "tp_target": o_data.get("tp_target", 0),
                            "tp3": o_data.get("tp3", 0), "tp_final": o_data.get("tp_final", 0),
                            "sl_step": 0, "trail_active": False, "be_active": False, "be_sl": 0,
                        }
                        entry["tickets"].append(tk)
                        log.info(f"[BE] Race condition détectée : #{ticket} rempli pendant annulation → #{pos.ticket} ajouté")
            else:
                log.debug(f"Annulation ordre pending #{ticket}")
        entry["orders"] = []

    def _get_gain_per_position(self, entry: dict) -> float:
        signal = entry.get("signal", {})
        action = signal.get("action", "")
        zone_low = signal.get("zone_low", 0)
        zone_high = signal.get("zone_high", 0)
        entry_price = (zone_low + zone_high) / 2
        tps = signal.get("tps", [])
        if not tps:
            return TP_FIXED_GAIN_USD
        tp_final = tps[-1]
        if action == "BUY":
            potential_gain = tp_final - entry_price
        else:
            potential_gain = entry_price - tp_final
        return min(TP_FIXED_GAIN_USD, potential_gain)

    def _get_tp_trigger(self, entry: dict) -> float:
        signal = entry.get("signal", {})
        tps = signal.get("tps", [])
        if len(tps) >= 3:
            return tps[2]
        elif len(tps) >= 2:
            return tps[1]
        elif len(tps) >= 1:
            return tps[0]
        return 0.0

    def _check_pnl_trigger(self, entry: dict) -> bool:
        # ★★★ FIX : utiliser min_profit (pire position) au lieu de best_profit ★★★
        # Le BE se déclenche quand la PIRE position atteint le seuil.
        # Pour BUY: market @ 2350 (pire entrée) doit atteindre 8$
        # Pour BUY: limit @ 2340 (meilleure entrée) aura forcément plus de profit.
        # → La market est protégée en premier.
        min_profit = float('inf')
        min_role = "?"
        has_active = False
        for t in entry.get("tickets", []):
            if t.get("be_active"):
                continue
            # ★★★ Vérification whitelist ★★★
            if t.get("role") not in self._be_allowed_roles:
                continue
            pos = self._get_pos(t["ticket"])
            if pos:
                has_active = True
                if pos.profit < min_profit:
                    min_profit = pos.profit
                    min_role = t.get("role", "?")
        if has_active and min_profit >= PNL_TRIGGER_USD:
            return True

        # ★★★ FIX : Déclenchement basé sur la distance au TP si PnL insuffisant ★★★
        # Utile pour les petits lots où le PnL met trop longtemps à atteindre le seuil
        for t in entry.get("tickets", []):
            if t.get("be_active") or t.get("role") not in self._be_allowed_roles:
                continue
            pos = self._get_pos(t["ticket"])
            if not pos:
                continue
            signal = entry.get("signal", {})
            action = signal.get("action", "")
            entry_price = t.get("entry_price", 0)
            tps = signal.get("tps", [])
            if not tps or entry_price == 0:
                continue
            tp1 = tps[0]
            sym = mt5.symbol_info(pos.symbol)
            if sym is None:
                continue
            tick = mt5.symbol_info_tick(sym.name)
            if tick is None:
                continue
            current = tick.bid if action == "BUY" else tick.ask
            tp_distance = abs(tp1 - entry_price)
            price_distance = abs(current - entry_price)
            if tp_distance > 0 and (price_distance / tp_distance) >= BE_TP_TRIGGER_PCT:
                log.debug(f"[BE] Déclenchement distance : {price_distance:.2f}/{tp_distance:.2f} = {price_distance/tp_distance*100:.0f}% >= {BE_TP_TRIGGER_PCT*100:.0f}%")
                return True

        # ✅ LOG DEBUG : pourquoi le BE ne se déclenche pas
        if has_active and min_profit < float('inf'):
            log.debug(f"[BE] PnL insuffisant : {min_profit:.2f}$ < {PNL_TRIGGER_USD}$ (pire rôle={min_role})")
        return False

    def _apply_be_on_open_positions(self, entry: dict, action: str):
        signal = entry.get("signal", {})
        canal = signal.get("source_channel", "Inconnu")
        ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
        mt5_comment = entry.get("_mt5_comment", f"CH{ch_num}-UNK")
        pending_before = len(entry.get("orders", []))

        # 1. Annuler les ordres pending non remplis
        self._cancel_pending_orders_for_entry(entry)

        # 2. Compter les positions ouvertes
        open_tickets = [t for t in entry.get("tickets", []) if self._get_pos(t["ticket"])]
        open_count = len(open_tickets)
        if open_count == 0:
            log.warning(f"Aucune position ouverte au moment du BE pour {entry.get('_signal_id', '?')}")
            return

        be_applied = 0

        # 3. Calculer le TP fixe : TP_FIXED_GAIN_USD × nombre de positions
        target_gain = TP_FIXED_GAIN_USD * open_count

        if open_count == 1:
            # ★ CAS : 1 position ouverte → BE @ entry ★
            t = open_tickets[0]
            entry_price = t.get("entry_price", 0)
            if entry_price == 0:
                return
            be_price = entry_price
            pos = self._get_pos(t["ticket"])
            if pos:
                sym = mt5.symbol_info(pos.symbol)
                be_price = round(entry_price, sym.digits if sym else 2)
                # ✅ BE @ entry seulement — TP reste le TP final du signal (pas modifié)
                if self.bridge.modify_sl(t["ticket"], be_price, f"[BE 1POS @{be_price}]"):
                    t["be_active"] = True
                    t["be_sl"] = be_price
                    be_applied += 1
            entry["_be_price"] = be_price
            entry["_be_market_entry"] = entry_price

        elif open_count == 2:
            # ★ CAS : 2 positions ouvertes → SL au médian ★
            # Market @ 2350 + Limit @ 2340 → SL @ 2345 pour les deux
            # → Si prix revient à 2345 : market perd 5$, limit gagne 5$ = 0$ total
            entry_1 = open_tickets[0].get("entry_price", 0)
            entry_2 = open_tickets[1].get("entry_price", 0)
            if entry_1 == 0 or entry_2 == 0:
                return
            be_price = (entry_1 + entry_2) / 2
            pos = self._get_pos(open_tickets[0]["ticket"])
            if pos:
                sym = mt5.symbol_info(pos.symbol)
                be_price = round(be_price, sym.digits if sym else 2)
            for t in open_tickets:
                if self.bridge.modify_sl(t["ticket"], be_price, f"[BE 2POS @{be_price}]"):
                    t["be_active"] = True
                    t["be_sl"] = be_price
                    be_applied += 1
            entry["_be_price"] = be_price

        else:
            log.warning(f"Nombre de positions inattendu : {open_count}")
            return

        if be_applied == 0:
            log.warning(f"Aucun BE posé pour {entry.get('_signal_id', '?')} → abandon")
            return

        entry["_target_gain"] = target_gain
        entry["_be_activated"] = True
        entry["_open_positions_at_be"] = be_applied

        log.info(f"===== | {mt5_comment} | BE | =====")
        pos_info = f"{be_applied} POS"
        if not signal.get("is_single_price", False) and pending_before > 0:
            pos_info += f" | {pending_before} PENDING annulés"
        log.info(f"{action} {signal['symbol']} | SL @{be_price:.2f} | {pos_info}")

        alert_lines = [
            f"🔒 {action} {signal['symbol']} | BE ACTIVE",
            "━━━━━━━━━━━━━━━━━━",
            f"NB POS : {be_applied} positions",
            f"SL : {be_price:.2f}",
            f"Gain cible (close manuel) : {target_gain:.2f}$",
        ]
        if not signal.get("is_single_price", False) and pending_before > 0:
            ordre_txt = "ordre" if pending_before == 1 else "ordres"
            alert_lines.append(f"PENDING annulés : {pending_before} {ordre_txt}")
        alert_lines.append(f"Canal: {canal}")
        send_alert_sync("\n".join(alert_lines))

    # ★★★ FIX : Appliquer BE aux nouveaux tickets (limit remplies après BE initial) ★★★

    # =============================================================
    # TP_TRIGGER PENDING UNIQUEMENT
    # =============================================================
    def _check_pending_only_expiry(self, entry: dict, symbol: str, action: str):
        has_open_position = False
        for t in entry.get("tickets", []):
            if self._get_pos(t["ticket"]):
                has_open_position = True
                break
        # ✅ MODIFIÉ : ne pas skip si position ouverte — le TP_TRIGGER doit quand même
        # annuler les ordres pending restants (ex: CAS2-b, limit_1 rempli, limit_2 pending)
        if not entry.get("orders"):
            return
        tp_trigger = self._get_tp_trigger(entry)
        if tp_trigger == 0:
            return
        sym_info = self.bridge._sym(symbol)
        if sym_info is None:
            return
        tick = mt5.symbol_info_tick(sym_info.name)
        if tick is None:
            return
        current = tick.bid if action == "BUY" else tick.ask
        triggered = False
        if action == "BUY" and current >= tp_trigger:
            triggered = True
        elif action == "SELL" and current <= tp_trigger:
            triggered = True
        if triggered:
            # ✅ Capturer les infos AVANT annulation
            pending_count = len(entry.get("orders", []))
            prices = [f"@{o['price']}" for o in entry.get("orders", []) if "price" in o]
            prices_str = ", ".join(prices) if prices else "inconnu"

            if has_open_position:
                log.debug(f"TP_TRIGGER ({tp_trigger:.2f}) atteint avec position ouverte → annulation de {pending_count} ordre(s) pending")
            else:
                log.debug(f"TP_TRIGGER ({tp_trigger:.2f}) atteint sans position ouverte → annulation des ordres pending")

            self._cancel_pending_orders_for_entry(entry)

            signal = entry.get("signal", {})
            canal = signal.get("source_channel", "Inconnu")
            ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
            mt5_comment = entry.get("_mt5_comment", f"CH{ch_num}-UNK")

            log.info(f"===== | {mt5_comment} | TP_TRIGGER | =====")
            log.info(f"{action} {symbol} | {prices_str} | {pending_count} ordres annulés")

            send_alert_sync(
                f"⚠️ {action} {symbol} | TP_TRIGGER\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Ordres annulés : {pending_count}\n"
                f"Prix : {prices_str}\n"
                f"Position ouverte : {'Oui' if has_open_position else 'Non'}\n"
                f"Canal: {canal}"
            )

            # ★★★ FIX : Nettoyer l'entry si aucune position ouverte restante ★★★
            if not has_open_position:
                remaining_tickets = [t for t in entry.get("tickets", []) if self._get_pos(t["ticket"])]
                if not remaining_tickets and not entry.get("orders"):
                    with self._lock:
                        if entry in self.active:
                            self.active.remove(entry)
                    log.debug(f"[TP_TRIGGER] Entry supprimée de self.active (aucune position/order restant)")

    # =============================================================
    # MÉTHODES UTILITAIRES
    # =============================================================
    def _get_pos(self, ticket: int):
        r = mt5.positions_get(ticket=ticket)
        return r[0] if r else None

    def _get_last_pnl(self, ticket: int, symbol: str) -> float:
        start = get_trading_day_start()
        deals = mt5.history_deals_get(symbol=symbol, from_time=start)
        if deals is None:
            return 0.0
        for deal in reversed(deals):
            if deal.position_id == ticket:
                if deal.entry == mt5.DEAL_ENTRY_OUT:
                    return deal.profit
        return 0.0

    def _get_close_reason(self, ticket: int, symbol: str) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
        if deals:
            for deal in reversed(deals):
                if deal.symbol == symbol and deal.position_id == ticket:
                    if deal.entry == mt5.DEAL_ENTRY_OUT:
                        if deal.reason == mt5.DEAL_REASON_TP:
                            return "TP"
                        elif deal.reason == mt5.DEAL_REASON_SL:
                            return "SL"
        return "OTHER"

    # =============================================================
    # BOUCLE PRINCIPALE
    # =============================================================
    async def start(self):
        self._task = asyncio.create_task(self._loop_async())

    def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()

    def register(self, entry: dict):
        with self._lock:
            self.active.append(entry)
        sig = entry["signal"]
        canal = sig.get("source_channel", "Inconnu")
        mode = "DEMO" if DEMO_MODE else "LIVE"
        log.debug(f"TradeManager [{mode}]: {sig['action']} {sig['symbol']} Canal: {canal} | {len(entry['orders'])} ordres")

    async def _loop_async(self):
        while not self._stop:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                await asyncio.to_thread(self._check_all)
            except Exception as exc:
                log.error(f"TradeManager erreur: {exc}")

    def _check_all(self):
        now = datetime.now(timezone.utc)

        if not self._check_daily_pnl_limit():
            if self.active:
                log.debug("[DAILY P&L] Limite atteinte ! Fermeture de toutes les positions et annulation des ordres.")
                self._shutdown_for_daily_limit()
            if not self.active:
                return

        with self._lock:
            entries_snapshot = list(self.active)

        for entry in entries_snapshot:
            signal = entry.get("signal", {})
            symbol = signal.get("symbol", "")
            action = signal.get("action", "")
            canal = signal.get("source_channel", "Inconnu")
            mt5_comment = entry.get("_mt5_comment", f"CH{CHANNEL_NUM_MAP.get(canal, '?')}-UNK")

            still_pending = []
            expired_orders = []
            for o in entry.get("orders", []):
                pos = self._resolve_order(o["order"], symbol)
                if pos:
                    tk = {
                        "ticket": pos.ticket,
                        "lot": o["lot"],
                        "role": o["role"],
                        "entry_price": pos.price_open,
                        "tp_index": o.get("tp_index", 0),
                        "tp_target": o.get("tp_target", 0),
                        "tp3": o.get("tp3", 0),
                        "tp_final": o.get("tp_final", 0),
                        "sl_step": 0,
                        "trail_active": False,
                        "be_active": False,
                        "be_sl": 0,
                    }
                    entry["tickets"].append(tk)
                    log.debug(f"Ordre #{o['order']} rempli → ticket={pos.ticket} @{pos.price_open}")

                    # Log LIMIT remplie
                    log.info(f"===== | {mt5_comment} | LIMIT | =====")
                    log.info(f"{action} {symbol} | #{pos.ticket} @{pos.price_open} lot{o['lot']}")

                    sl_price = signal.get("sl", 0)
                    send_alert_sync(
                        f"🔵 {action} {symbol} | LIMIT REMPLIE\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{o['role']}: @{pos.price_open} | Lot: {o['lot']}\n"
                        f"TICKET: #{pos.ticket}\n"
                        f"TP: {o.get('tp_final', 0)} | SL: {sl_price}\n"
                        f"Canal: {canal}"
                    )

                elif now > entry.get("expiry", now):
                    self.bridge.cancel_order(o["order"])
                    expired_orders.append(o)
                else:
                    still_pending.append(o)

            if expired_orders:
                prices = [f"@{o['price']}" for o in expired_orders if "price" in o]
                prices_str = ", ".join(prices) if prices else "inconnu"
                log.info(f"===== | {mt5_comment} | EXPIRATION | =====")
                log.info(f"{action} {symbol} | {prices_str} | {len(expired_orders)} ordres annulés")
                send_alert_sync(
                    f"🕒 {action} {symbol} | EXPIRATION\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Ordres annulés : {len(expired_orders)}\n"
                    f"Prix : {prices_str}\n"
                    f"Canal: {canal}"
                )

            entry["orders"] = still_pending

            for t in entry.get("tickets", []):
                pos = self._get_pos(t["ticket"])
                if pos is None and not t.get("_reported"):
                    t["_reported"] = True
                    pnl = self._get_last_pnl(t["ticket"], symbol)
                    t["_last_pnl"] = pnl
                    close_reason = self._get_close_reason(t["ticket"], symbol)
                    if close_reason == "TP":
                        label = "TP"
                    elif close_reason == "SL":
                        label = "SL"
                    else:
                        label = "CLOSE"

                    idx = entry["tickets"].index(t) + 1
                    total = len(entry["tickets"])
                    log.info(f"===== | {mt5_comment} | {label} | =====")
                    log.info(f"{action} {symbol} | P&L: {pnl:+.2f}$ | {idx}/{total} #{t['ticket']}")

                    send_alert_sync(
                        f"{'🎯' if label=='TP' else '🛑' if label=='SL' else '⚪'} {action} {symbol} | {label}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"P&L: {pnl:+.2f}$\n"
                        f"Ticket {idx}/{total}: #{t['ticket']}\n"
                        f"Canal: {canal}"
                    )

            active_tickets = []
            for t in entry.get("tickets", []):
                if self._get_pos(t["ticket"]):
                    active_tickets.append(t)

            if not entry.get("orders") and not active_tickets:
                total_pnl = sum(t.get("_last_pnl", 0.0) for t in entry.get("tickets", []))
                log.debug(f"Trade terminé ({symbol}) | Canal: {canal} | P&L total: {total_pnl:+.2f}")
                if self.tracker:
                    self.tracker.log_trade_close(entry, total_pnl)
                self._update_daily_pnl(total_pnl)
                with self._lock:
                    if entry in self.active:
                        self.active.remove(entry)
                continue

            if not entry.get("_be_activated") and not active_tickets:
                self._check_pending_only_expiry(entry, symbol, action)
                if not entry.get("orders"):
                    with self._lock:
                        if entry in self.active:
                            self.active.remove(entry)
                    continue

            # ══════════════════════════════════════════════════════════════
            # ★★★ PHASE 3 : GESTION BE ★★★
            # ══════════════════════════════════════════════════════════════
            # 1 position → pending annulés, SL @ entry
            # 2 positions → SL au médian (total = 0$)
            # Quand BE triggers → pending annulés → jamais de limit après BE

            if TP_FIXED_ENABLED and not entry.get("_be_activated"):
                if self._check_pnl_trigger(entry):
                    self._apply_be_on_open_positions(entry, action)
                    continue

            # ★★★ FIX : Protéger les nouveaux tickets remplis après le BE initial ★★★
            # Quand le limit se remplit après que le BE soit déjà activé sur le market,
            # il faut appliquer le BE au nouveau ticket aussi.
            if entry.get("_be_activated") and entry.get("orders") is not None:
                unprotected = [t for t in entry.get("tickets", []) if not t.get("be_active")]
                if unprotected:
                    all_tickets = [t for t in entry.get("tickets", []) if self._get_pos(t["ticket"])]
                    open_count = len(all_tickets)
                    if open_count >= 2:
                        # Recalculer le médian avec la nouvelle position
                        prices = [t["entry_price"] for t in all_tickets]
                        new_be = round(sum(prices) / len(prices), 2)
                        for t in unprotected:
                            pos = self._get_pos(t["ticket"])
                            if pos:
                                sym = mt5.symbol_info(pos.symbol)
                                new_be_rounded = round(new_be, sym.digits if sym else 2)
                                if self.bridge.modify_sl(t["ticket"], new_be_rounded, f"[BE LATE @{new_be_rounded}]"):
                                    t["be_active"] = True
                                    t["be_sl"] = new_be_rounded
                                    log.info(f"===== | {mt5_comment} | BE | =====")
                                    log.info(f"{action} {symbol} | SL @{new_be_rounded} | LATE LIMIT PROTÉGÉ")
                                    send_alert_sync(
                                        f"🔒 {action} {symbol} | BE LATE\n"
                                        f"━━━━━━━━━━━━━━━━━━\n"
                                        f"Limit rempli après BE → SL @{new_be_rounded}\n"
                                        f"Positions: {open_count}\n"
                                        f"Objectif: {TP_FIXED_GAIN_USD * open_count:.2f}$ (était {TP_FIXED_GAIN_USD * (open_count - 1):.2f}$)\n"
                                        f"Canal: {canal}"
                                    )
                        # Recalculer le target_gain avec le nouveau count
                        entry["_target_gain"] = TP_FIXED_GAIN_USD * open_count
                    elif open_count == 1:
                        # Cas rare : le seul ticket non protégé
                        t = unprotected[0]
                        entry_price = t.get("entry_price", 0)
                        if entry_price > 0:
                            pos = self._get_pos(t["ticket"])
                            if pos:
                                sym = mt5.symbol_info(pos.symbol)
                                be_price = round(entry_price, sym.digits if sym else 2)
                                if self.bridge.modify_sl(t["ticket"], be_price, f"[BE LATE @{be_price}]"):
                                    t["be_active"] = True
                                    t["be_sl"] = be_price
                                    log.info(f"===== | {mt5_comment} | BE | =====")
                                    log.info(f"{action} {symbol} | SL @{be_price} | LATE PROTÉGÉ")

            if entry.get("_be_activated"):
                target_gain = entry.get("_target_gain", 0)
                if target_gain > 0:
                    total_pnl = 0.0
                    active_tickets = []
                    for t in entry.get("tickets", []):
                        pos = self._get_pos(t["ticket"])
                        if pos:
                            total_pnl += pos.profit
                            active_tickets.append(t)
                    if total_pnl >= target_gain:
                        log.info(f"===== | {mt5_comment} | TP-FIXED | =====")
                        ticket_list = ", ".join([f"#{t['ticket']}" for t in active_tickets])
                        log.info(f"{action} {symbol} | P&L: {total_pnl:+.2f}$ | {len(active_tickets)} POS")
                        log.info(f"{ticket_list}")
                        for t in active_tickets:
                            if not t.get("_tp_fixed_closed"):
                                self.bridge.close_position(t["ticket"], "TP-FIXED")
                                t["_tp_fixed_closed"] = True
                        send_alert_sync(
                            f"🎯 {action} {symbol} | TP FIXED\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"P&L total: +{total_pnl:.2f}$\n"
                            f"Positions: {len(active_tickets)}\n"
                            f"Ticket(s): {ticket_list}\n"
                            f"Canal: {canal}"
                        )
                        # ✅ Retirer immédiatement l'entry de self.active
                        with self._lock:
                            if entry in self.active:
                                self.active.remove(entry)
                        continue

    # ★★★ FIX : Pas de cache pour les ordres pending ★★★
    # Le cache de 1s + délai MT5 = la limit peut être invisible quand le BE se déclenche.
    # On query MT5 directement à chaque cycle.
    def _resolve_order(self, order_ticket: int, symbol: str):
        since = datetime.now(timezone.utc) - timedelta(days=1)
        deals = mt5.history_deals_get(symbol=symbol, from_time=since)
        if deals is None or len(deals) == 0:
            return None

        for deal in reversed(deals):
            if deal.order == order_ticket and deal.entry == mt5.DEAL_ENTRY_IN:
                positions = mt5.positions_get(ticket=deal.position_id)
                if positions:
                    return positions[0]

        return None

# =============================================================
# CONFLIT & EXÉCUTION (avec SL paramétrable)
# =============================================================
def check_conflict(signal: dict, bridge: MT5Bridge, manager) -> bool:
    if DEMO_MODE:
        return False
    symbol = signal["symbol"]
    new_action = signal["action"]
    opposite = "SELL" if new_action == "BUY" else "BUY"
    conflict = False
    positions = mt5.positions_get()
    if positions:
        for pos in positions:
            if pos.magic != MAGIC_NUMBER:
                continue
            pos_dir = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
            if pos_dir == opposite:
                conflict = True
                break
    if not conflict:
        for entry in manager.active:
            if entry["signal"]["symbol"] == symbol and entry["signal"]["action"] == opposite:
                conflict = True
                break
    if not conflict:
        return False
    log.warning(f"<<<<< WARNING >>>>> CONFLIT {symbol} : entrant={new_action} existant={opposite}")
    to_remove = []
    for entry in manager.active:
        if entry["signal"]["symbol"] != symbol:
            continue
        for o in entry.get("orders", []):
            bridge.cancel_order(o["order"])
        to_remove.append(entry)
    for e in to_remove:
        if e in manager.active:
            manager.active.remove(e)
    bridge.close_all(symbol=symbol)
    return True

def execute_signal(signal: dict, bridge: MT5Bridge, manager, tracker):
    action = signal["action"]
    symbol = signal["symbol"]
    zone_low = signal["zone_low"]
    zone_mid = signal["zone_mid"]
    zone_high = signal["zone_high"]

    all_tps = signal["tps"]
    if not all_tps:
        log.warning(f"Signal ignoré — aucun TP trouvé ({symbol} {action})")
        return

    if action == "SELL":
        all_tps = sorted(all_tps, reverse=True)
    else:
        all_tps = sorted(all_tps)

    if len(all_tps) == 1:
        tp_trigger_idx = 0
    else:
        if 3 > len(all_tps):
            tp_trigger_idx = len(all_tps) - 1
        else:
            tp_trigger_idx = 2

    tp_final = all_tps[-1]
    tp3 = all_tps[tp_trigger_idx]
    sl = signal["sl"]
    expiry = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MIN)

    if not DEMO_MODE and check_conflict(signal, bridge, manager):
        return

    sym_info = bridge._sym(symbol)
    if sym_info is None:
        log.error(f"Signal rejeté — symbole introuvable dans MT5: {symbol}")
        return

    current = bridge.current_price(sym_info.name, action)
    if current is None:
        log.error(f"Signal rejeté — prix indisponible pour {sym_info.name} (action={action})")
        return

    avg_entry = (zone_low + zone_high) / 2
    if not SignalParser._validate_sl(action, avg_entry, sl):
        log.error(f"Signal rejeté — SL {sl} invalide pour {action} (entry={avg_entry})")
        return

    tick = mt5.symbol_info_tick(sym_info.name)
    if tick and not DEMO_MODE:
        spread_points = abs(tick.ask - tick.bid)
        spread_pips = spread_points / sym_info.point
        if spread_pips > MAX_SPREAD_POINTS:
            log.warning(f"Signal ignoré — spread trop large: {spread_pips:.0f} pts (max={MAX_SPREAD_POINTS}) | {sym_info.name}")
            return

    total_signals = len(manager.active)
    if total_signals >= MAX_POSITIONS:
        log.warning(f"Signal ignoré — max signaux atteint ({total_signals}/{MAX_POSITIONS}) | {symbol} {action}")
        return

    in_zone = zone_low <= current <= zone_high
    between_zone_tp1 = False

    canal = signal.get("source_channel", "Inconnu")
    mode = "DEMO" if DEMO_MODE else "LIVE"
    ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
    cas_num = 1 if in_zone else 2
    mt5_comment = f"CH{ch_num}-C{cas_num}"

    orders, tickets = [], []
    is_single_price = signal.get("is_single_price", False)

    # ── Prix unique ──
    if is_single_price and len(all_tps) >= 1:
        entry_price = zone_mid
        tp1 = all_tps[0]
        sl_price = sl
        scenario = None

        # Scénarios selon documentation v9 :
        # S1: SL < prix < entry → MARKET
        # S2: entry < prix < TP1 → LIMIT (BUY) | TP1 < prix < entry → LIMIT (SELL)
        # S3: sinon → ANNULÉ
        if action == "BUY":
            scenario_1 = sl_price < current < entry_price
            scenario_2 = entry_price < current < tp1
        else:
            scenario_1 = entry_price < current < sl_price
            scenario_2 = tp1 < current < entry_price

        if scenario_1:
            scenario = 1
        elif scenario_2:
            scenario = 2
        else:
            scenario = 3

        mt5_comment_pu = f"CH{ch_num}-PU-S{scenario}"

        if scenario == 3:
            log.info(f"===== | {mt5_comment_pu} | ANNULÉ | =====")
            log.info(f"{action} {signal['symbol']} | prix={current} hors zone S2 | entry={entry_price} TP1={tp1} SL={sl_price}")
            return
        log.debug(f"PRIX UNIQUE — Scénario {scenario} | entry={entry_price} TP1={tp1} prix={current}")

        unique_lot = LOT_UNIQUE_TRADE

        # ★★★ Limitation SL pour prix unique avec SL_PRIX_UNIQUE ★★★
        if action == "BUY":
            sl = max(sl, entry_price - SL_PRIX_UNIQUE)
        else:
            sl = min(sl, entry_price + SL_PRIX_UNIQUE)

        if scenario == 1:
            log.debug(f"  → MARKET {action} @{current} lot={unique_lot} TP={tp_final} SL={sl}")
            try:
                t = bridge.place_market_order(signal, unique_lot, tp=tp_final, sl=sl, comment=mt5_comment_pu)
            except Exception as e:
                log.error(f"  MARKET EXCEPTION: {e}")
                t = None
            if t:
                tickets.append({
                    "ticket": t, "lot": unique_lot, "role": "market_single",
                    "entry_price": current, "tp_index": tp_trigger_idx, "tp_target": tp3,
                    "tp3": tp3, "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                    "be_active": False, "be_sl": 0,
                })
                log.debug(f"  ✓ MARKET #{t} @{current} TP={tp_final}")
                send_alert_sync(
                    f"🟢 {action} {symbol} | {mt5_comment_pu}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"MARKET: @{current} | Lot: {unique_lot}\n"
                    f"TICKET: {t}\n"
                    f"TP: {tp_final} | SL: {sl}\n"
                    f"Canal: {canal}"
                )
            else:
                log.error("  ✗ MARKET échoué")

        elif scenario == 2:
            log.debug(f"  → LIMIT {action} @{entry_price} lot={unique_lot} TP={tp_final} SL={sl}")
            o = bridge.place_limit_order(signal, unique_lot, entry_price, tp_final, expiry, comment=mt5_comment_pu)
            if o:
                orders.append({
                    "order": o, "lot": unique_lot, "price": entry_price, "role": "limit_single",
                    "tp_index": tp_trigger_idx, "tp_target": tp3, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.debug(f"  ✓ LIMIT #{o} @{entry_price} TP={tp_final}")
                send_alert_sync(
                    f"🔵 {action} {symbol} | {mt5_comment_pu}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"LIMIT: @{entry_price} | Lot: {unique_lot}\n"
                    f"TP: {tp_final} | SL: {sl}\n"
                    f"Canal: {canal}"
                )
            else:
                log.error(f"  ✗ LIMIT échoué @{entry_price}")

        if not orders and not tickets:
            log.error("Aucun ordre placé (prix unique).")
            return

        entry = {
            "signal": signal,
            "orders": orders,
            "tickets": tickets,
            "expiry": expiry,
            "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "_signal_id": f"{symbol}_{action}_{int(time.time())}",
            "_expected_positions": 1,
            "_mt5_comment": mt5_comment_pu,
        }
        manager.register(entry)
        tracker.log_trade_open(entry)

        log.info(f"===== | {mt5_comment_pu} | =====")
        log.info(f"{action} {symbol} | Entrée: {entry_price} | Prix: {current} | TPf: {tp_final} SL: {sl}")
        parts = []
        for t in tickets:
            parts.append(f"MKT #{t['ticket']} @{t['entry_price']} lot{t['lot']}")
        for o in orders:
            parts.append(f"LIMIT #{o['order']} @{o['price']} lot{o['lot']}")
        if parts:
            log.info(f"  {' | '.join(parts)}")
        return

    # ── Signal avec zone ──
    if in_zone:
        vol_min = sym_info.volume_min
        lot_market = max(round(LOT_SIZE * 0.5, 2), vol_min)
        lot_limit = max(round(LOT_SIZE * 0.5, 2), vol_min)
        log.debug(f"CAS 1 lots → market={lot_market} limit={lot_limit} (vol_min={vol_min})")

        log.debug(f"CAS 1 → MARKET {action} lot={lot_market} TP={tp_final} SL={sl}")
        try:
            t = bridge.place_market_order(signal, lot_market, tp=tp_final, sl=sl, comment=mt5_comment)
        except Exception as e:
            log.error(f"MARKET EXCEPTION: {e}")
            t = None
        market_entry_price = current
        if t:
            tickets.append({
                "ticket": t, "lot": lot_market, "role": "market_cas1",
                "entry_price": market_entry_price, "tp_index": tp_trigger_idx, "tp_target": tp3,
                "tp3": tp3, "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                "be_active": False, "be_sl": 0,
            })
            log.debug(f"  ✓ MARKET #{t} @{market_entry_price} TP={tp_final}")
        else:
            log.error("  ✗ MARKET échoué")

        if action == "BUY":
            limit_price = round((sl + zone_low) / 2, sym_info.digits)
        else:
            limit_price = round((zone_high + sl) / 2, sym_info.digits)

        log.debug(f"CAS 1 → LIMIT {action} @{limit_price} lot={lot_limit} TP={tp_final} SL={sl}")
        o = bridge.place_limit_order(signal, lot_limit, limit_price, tp_final, expiry, comment=mt5_comment)
        if o:
            orders.append({
                "order": o, "lot": lot_limit, "price": limit_price, "role": "limit_cas1",
                "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                "_market_entry_price": market_entry_price,
            })
            log.debug(f"  ✓ LIMIT #{o} @{limit_price} TP={tp_final}")
        else:
            log.error(f"  ✗ LIMIT échoué @{limit_price}")

        # ★★★ Ajustement du SL pour CAS 1 avec SL_PLUS_PROCHE ★★★
        entry_prices = []
        if t:
            entry_prices.append(market_entry_price)
        if o:
            entry_prices.append(limit_price)
        sl = adjust_sl_to_nearest_entry(entry_prices, sl, action, SL_PLUS_PROCHE)
        if t:
            bridge.modify_sl(t, sl, f"CAS1 SL ajusté @{sl}")
        if o:
            bridge.modify_pending_order(o, sl, tp_final, f"CAS1 SL ajusté @{sl}")

        # Alerte CAS 1
        market_line = f"MARKET: @{market_entry_price} | Lot: {lot_market}" if t else "MARKET: ÉCHOUÉ"
        ticket_line = f"TICKET: {t}" if t else ""
        limit_line = f"LIMIT : @{limit_price} | Lot: {lot_limit}" if o else "LIMIT : ÉCHOUÉ"

        alert_lines = [
            f"🟢 {action} {symbol} | {mt5_comment}",
            "━━━━━━━━━━━━━━━━━━",
            market_line,
        ]
        if ticket_line:
            alert_lines.append(ticket_line)
        alert_lines.append(limit_line)
        alert_lines.append(f"TP: {tp_final} | SL: {sl}")
        alert_lines.append(f"Canal: {canal}")
        send_alert_sync("\n".join(alert_lines))

    else:
        tp1 = all_tps[0]
        tp2 = all_tps[1] if len(all_tps) >= 2 else None

        # ✅ CAS 2-a : prix entre TP1 et zone
        if action == "BUY":
            between_zone_tp1 = zone_high < current < tp1
        else:
            between_zone_tp1 = tp1 < current < zone_low

        # ✅ CAS 2-b : prix entre TP1 et TP2
        between_tp1_tp2 = False
        if tp2 is not None:
            if action == "BUY":
                between_tp1_tp2 = tp1 < current < tp2
            else:
                between_tp1_tp2 = tp2 < current < tp1

        if between_zone_tp1:
            mt5_comment = f"CH{ch_num}-C2-S1"
            lot_per_order = max(round(LOT_SIZE / 2, 2), sym_info.volume_min)
            other_limit = zone_low if action == "BUY" else zone_high
            log.debug(f"CAS 2-a → Prix entre zone et TP1 ({zone_low}-{zone_high} ↔ {tp1}) | prix={current}")

            log.debug(f"  → MARKET {action} @{current} lot={lot_per_order} TP={tp_final} SL={sl}")
            try:
                t = bridge.place_market_order(signal, lot_per_order, tp=tp_final, sl=sl, comment=mt5_comment)
            except Exception as e:
                log.error(f"  MARKET EXCEPTION: {e}")
                t = None
            if t:
                tickets.append({
                    "ticket": t, "lot": lot_per_order, "role": "market_cas2",
                    "entry_price": current, "tp_index": tp_trigger_idx, "tp_target": tp3,
                    "tp3": tp3, "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                    "be_active": False, "be_sl": 0,
                })
                log.debug(f"  ✓ MARKET #{t} @{current} TP={tp_final}")
            else:
                log.error("  ✗ MARKET échoué")

            log.debug(f"  → LIMIT {action} @{other_limit} lot={lot_per_order} TP={tp_final} SL={sl}")
            o = bridge.place_limit_order(signal, lot_per_order, other_limit, tp_final, expiry, comment=mt5_comment)
            if o:
                orders.append({
                    "order": o, "lot": lot_per_order, "price": other_limit, "role": "limit_cas2",
                    "tp_index": tp_trigger_idx, "tp_target": tp3, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.debug(f"  ✓ LIMIT #{o} @{other_limit} TP={tp_final}")
            else:
                log.error(f"  ✗ LIMIT échoué @{other_limit}")

            # ★★★ Ajustement du SL pour CAS 2a avec SL_PLUS_PROCHE ★★★
            entry_prices = []
            if t:
                entry_prices.append(current)
            if o:
                entry_prices.append(other_limit)
            sl = adjust_sl_to_nearest_entry(entry_prices, sl, action, SL_PLUS_PROCHE)
            if t:
                bridge.modify_sl(t, sl, f"CAS2a SL ajusté @{sl}")
            if o:
                bridge.modify_pending_order(o, sl, tp_final, f"CAS2a SL ajusté @{sl}")

            # Alerte CAS 2a
            market_line = f"MARKET: @{current} | Lot: {lot_per_order}" if t else "MARKET: ÉCHOUÉ"
            ticket_line = f"TICKET: {t}" if t else ""
            limit_line = f"LIMIT : @{other_limit} | Lot: {lot_per_order}" if o else "LIMIT : ÉCHOUÉ"
            alert_lines = [
                f"🟢 {action} {symbol} | {mt5_comment}",
                "━━━━━━━━━━━━━━━━━━",
                market_line,
            ]
            if ticket_line:
                alert_lines.append(ticket_line)
            alert_lines.append(limit_line)
            alert_lines.append(f"TP: {tp_final} | SL: {sl}")
            alert_lines.append(f"Canal: {canal}")
            send_alert_sync("\n".join(alert_lines))

        elif between_tp1_tp2:
            mt5_comment = f"CH{ch_num}-C2-S2"
            lot_per_order = max(round(LOT_SIZE / 2, 2), sym_info.volume_min)
            if action == "BUY":
                price_1 = zone_high
                price_2 = zone_low
            else:
                price_1 = zone_low
                price_2 = zone_high

            log.debug(f"CAS 2-b → prix entre TP1 et TP2 ({tp1}-{tp2}) | prix={current} → 2 × LIMIT")

            log.debug(f"  → LIMIT_1 {action} @{price_1} lot={lot_per_order} TP={tp_final} SL={sl}")
            o1 = bridge.place_limit_order(signal, lot_per_order, price_1, tp_final, expiry, comment=mt5_comment)
            if o1:
                orders.append({
                    "order": o1, "lot": lot_per_order, "price": price_1, "role": "limit_1",
                    "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.debug(f"  ✓ LIMIT_1 #{o1} @{price_1} TP={tp_final}")
            else:
                log.error(f"  ✗ LIMIT_1 échoué @{price_1}")

            log.debug(f"  → LIMIT_2 {action} @{price_2} lot={lot_per_order} TP={tp_final} SL={sl}")
            o2 = bridge.place_limit_order(signal, lot_per_order, price_2, tp_final, expiry, comment=mt5_comment)
            if o2:
                orders.append({
                    "order": o2, "lot": lot_per_order, "price": price_2, "role": "limit_2",
                    "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.debug(f"  ✓ LIMIT_2 #{o2} @{price_2} TP={tp_final}")
            else:
                log.error(f"  ✗ LIMIT_2 échoué @{price_2}")

            # ★★★ Ajustement du SL pour CAS 2b avec SL_PLUS_PROCHE ★★★
            entry_prices = []
            if o1:
                entry_prices.append(price_1)
            if o2:
                entry_prices.append(price_2)
            sl = adjust_sl_to_nearest_entry(entry_prices, sl, action, SL_PLUS_PROCHE)
            if o1:
                bridge.modify_pending_order(o1, sl, tp_final, f"CAS2b SL ajusté @{sl}")
            if o2:
                bridge.modify_pending_order(o2, sl, tp_final, f"CAS2b SL ajusté @{sl}")

            # Alerte CAS 2b
            l1_str = f"LIMIT_1: @{price_1} | Lot: {lot_per_order}" if o1 else "LIMIT_1: ÉCHOUÉ"
            l2_str = f"LIMIT_2: @{price_2} | Lot: {lot_per_order}" if o2 else "LIMIT_2: ÉCHOUÉ"
            send_alert_sync(
                f"🔵 {action} {symbol} | {mt5_comment}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{l1_str}\n"
                f"{l2_str}\n"
                f"TP: {tp_final} | SL: {sl}\n"
                f"Canal: {canal}"
            )

        else:
            # Prix hors zone (ni entre zone-TP1, ni entre TP1-TP2)
            log.debug(f"CAS 2 — prix hors zone → ANNULÉ | prix={current} | TP1={tp1} TP2={tp2}")
            return

    if not orders and not tickets:
        log.error("Aucun ordre placé.")
        return

    log.info(f"===== | {mt5_comment} | =====")
    zone_str = f"{zone_low}-{zone_high}"
    log.info(f"{action} {symbol} | Zone: {zone_str} | Prix: {current} | TPf: {tp_final} SL: {sl}")
    parts = []
    for t in tickets:
        role = t['role']
        if 'market' in role:
            label = 'MKT'
        elif 'limit_1' in role or role == 'limit_single' or role == 'limit_cas1':
            label = 'LIMIT_1'
        elif 'limit_2' in role or role == 'limit_cas2':
            label = 'LIMIT_2'
        else:
            label = role.upper()
        parts.append(f"{label} #{t['ticket']} @{t['entry_price']} lot{t['lot']}")
    for o in orders:
        role = o['role']
        if 'market' in role:
            label = 'MKT'
        elif 'limit_1' in role or role == 'limit_single' or role == 'limit_cas1':
            label = 'LIMIT_1'
        elif 'limit_2' in role or role == 'limit_cas2':
            label = 'LIMIT_2'
        else:
            label = role.upper()
        parts.append(f"{label} #{o['order']} @{o['price']} lot{o['lot']}")
    if parts:
        log.info(f"  {' | '.join(parts)}")

    entry = {
        "signal": signal,
        "orders": orders,
        "tickets": tickets,
        "expiry": expiry,
        "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "_signal_id": f"{symbol}_{action}_{int(time.time())}",
        "_expected_positions": 2 if (in_zone or between_zone_tp1 or len(orders) >= 2) else 1,
        "_mt5_comment": mt5_comment,
    }

    manager.register(entry)
    tracker.log_trade_open(entry)

# =============================================================
# QUICK ALERT (CORRIGÉE)
# =============================================================
def _qa_key(symbol: str, action: str, channel_name: str = "") -> str:
    clean_channel = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f\u00a0]', '', channel_name)
    ch_num = CHANNEL_NUM_MAP.get(clean_channel, CHANNEL_NUM_MAP.get(clean_channel.lstrip("-"), "?"))
    return f"CH{ch_num}_{symbol}_{action}"

def execute_quick_alert(signal: dict, bridge: MT5Bridge, manager: TradeManager,
                        tracker: PerformanceTracker, quick_alerts: dict):
    action = signal["action"]
    symbol = signal["symbol"]
    sl = signal.get("sl")
    entry_price = signal["zone_mid"]

    total_signals = len(manager.active)
    if total_signals >= MAX_POSITIONS:
        log.warning(f"Quick Alert ignorée — max signaux atteint ({total_signals}/{MAX_POSITIONS}) | {symbol} {action}")
        return

    sym_info = bridge._sym(symbol)
    if not sym_info:
        log.error(f"Quick alert rejeté — symbole introuvable: {symbol}")
        return
    current = bridge.current_price(sym_info.name, action)
    if current is None:
        log.error(f"Quick alert rejeté — prix indisponible: {symbol}")
        return

    canal = signal.get("source_channel", "Inconnu")
    clean_canal = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f\u00a0]', '', canal)
    ch_num = CHANNEL_NUM_MAP.get(clean_canal, CHANNEL_NUM_MAP.get(clean_canal.lstrip("-"), "?"))
    expiry = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MIN)

    # Utiliser le TP fourni par le parser s'il existe
    if signal.get("tps") and len(signal["tps"]) > 0:
        default_tp = signal["tps"][0]
        log.debug(f"Quick Alert : TP fourni par le parser = {default_tp}")
    else:
        sl_offset = float(os.getenv("QUICK_ALERT_SL_OFFSET", "10.0"))
        if action == "BUY":
            default_tp = entry_price + sl_offset
        else:
            default_tp = entry_price - sl_offset
        default_tp = round(default_tp, 2)
        log.debug(f"Quick Alert : TP calculé (fallback) = {default_tp}")

    if sl is None:
        sl_offset = float(os.getenv("QUICK_ALERT_SL_OFFSET", "10.0"))
        if action == "BUY":
            sl = entry_price - sl_offset
        else:
            sl = entry_price + sl_offset
        log.debug(f"Quick Alert : SL manquant, calculé = {sl}")

    # Ajuster SL/TP pour les rendre valides
    if action == "BUY":
        if sl >= entry_price:
            sl = entry_price - 10.0
            log.warning(f"Quick Alert : SL ajusté à {sl} (doit être < entry)")
        if default_tp <= entry_price:
            default_tp = entry_price + 10.0
            log.warning(f"Quick Alert : TP ajusté à {default_tp} (doit être > entry)")
    else:  # SELL
        if sl <= entry_price:
            sl = entry_price + 10.0
            log.warning(f"Quick Alert : SL ajusté à {sl} (doit être > entry)")
        if default_tp >= entry_price:
            default_tp = entry_price - 10.0
            log.warning(f"Quick Alert : TP ajusté à {default_tp} (doit être < entry)")

    # Déterminer les zones
    if action == "SELL":
        in_market_zone = entry_price <= current <= sl
        in_limit_zone = entry_price - 3 <= current < entry_price
    else:
        in_market_zone = sl <= current <= entry_price
        in_limit_zone = entry_price < current <= entry_price + 3

    log.debug(f"Quick Alert : current={current}, entry={entry_price}, sl={sl}, tp={default_tp}, "
              f"in_market={in_market_zone}, in_limit={in_limit_zone}")

    if not in_market_zone and not in_limit_zone:
        log.debug(f"Quick Alert ignorée : prix {current} hors zones")
        return

    key = _qa_key(symbol, action, canal)
    if key in quick_alerts and quick_alerts[key]:
        existing = quick_alerts[key][0]
        existing_ticket = existing.get("ticket")
        log.debug(f"Quick Alert déjà existante pour {key} → mise à jour")
        if existing.get("is_limit", False):
            order = mt5.orders_get(ticket=existing_ticket)
            if order:
                bridge.modify_pending_order(existing_ticket, sl, default_tp, "[QA-UPDATE-SL-TP]")
                log.debug(f"✓ SL/TP de l'ordre pending #{existing_ticket} mis à jour")
                existing["signal"]["sl"] = sl
                return
        else:
            pos = mt5.positions_get(ticket=existing_ticket)
            if pos:
                bridge.modify_sl_tp(existing_ticket, sl, default_tp, "[QA-UPDATE-SL-TP]")
                log.debug(f"✓ SL/TP de la position #{existing_ticket} mis à jour")
                existing["signal"]["sl"] = sl
                return
            else:
                log.debug("Quick Alert existante introuvable → nouvelle alerte")

    # Log standard pour Quick Alert
    mt5_comment_qa = f"CH{ch_num}-QA"
    log.info(f"===== | {mt5_comment_qa} | =====")
    log.info(f"{action} {symbol} | Entrée: {entry_price} | TPf: {default_tp} SL: {sl}")

    orders = []
    tickets = []
    order_ticket = None
    is_limit_order = False

    if in_market_zone:
        log.debug(f"Quick Alert MARKET {action} {symbol} @{current} SL={sl}, TP={default_tp}")
        try:
            t = bridge.place_market_order(signal, LOT_UNIQUE_TRADE, tp=default_tp, sl=sl, comment=f"CH{ch_num}-AL")
        except Exception as e:
            log.error(f"Quick alert MARKET exception: {e}")
            t = None
        if t:
            tickets.append({
                "ticket": t,
                "lot": LOT_UNIQUE_TRADE,
                "role": "quick_market",
                "entry_price": current,
                "tp_index": 0,
                "tp_target": default_tp,
                "tp3": default_tp,
                "tp_final": default_tp,
                "sl_step": 0,
                "trail_active": False,
                "be_active": False,
                "be_sl": 0,
            })
            order_ticket = t
            log.info(f"  MKT #{t} @{current} lot{LOT_UNIQUE_TRADE}")
            log.debug(f"✓ QUICK MARKET #{t}")
            send_alert_sync(
                f"⚡ {action} {symbol} | QUICK ALERT\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Type: MARKET @{current} | Lot: {LOT_UNIQUE_TRADE}\n"
                f"Ticket : #{t}\n"
                f"TP: {default_tp} | SL: {sl}\n"
                f"Canal: {canal}"
            )
        else:
            log.error("✗ QUICK MARKET échoué")
            return
    else:
        log.debug(f"Quick Alert LIMIT {action} {symbol} @{entry_price} SL={sl}, TP={default_tp}")
        try:
            o = bridge.place_limit_order(signal, LOT_UNIQUE_TRADE, entry_price, default_tp, expiry, comment=f"CH{ch_num}-AL")
        except Exception as e:
            log.error(f"Quick alert LIMIT exception: {e}")
            o = None
        if o:
            orders.append({
                "order": o,
                "lot": LOT_UNIQUE_TRADE,
                "price": entry_price,
                "role": "quick_limit",
                "tp_index": 0,
                "tp_target": default_tp,
                "tp3": default_tp,
                "tp_final": default_tp,
                "sl_step": 0,
                "trail_active": False,
            })
            order_ticket = o
            is_limit_order = True
            log.info(f"  LIMIT #{o} @{entry_price} lot{LOT_UNIQUE_TRADE}")
            log.debug(f"✓ QUICK LIMIT #{o}")
            send_alert_sync(
                f"⚡ {action} {symbol} | QUICK ALERT\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Type: LIMIT @{entry_price} | Lot: {LOT_UNIQUE_TRADE}\n"
                f"Ticket : #{o}\n"
                f"TP: {default_tp} | SL: {sl}\n"
                f"Canal: {canal}"
            )
        else:
            log.error("✗ QUICK LIMIT échoué")
            return

    entry = {
        "signal": signal,
        "orders": orders,
        "tickets": tickets,
        "expiry": expiry,
        "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "_is_quick_alert": True,
        "_signal_id": f"{symbol}_{action}_{int(time.time())}_QA",
        "_expected_positions": 1,
        "_mt5_comment": f"CH{ch_num}-AL",
    }
    manager.register(entry)

    if key not in quick_alerts:
        quick_alerts[key] = []
    quick_alerts[key].append({
        "entry": entry,
        "signal": signal,
        "ticket": order_ticket,
        "is_limit": is_limit_order,
        "entry_price": entry_price,
        "time": datetime.now(timezone.utc),
    })
    log.debug(f"Quick Alert enregistré: {key}")

def merge_quick_alert(qa: dict, key: str, full_signal: dict,
                      bridge: MT5Bridge, manager: TradeManager,
                      tracker: PerformanceTracker, quick_alerts: dict):
    qa_ticket   = qa["ticket"]
    qa_is_limit = qa["is_limit"]
    entry       = qa["entry"]
    real_sl     = full_signal["sl"]
    tp_final    = full_signal["tps"][-1] if full_signal["tps"] else 0

    if qa_is_limit:
        pos   = manager._resolve_order(qa_ticket, full_signal["symbol"])
        order = mt5.orders_get(ticket=qa_ticket)
        if not pos and not order:
            since = datetime.now(timezone.utc) - timedelta(minutes=30)
            deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
            sl_hit = False
            if deals:
                for deal in reversed(deals):
                    if deal.position_id == qa_ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
                        if deal.reason == mt5.DEAL_REASON_SL:
                            sl_hit = True
                        break
            if sl_hit:
                log.info(f"MERGE: Quick alert #{qa_ticket} SL touché → signal complet ignoré")
            else:
                log.info(f"MERGE: Quick alert #{qa_ticket} expiré/annulé → exécuter signal complet")
                execute_signal(full_signal, bridge, manager, tracker)
            if key in quick_alerts and qa in quick_alerts[key]:
                quick_alerts[key].remove(qa)
                if not quick_alerts[key]:
                    del quick_alerts[key]
            return
    else:
        pos = mt5.positions_get(ticket=qa_ticket)
        if not pos:
            since = datetime.now(timezone.utc) - timedelta(minutes=30)
            deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
            sl_hit = tp_hit = False
            if deals:
                for deal in reversed(deals):
                    if deal.symbol == full_signal["symbol"] and (
                        deal.position_id == qa_ticket or deal.order == qa_ticket
                    ):
                        if deal.entry == mt5.DEAL_ENTRY_OUT:
                            if deal.reason == mt5.DEAL_REASON_SL:
                                sl_hit = True
                            elif deal.reason == mt5.DEAL_REASON_TP:
                                tp_hit = True
                            break
            if sl_hit:
                log.info(f"MERGE: Quick alert #{qa_ticket} SL touché → signal complet ignoré")
            elif tp_hit:
                log.info(f"MERGE: Quick alert #{qa_ticket} TP touché → signal complet ignoré")
            else:
                log.info(f"MERGE: Quick alert #{qa_ticket} fermé (autre raison) → exécuter signal complet")
                execute_signal(full_signal, bridge, manager, tracker)
            if key in quick_alerts and qa in quick_alerts[key]:
                quick_alerts[key].remove(qa)
                if not quick_alerts[key]:
                    del quick_alerts[key]
            return

    if not qa_is_limit:
        log.info(f"MERGE: Position #{qa_ticket} ouverte → SL/TP + LIMIT")
        bridge.modify_sl_tp(qa_ticket, real_sl, tp_final, "[MERGE-SL-TP]")
        for t in entry["tickets"]:
            if t["ticket"] == qa_ticket:
                if len(full_signal["tps"]) == 1:
                    tp_trigger_idx = 0
                else:
                    tp_trigger_idx = 2 if 3 <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
                t["tp_final"]  = tp_final
                t["tp_target"] = full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final
                t["tp3"]       = t["tp_target"]
                t["tp_index"]  = tp_trigger_idx
                break
        _place_merge_limit(full_signal, bridge, entry, real_sl, tp_final)
        entry["signal"]           = full_signal
        entry["_is_quick_alert"]  = False
    else:
        # Vérifier si le limit QA a été rempli entre-temps
        resolved_pos = manager._resolve_order(qa_ticket, full_signal["symbol"])
        if resolved_pos:
            # ★ Limit déjà rempli → créer ticket + modifier SL/TP sur la position
            log.info(f"MERGE: LIMIT #{qa_ticket} rempli → SL/TP + LIMIT")
            if len(full_signal["tps"]) == 1:
                tp_trigger_idx = 0
            else:
                tp_trigger_idx = 2 if 3 <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
            tk = {
                "ticket":       resolved_pos.ticket,
                "lot":          qa["entry"]["orders"][0]["lot"] if qa["entry"]["orders"] else LOT_UNIQUE_TRADE,
                "role":         "quick_limit_filled",
                "entry_price":  resolved_pos.price_open,
                "tp_index":     tp_trigger_idx,
                "tp_target":    full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final,
                "tp3":          full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final,
                "tp_final":     tp_final,
                "sl_step":      0,
                "trail_active": False,
                "be_active":    False,
                "be_sl":        0,
            }
            entry["tickets"].append(tk)
            entry["orders"] = [o for o in entry["orders"] if o["order"] != qa_ticket]
            bridge.modify_sl_tp(resolved_pos.ticket, real_sl, tp_final, "[MERGE-SL-TP]")
            _place_merge_limit(full_signal, bridge, entry, real_sl, tp_final)
            entry["signal"]          = full_signal
            entry["_is_quick_alert"] = False
        else:
            # ★ Limit encore pending → modifier l'ordre pending
            log.info(f"MERGE: LIMIT #{qa_ticket} pending → modif SL/TP + LIMIT")
            if len(full_signal["tps"]) == 1:
                tp_trigger_idx = 0
            else:
                tp_trigger_idx = 2 if 3 <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
            bridge.modify_pending_order(qa_ticket, real_sl, tp_final, "[MERGE-ORD-SL-TP]")
            for o in entry["orders"]:
                if o["order"] == qa_ticket:
                    o["tp_final"]  = tp_final
                    o["tp_target"] = full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final
                    o["tp3"]       = o["tp_target"]
                    o["tp_index"]  = tp_trigger_idx
                    break
            _place_merge_limit(full_signal, bridge, entry, real_sl, tp_final)
            entry["signal"]          = full_signal
            entry["_is_quick_alert"] = False

    if abs(full_signal["zone_high"] - full_signal["zone_low"]) >= 1:
        market_entry_price = None
        for t in entry["tickets"]:
            if t.get("role") == "quick_market":
                market_entry_price = t.get("entry_price")
                break
        if not market_entry_price:
            market_entry_price = entry.get("signal", {}).get("entry", 0)
        if market_entry_price:
            entry["_grade_market_price"] = market_entry_price
            if full_signal["action"] == "BUY":
                entry["_grade_limit_price"] = full_signal["zone_low"]
            else:
                entry["_grade_limit_price"] = full_signal["zone_high"]

    if key in quick_alerts and qa in quick_alerts[key]:
        quick_alerts[key].remove(qa)
        if not quick_alerts[key]:
            del quick_alerts[key]
    log.info(f"MERGE terminé: {full_signal['action']} {full_signal['symbol']}")


def _place_merge_limit(
    full_signal: dict, bridge: MT5Bridge, entry: dict, real_sl: float, tp_final: float
):
    zone_low  = full_signal["zone_low"]
    zone_high = full_signal["zone_high"]
    action    = full_signal["action"]
    if abs(zone_high - zone_low) < 1:
        return
    sym_info = bridge._sym(full_signal["symbol"])
    if not sym_info:
        return
    limit_price = zone_high if action == "SELL" else zone_low
    expiry      = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MIN)
    canal       = full_signal.get("source_channel", "Inconnu")
    ch_num      = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
    log.info(f"===== | CH{ch_num}-MG | LIMIT | =====")
    log.info(f"{action} {full_signal['symbol']} | @{limit_price} lot{LOT_UNIQUE_TRADE}")
    o = bridge.place_limit_order(
        full_signal, LOT_UNIQUE_TRADE, limit_price, tp_final, expiry, comment=f"CH{ch_num}-MG"
    )
    if o:
        if len(full_signal["tps"]) == 1:
            tp_trigger_idx = 0
        else:
            tp_trigger_idx = 2 if 3 <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
        entry["orders"].append({
            "order":      o,
            "lot":        LOT_UNIQUE_TRADE,
            "price":      limit_price,
            "role":       "merge_limit",
            "tp_index":   len(full_signal["tps"]) - 1,
            "tp_target":  tp_final,
            "tp3":        full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final,
            "tp_final":   tp_final,
            "sl_step":    0,
            "trail_active": False,
        })
        log.info(f"  ✓ LIMIT #{o} @{limit_price} lot{LOT_UNIQUE_TRADE}")
    else:
        log.error(f"  ✗ MERGE LIMIT échoué @{limit_price}")

# =============================================================
# MAIN
# =============================================================
def _is_signal_message(text: str) -> bool:
    if re.search(r'\d+\.\d+', text):
        return True
    if "CLOSE" in text.upper():
        return True
    if "BUY" in text.upper() or "SELL" in text.upper():
        return True
    return False

async def heartbeat_loop(manager, tracker):
    """Heartbeat désactivé — pas de messages BOT ACTIF"""
    return

async def main():
    global _main_loop, _alert_client
    _main_loop = asyncio.get_running_loop()
    
    parser = SignalParser()
    bridge = MT5Bridge()
    tracker = PerformanceTracker()
    manager = None

    try:
        if not bridge.connect():
            log.critical("Bot arrêté — corrigez MT5 puis relancez.")
            return

        manager = TradeManager(bridge, tracker)
        await manager.start()

        news_mgr = NewsManager(bridge)
        news_mgr.set_manager(manager)
        await news_mgr.start()

        client = TelegramClient("session_trading", API_ID, API_HASH)
        await client.start()
        _alert_client = client
        log.info("Telegram connecté.")

        asyncio.create_task(heartbeat_loop(manager, tracker))

        _quick_alerts = {}

        chats = []
        channel_names = [
            ("TG_CHANNEL_1", CHANNEL_NAME),
            ("TG_CHANNEL_2", CHANNEL_NAME_2),
            ("TG_CHANNEL_3", CHANNEL_NAME_3),
            ("TG_CHANNEL_4", CHANNEL_NAME_4),
            ("TG_CHANNEL_5", CHANNEL_NAME_5),
            ("TG_CHANNEL_6", CHANNEL_NAME_6),
            ("TG_CHANNEL_7", CHANNEL_NAME_7),
            ("TG_CHANNEL_8", CHANNEL_NAME_8),
            ("TG_CHANNEL_9", CHANNEL_NAME_9),
        ]
        entity_to_name = {}

        for env_name, ch_value in channel_names:
            if not ch_value:
                continue
            try:
                ch_resolved = int(ch_value) if ch_value.lstrip("-").isdigit() else ch_value
                entity = await client.get_entity(ch_resolved)
                title = getattr(entity, "title", ch_value)
                title_clean = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f\u00a0]', '', title)
                if title_clean.strip() == "":
                    title_clean = ch_value
                chats.append(entity)
                entity_to_name[entity.id] = title_clean
                ch_num = int(env_name.replace("TG_CHANNEL_", ""))
                CHANNEL_NUM_MAP[title_clean] = ch_num
                log.info(f"Canal : {title_clean} ({env_name}={ch_value})")
            except Exception as e:
                log.warning(f"Canal introuvable ({env_name}={ch_value}) : {e}")

        @client.on(events.NewMessage(chats=chats))
        async def handler(event):
            text = event.message.text or ""
            chat = await event.get_chat()
            canal_name = entity_to_name.get(chat.id, getattr(chat, "title", "inconnu"))

            if is_spam(text):
                return

            if not _is_signal_message(text):
                return

            # Log brut en DEBUG seulement
            clean_text = text.replace('*', '').replace('\n', ' | ')[:150]
            log.debug(f"[{canal_name}] {clean_text}")

            signal_data = parser.parse(text)
            if signal_data is None:
                return

            signal_data.source_channel = canal_name

            # Log du signal reçu (sans scénario — le vrai scénario est loggé par execute_signal)
            if signal_data.signal_type == "TRADE":
                action = signal_data.direction or "?"
                symbol = signal_data.pair or "?"
                sl = signal_data.sl or 0
                tp_final = signal_data.tp_final or 0
                ch_num = CHANNEL_NUM_MAP.get(canal_name, CHANNEL_NUM_MAP.get(canal_name.lstrip("-"), "?"))

                if signal_data.is_quick_alert:
                    mode = "QA"
                elif signal_data.is_single_price:
                    mode = "PU"
                else:
                    mode = "C"

                mt5_comment = f"CH{ch_num}-{mode}"
                log.info(f">>>>> SIGNAL | {mt5_comment} | {action} {symbol} | TPf: {tp_final} SL: {sl}")

            if signal_data.signal_type == "CLOSE":
                canal = canal_name
                ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), None))
                bridge.close_all(symbol=signal_data.close_symbol, channel_num=ch_num)
                return

            elif signal_data.signal_type == "SL_MOVE":
                log.debug(f"SL MOVE reçu → nouveau SL={signal_data.new_sl}")
                ch_num = CHANNEL_NUM_MAP.get(canal_name, CHANNEL_NUM_MAP.get(canal_name.lstrip("-"), None))
                if ch_num is not None:
                    bridge.update_sl_by_channel(signal_data.new_sl, ch_num)
                    manager.update_pending_orders_sl(ch_num, signal_data.new_sl)
                else:
                    log.warning(f"SL MOVE ignoré : canal inconnu ({canal_name})")
                return

            elif signal_data.signal_type == "TRADE":
                if NEWS_ENABLED and news_mgr.is_blocked():
                    log.debug("[NEWS] Signal ignoré — protection news")
                    return

                blocked, reason = in_blocked_window()
                if blocked:
                    log.debug(f"[{canal_name}] Signal ignoré - Filtre horaire : {reason}")
                    return

                if not manager._check_daily_pnl_limit():
                    log.debug(f"[{canal_name}] Signal ignoré - Limite de P&L quotidien atteinte ({DAILY_PROFIT_LIMIT}$)")
                    return

                sig_dict = signal_data.to_dict()

                if signal_data.is_quick_alert:
                    execute_quick_alert(sig_dict, bridge, manager, tracker, _quick_alerts)
                    return

                key = _qa_key(sig_dict["symbol"], sig_dict["action"], canal_name)
                qa_list = _quick_alerts.get(key, [])
                found_qa = None
                found_idx = -1
                zone_low = sig_dict["zone_low"]
                zone_high = sig_dict["zone_high"]

                for idx, qa in enumerate(qa_list):
                    qa_price = qa["entry_price"]
                    if zone_low - 2 <= qa_price <= zone_high + 2:
                        found_qa = qa
                        found_idx = idx
                        break

                if found_qa is not None:
                    merge_quick_alert(found_qa, key, sig_dict, bridge, manager, tracker, _quick_alerts)
                else:
                    execute_signal(sig_dict, bridge, manager, tracker)

        # Banner
        mode = "🧪 DEMO" if DEMO_MODE else "💰 LIVE"
        log.info("=" * 55)
        log.info(f" TRADINGBOT V9.0.0 — 5 BUG FIXES")
        log.info(f" Mode: {mode}")
        log.info(f" Canaux surveillés : {len(chats)}")
        for env_name, ch_value in channel_names:
            if ch_value:
                log.info(f"  {env_name} : {ch_value}")
        log.info(f" Lot total : {LOT_SIZE} | Lot unique : {LOT_UNIQUE_TRADE}")
        log.info(f" Gain fixe par position : {TP_FIXED_GAIN_USD}$")
        log.info(f" BE déclenché à : {PNL_TRIGGER_USD}$ ou {BE_TP_TRIGGER_PCT*100:.0f}% du TP1")
        log.info(f" Objectif quotidien : {DAILY_PROFIT_LIMIT}$")

        log.info(f" Heartbeat : {HEARTBEAT_INTERVAL_MIN} min")
        log.info(f" SL_PRIX_UNIQUE : {SL_PRIX_UNIQUE}$")
        log.info(f" SL_PLUS_PROCHE : {SL_PLUS_PROCHE}$")
        log.info(f" Filtre horaire : {'ON' if TIME_FILTER_ENABLED else 'OFF'} ({TRADING_START_HOUR}h-{TRADING_END_HOUR}h UTC)")
        log.info(f" Max signaux actifs : {MAX_POSITIONS}")
        log.info("=" * 55)

        await client.run_until_disconnected()

    except Exception as e:
        send_alert_sync(
            f"💥 BOT CRASH !\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Erreur: {type(e).__name__}: {e}\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        log.error(f"CRASH: {e}", exc_info=True)
        raise
    finally:
        if manager:
            manager.stop()
        if news_mgr:
            news_mgr.stop()
        bridge.disconnect()
        tracker.print_final_report()
        log.info("[SHUTDOWN] Bot arrêté proprement.")

if __name__ == "__main__":
    asyncio.run(main())
