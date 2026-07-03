"""
=============================================================
 TELEGRAM → MT5 | Bot Trading
 Version 4.8.6 — COMPLET – NUMÉROTATION DES SIGNAUX
                 LOGS AMÉLIORÉS – TOUTES LES FONCTIONNALITÉS
=============================================================
"""

# ── Auto‑install des dépendances ──
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
from dotenv import load_dotenv

from telethon import TelegramClient, events
import MetaTrader5 as mt5

# ── Forcer le buffer de sortie en mode ligne ──
sys.stdout.reconfigure(line_buffering=True)

# Constantes de filling mode
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
ORDER_FILLING_RETURN = 0
ORDER_FILLING_FOK = 1
ORDER_FILLING_IOC = 2

load_dotenv()

# =============================================================
# COMPTEUR DE SIGNAUX (réinitialisation à minuit UTC)
# =============================================================
_signal_counter = 0
_signal_counter_day = datetime.now(timezone.utc).day
_signal_counter_lock = threading.Lock()

def get_next_signal_number() -> int:
    """Retourne le prochain numéro de signal, réinitialisé à minuit UTC."""
    global _signal_counter, _signal_counter_day
    with _signal_counter_lock:
        now = datetime.now(timezone.utc)
        if now.day != _signal_counter_day:
            _signal_counter = 0
            _signal_counter_day = now.day
        _signal_counter += 1
        return _signal_counter

# ------------------------------------------------------------------
# SUPABASE LOGGER (initialized later)
# ------------------------------------------------------------------
_supa = None
_supa_connected = False

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

# Mapping canal → numéro (pour commentaire MT5 et clé CHx)
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
TRAIL_POINTS = float(os.getenv("TRAIL_POINTS", "200"))
TRAIL_RATIO_R1 = float(os.getenv("TRAIL_RATIO_R1", "2"))
TRAIL_RATIO_R2 = float(os.getenv("TRAIL_RATIO_R2", "4"))
LOT_SIZE = float(os.getenv("LOT_TOTAL", "0.01"))
LOT_UNIQUE_TRADE = float(os.getenv("LOT_UNIQUE_TRADE", "0.01"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
MAX_SPREAD_POINTS = float(os.getenv("MAX_SPREAD_POINTS", "50"))
TP_TRIGGER = int(os.getenv("TP_TRIGGER", "3"))
DEFAULT_ALERT_TP_RR = float(os.getenv("DEFAULT_ALERT_TP_RR", "1.0"))

# === NOUVEAUX PARAMÈTRES ===
TIME_FILTER_ENABLED = os.getenv("TIME_FILTER_ENABLED", "true").lower() == "true"
TRADING_START_HOUR = int(os.getenv("TRADING_START_HOUR", "3"))
TRADING_END_HOUR = int(os.getenv("TRADING_END_HOUR", "20"))
DAILY_PROFIT_LIMIT = float(os.getenv("DAILY_PROFIT_LIMIT", "20.0"))

# === ALERTES TELEGRAM ===
TG_ALERT_CHANNEL = os.getenv("TG_ALERT_CHANNEL", "")

# === GRADE ===
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

OPEN_TP_RR_RATIOS = [float(x) for x in os.getenv("OPEN_TP_RR_RATIOS", "1.0,2.0,3.0").split(",")]
OPEN_TP_COUNT = int(os.getenv("OPEN_TP_COUNT", "3"))
OPEN_TRAIL_AFTER_TP = int(os.getenv("OPEN_TRAIL_AFTER_TP", "1"))

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "1"))
PNL_TRIGGER_USD = float(os.getenv("PNL_TRIGGER_USD", "3.0"))
QUICK_ALERT_SL_OFFSET = float(os.getenv("QUICK_ALERT_SL_OFFSET", "10.0"))

RUNTIME_MINUTES = int(os.getenv("RUNTIME_MINUTES", "60"))
SHUTDOWN_MARGIN_MIN = 5

START_TIME = datetime.now(timezone.utc)
_shutdown_event = asyncio.Event()

# =============================================================
# TELEGRAM ALERTS (thread-safe)
# =============================================================
_alert_client = None
_main_loop = None

def send_alert_sync(message: str):
    if not TG_ALERT_CHANNEL or not _alert_client or not _main_loop:
        return
    coro = _alert_client.send_message(TG_ALERT_CHANNEL, message)
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
    try:
        future.result(timeout=5)
    except Exception as e:
        log.warning(f"[ALERT] Erreur envoi alerte Telegram (sync): {e}")

async def send_alert_async(message: str):
    if not TG_ALERT_CHANNEL or not _alert_client:
        return
    try:
        await _alert_client.send_message(TG_ALERT_CHANNEL, message)
    except Exception as e:
        log.warning(f"[ALERT] Erreur envoi alerte Telegram (async): {e}")

# =============================================================
# HELPERS
# =============================================================
def in_blocked_window() -> tuple[bool, str]:
    if not TIME_FILTER_ENABLED:
        return False, ""
    now = datetime.now(timezone.utc)
    if TRADING_START_HOUR <= now.hour < TRADING_END_HOUR:
        return False, ""
    return True, f"Hors plage {TRADING_START_HOUR}h-{TRADING_END_HOUR}h UTC"

# ------------------------------------------------------------------
# LOGGING avec flush
# ------------------------------------------------------------------
class OrderFilter(logging.Filter):
    HIDE = ["[SPAM]", "[CYCLE]", "[PARSING]", "[PARSING ECHOUÉ]"]
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

# Remplacer le handler console par un qui flush
for handler in log.handlers[:]:
    if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
        log.removeHandler(handler)
flush_handler = FlushStreamHandler(sys.stdout)
flush_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
flush_handler.addFilter(OrderFilter())
log.addHandler(flush_handler)

# ------------------------------------------------------------------
# SUPABASE & TRACKER
# ------------------------------------------------------------------
try:
    from supabase_logger import SupabaseLogger
    _supa = SupabaseLogger()
    _supa_connected = _supa.connect()
except ImportError:
    _supa = None
    _supa_connected = False
    log.warning("supabase_logger non trouvé")

_tracker_available = False
if _tracker_available:
    _tracker = get_tracker(_supa if _supa_connected else None)
    log.info("[TRACK] Module de tracking initialisé")

# ------------------------------------------------------------------
# SIGNAL PARSER — importé depuis signal_parser.py
# ------------------------------------------------------------------
from signal_parser import SignalParser, is_spam, TradeSignal

try:
    from tracking import get_tracker
    _tracker = None
    _tracker_available = True
except ImportError:
    _tracker = None
    _tracker_available = False

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
        log.info("[PERF] Rapport final:")
        summary = self.format_session_summary()
        for line in summary.split("\n"):
            log.info(line)


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
            log.info(f"[NEWS] {len(self._news)} news HIGH impact chargées")
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
                    log.info(f"[NEWS] {news.get('title', '?')} terminé → reprise")
                    break
            if 0 < diff_minutes <= NEWS_CLOSE_MIN:
                if not self._blocked:
                    self._blocked = True
                    log.info(f"[NEWS] {news.get('title', '?')} dans {diff_minutes:.0f} min → fermeture positions")
                    if self.manager:
                        self._close_all()
                    break
            elif NEWS_CLOSE_MIN < diff_minutes <= NEWS_BLOCK_MIN:
                if not self._blocked:
                    self._blocked = True
                    log.info(f"[NEWS] {news.get('title', '?')} dans {diff_minutes:.0f} min → signaux bloqués")
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
                    log.info(f"Symbole résolu : {symbol} → {symbol + sfx}")
                    break
        if info is None and symbol.endswith("m"):
            info = mt5.symbol_info(symbol[:-1])
            if info:
                log.info(f"Symbole résolu : {symbol} → {symbol[:-1]}")
        if info is None:
            all_syms = mt5.symbols_get()
            if all_syms:
                matches = [s for s in all_syms if s.name.upper().startswith(symbol.upper()[:6])]
                if matches:
                    info = matches[0]
                    log.info(f"Symbole trouvé par recherche : {info.name}")
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
                log.info(f"MARKET {action} {sym.name} lot={lot} @{price} ticket#{result.order}")
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
            log.info(f"LIMIT {action} {sym.name} lot={lot} @{price} TP={tp} order#{result.order}")
            return result.order
        return None

    def cancel_order(self, order_ticket: int) -> bool:
        result = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket})
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"{'OK' if ok else 'FAIL'} Annulation #{order_ticket}")
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
            log.info(f"Fermeture #{ticket} ({comment}) P&L={pos.profit:.2f}")
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
            log.info(f"SL modifié #{ticket} → {new_sl} {label}")
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
            log.info(f"SL/TP modifiés #{ticket} → SL={new_sl} TP={new_tp} {label}")
        return ok

    def modify_order_sl_tp(self, order_ticket: int, new_sl: float, new_tp: float, label: str = "") -> bool:
        orders = mt5.orders_get(ticket=order_ticket)
        if not orders:
            return False
        order = orders[0]
        sym = mt5.symbol_info(order.symbol)
        if sym is None:
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
            log.info(f"Order modifié #{order_ticket} → SL={new_sl} TP={new_tp} {label}")
        return ok

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
        orders = mt5.orders_get()
        if orders:
            for order in orders:
                if order.magic != MAGIC_NUMBER:
                    continue
                sym = mt5.symbol_info(order.symbol)
                if not sym:
                    continue
                result = mt5.order_send({
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": order.ticket,
                    "price": order.price_open,
                    "sl": round(new_sl, sym.digits),
                    "tp": order.tp,
                    "type_time": order.type_time,
                    "expiration": order.time_expiration,
                })
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
        log.info(f"SL MOVE appliqué sur {updated} pos/ordres → SL={new_sl}")

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
# CONFLIT & EXÉCUTION
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
    log.warning(f"CONFLIT {symbol} : entrant={new_action} existant={opposite}")
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


# =============================================================
# EXECUTE SIGNAL (modifié)
# =============================================================
def execute_signal(signal: dict, bridge: MT5Bridge, manager, tracker):
    signal_number = get_next_signal_number()
    log.info("=" * 55)
    
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
        if TP_TRIGGER > len(all_tps):
            tp_trigger_idx = len(all_tps) - 1
            log.info(f"TP_TRIGGER ajusté : {TP_TRIGGER} > {len(all_tps)} → utilisation du dernier TP (index {tp_trigger_idx})")
        else:
            tp_trigger_idx = TP_TRIGGER - 1

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

    log_lines = [f"SIGNAL {signal_number} | {action} {symbol} | Canal: {canal} | {mt5_comment}"]
    log_lines.append(f"Zone [{zone_low}–{zone_high}] | Prix {current} | TPs={all_tps} | SL={sl}")

    orders, tickets = [], []
    is_single_price = signal.get("is_single_price", False)

    # ── Prix unique ──
    if is_single_price and len(all_tps) >= 1:
        entry_price = zone_mid
        tp1 = all_tps[0]
        sl_price = sl
        scenario = None

        if action == "BUY":
            scenario_1 = sl_price < current < entry_price
            scenario_2 = entry_price < current < tp1
        else:
            scenario_1 = entry_price < current < sl_price
            scenario_2 = tp1 < current < entry_price

        if len(all_tps) == 1:
            scenario_2 = False

        if scenario_1:
            scenario = 1
        elif scenario_2:
            scenario = 2
        else:
            scenario = 3

        if scenario == 3:
            log.info(f"PRIX UNIQUE — Scénario 3 : prix={current} hors conditions → ANNULÉ")
            return

        mt5_comment_pu = f"CH{ch_num}-PU-S{scenario}"
        unique_lot = LOT_UNIQUE_TRADE

        if scenario == 1:
            log.info(f"  → MARKET {action} @{current} lot={unique_lot} TP={tp_final} SL={sl}")
            try:
                t = bridge.place_market_order(signal, unique_lot, tp=tp_final, comment=mt5_comment_pu)
            except Exception as e:
                log.error(f"  MARKET EXCEPTION: {e}")
                t = None
            if t:
                tickets.append({
                    "ticket": t, "lot": unique_lot, "role": "market_single",
                    "entry_price": current, "tp_index": tp_trigger_idx, "tp_target": tp3,
                    "tp3": tp3, "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log_lines.append(f"ORDER MARKET {action} @{current} | Lot: {unique_lot} | TP: {tp_final} | SL: {sl} | Ticket: #{t}")
                now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                send_alert_sync(
                    f"🟢 {action} {symbol} | {mt5_comment_pu}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"MARKET: @{current} | Lot: {unique_lot}\n"
                    f"TP: {tp_final} | SL: {sl}\n"
                    f"Time: {now_str}\n"
                    f"Canal: {canal}"
                )
            else:
                log.error("  ✗ MARKET échoué")

        elif scenario == 2:
            log.info(f"  → LIMIT {action} @{entry_price} lot={unique_lot} TP={tp_final} SL={sl}")
            o = bridge.place_limit_order(signal, unique_lot, entry_price, tp_final, expiry, comment=mt5_comment_pu)
            if o:
                orders.append({
                    "order": o, "lot": unique_lot, "price": entry_price, "role": "limit_single",
                    "tp_index": tp_trigger_idx, "tp_target": tp3, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log_lines.append(f"ORDER LIMIT {action} @{entry_price} | Lot: {unique_lot} | TP: {tp_final} | SL: {sl} | Ticket: #{o} (pending)")
                now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                send_alert_sync(
                    f"🔵 {action} {symbol} | {mt5_comment_pu}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"LIMIT: @{entry_price} | Lot: {unique_lot}\n"
                    f"TP: {tp_final} | SL: {sl}\n"
                    f"Time: {now_str}\n"
                    f"Canal: {canal}"
                )
            else:
                log.error(f"  ✗ LIMIT échoué @{entry_price}")

        if not orders and not tickets:
            log.error("Aucun ordre placé (prix unique).")
            return

        for line in log_lines:
            log.info(line)

        entry = {
            "signal": signal,
            "orders": orders,
            "tickets": tickets,
            "expiry": expiry,
            "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "_signal_number": signal_number,
        }
        manager.register(entry)
        tracker.log_trade_open(entry)

        supa_trade_id = None
        if _supa_connected and _supa:
            ticket_ids = [t["ticket"] for t in tickets]
            supa_trade_id = _supa.log_trade_open(
                signal=signal,
                entry_price=current if scenario == 1 else entry_price,
                lot_size=unique_lot,
                tickets=ticket_ids,
            )
            entry["_supa_trade_id"] = supa_trade_id

        if _tracker and _supa_connected and supa_trade_id:
            signal_type = "PU"
            enriched = _tracker.enrich_trade_data(signal, current if scenario == 1 else entry_price, unique_lot, sl, tp_final, 0)
            _tracker.update_trade_tracking(supa_trade_id, enriched)
            _tracker.track_open(supa_trade_id, signal, current if scenario == 1 else entry_price, unique_lot, sl, tp_final, signal_type)

        return

    # ── Signal avec zone ──
    if in_zone:
        vol_min = sym_info.volume_min
        lot_market = max(round(LOT_SIZE * 0.5, 2), vol_min)
        lot_limit = max(round(LOT_SIZE * 0.5, 2), vol_min)
        log.info(f"CAS 1 lots → market={lot_market} limit={lot_limit} (vol_min={vol_min})")

        log.info(f"CAS 1 → MARKET {action} lot={lot_market} TP={tp_final} SL={sl}")
        try:
            t = bridge.place_market_order(signal, lot_market, tp=tp_final, comment=mt5_comment)
        except Exception as e:
            log.error(f"MARKET EXCEPTION: {e}")
            t = None
        market_entry_price = current
        if t:
            tickets.append({
                "ticket": t, "lot": lot_market, "role": "market_tp3",
                "entry_price": market_entry_price, "tp_index": tp_trigger_idx, "tp_target": tp3,
                "tp3": tp3, "tp_final": tp_final, "sl_step": 0, "trail_active": False,
            })
            log_lines.append(f"ORDER MARKET {action} @{market_entry_price} | Lot: {lot_market} | TP: {tp_final} | SL: {sl} | Ticket: #{t}")
        else:
            log.error("  ✗ MARKET échoué")

        if action == "BUY":
            limit_price = round((sl + zone_low) / 2, sym_info.digits)
        else:
            limit_price = round((zone_high + sl) / 2, sym_info.digits)

        log.info(f"CAS 1 → LIMIT {action} @{limit_price} lot={lot_limit} TP={tp_final} SL={sl}")
        o = bridge.place_limit_order(signal, lot_limit, limit_price, tp_final, expiry, comment=mt5_comment)
        if o:
            orders.append({
                "order": o, "lot": lot_limit, "price": limit_price, "role": "limit_catch",
                "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                "_market_entry_price": market_entry_price,
            })
            log_lines.append(f"ORDER LIMIT {action} @{limit_price} | Lot: {lot_limit} | TP: {tp_final} | SL: {sl} | Ticket: #{o} (pending)")
        else:
            log.error(f"  ✗ LIMIT échoué @{limit_price}")

        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        for line in log_lines:
            log.info(line)
        send_alert_sync(
            f"🟢 {action} {symbol} | {mt5_comment}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{log_lines[1]}\n"
            f"Time: {now_str}\n"
            f"Canal: {canal}"
        )

    else:
        tp1 = all_tps[0]
        tp2 = all_tps[1] if len(all_tps) >= 2 else None

        if tp2 is not None:
            if action == "BUY" and current > tp2:
                log.info(f"CAS 2 — prix > TP2 ({tp2}) → ANNULÉ")
                return
            elif action == "SELL" and current < tp2:
                log.info(f"CAS 2 — prix < TP2 ({tp2}) → ANNULÉ")
                return

        if action == "BUY":
            between_zone_tp1 = zone_high < current < tp1
        else:
            between_zone_tp1 = tp1 < current < zone_low

        if between_zone_tp1:
            lot_per_order = max(round(LOT_SIZE / 2, 2), sym_info.volume_min)
            other_limit = zone_low if action == "BUY" else zone_high
            log.info(f"CAS 2-a → Prix entre zone et TP1 ({zone_low}-{zone_high} ↔ {tp1}) | prix={current}")

            log.info(f"  → MARKET {action} @{current} lot={lot_per_order} TP={tp_final} SL={sl}")
            try:
                t = bridge.place_market_order(signal, lot_per_order, tp=tp_final, comment=mt5_comment)
            except Exception as e:
                log.error(f"  MARKET EXCEPTION: {e}")
                t = None
            if t:
                tickets.append({
                    "ticket": t, "lot": lot_per_order, "role": "market_cas2",
                    "entry_price": current, "tp_index": tp_trigger_idx, "tp_target": tp3,
                    "tp3": tp3, "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log_lines.append(f"ORDER MARKET {action} @{current} | Lot: {lot_per_order} | TP: {tp_final} | SL: {sl} | Ticket: #{t}")
            else:
                log.error("  ✗ MARKET échoué")

            log.info(f"  → LIMIT {action} @{other_limit} lot={lot_per_order} TP={tp_final} SL={sl}")
            o = bridge.place_limit_order(signal, lot_per_order, other_limit, tp_final, expiry, comment=mt5_comment)
            if o:
                orders.append({
                    "order": o, "lot": lot_per_order, "price": other_limit, "role": "limit_cas2",
                    "tp_index": tp_trigger_idx, "tp_target": tp3, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log_lines.append(f"ORDER LIMIT {action} @{other_limit} | Lot: {lot_per_order} | TP: {tp_final} | SL: {sl} | Ticket: #{o} (pending)")
            else:
                log.error(f"  ✗ LIMIT échoué @{other_limit}")

            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
            for line in log_lines:
                log.info(line)
            send_alert_sync(
                f"🟢 {action} {symbol} | {mt5_comment}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{log_lines[1]}\n"
                f"Time: {now_str}\n"
                f"Canal: {canal}"
            )

        else:
            lot_per_order = max(round(LOT_SIZE / 2, 2), sym_info.volume_min)
            if action == "BUY":
                price_1 = zone_high
                price_2 = zone_low
            else:
                price_1 = zone_low
                price_2 = zone_high

            log.info(f"CAS 2-b → prix loin de la zone (mais <= TP2) → 2 × LIMIT")

            log.info(f"  → LIMIT_1 {action} @{price_1} lot={lot_per_order} TP={tp_final} SL={sl}")
            o1 = bridge.place_limit_order(signal, lot_per_order, price_1, tp_final, expiry, comment=mt5_comment)
            if o1:
                orders.append({
                    "order": o1, "lot": lot_per_order, "price": price_1, "role": "limit_1",
                    "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log_lines.append(f"ORDER LIMIT {action} @{price_1} | Lot: {lot_per_order} | TP: {tp_final} | SL: {sl} | Ticket: #{o1} (pending)")
            else:
                log.error(f"  ✗ LIMIT_1 échoué @{price_1}")

            log.info(f"  → LIMIT_2 {action} @{price_2} lot={lot_per_order} TP={tp_final} SL={sl}")
            o2 = bridge.place_limit_order(signal, lot_per_order, price_2, tp_final, expiry, comment=mt5_comment)
            if o2:
                orders.append({
                    "order": o2, "lot": lot_per_order, "price": price_2, "role": "limit_2",
                    "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log_lines.append(f"ORDER LIMIT {action} @{price_2} | Lot: {lot_per_order} | TP: {tp_final} | SL: {sl} | Ticket: #{o2} (pending)")
            else:
                log.error(f"  ✗ LIMIT_2 échoué @{price_2}")

            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
            for line in log_lines:
                log.info(line)
            send_alert_sync(
                f"🔵 {action} {symbol} | {mt5_comment}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{log_lines[1]}\n"
                f"Time: {now_str}\n"
                f"Canal: {canal}"
            )

    if not orders and not tickets:
        log.error("Aucun ordre placé.")
        return

    entry = {
        "signal": signal,
        "orders": orders,
        "tickets": tickets,
        "expiry": expiry,
        "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "_signal_number": signal_number,
    }

    if in_zone or between_zone_tp1:
        if 'market_entry_price' in locals() and 'limit_price' in locals():
            entry["_grade_market_price"] = market_entry_price
            entry["_grade_limit_price"] = limit_price
            log.info(f"[GRADE] Prix stockés pour execute_signal : MARKET={market_entry_price}, LIMIT={limit_price}")

    manager.register(entry)
    tracker.log_trade_open(entry)

    supa_trade_id = None
    if _supa_connected and _supa:
        ticket_ids = [t["ticket"] for t in tickets]
        supa_trade_id = _supa.log_trade_open(
            signal=signal,
            entry_price=current,
            lot_size=LOT_SIZE,
            tickets=ticket_ids,
        )
        entry["_supa_trade_id"] = supa_trade_id

    if _tracker and _supa_connected:
        cas_num = 1 if in_zone else 2
        signal_type = "PU" if is_single_price else f"CAS{cas_num}"
        enriched = _tracker.enrich_trade_data(signal, current, LOT_SIZE, sl, tp_final, cas_num)
        if supa_trade_id:
            _tracker.update_trade_tracking(supa_trade_id, enriched)
            _tracker.track_open(supa_trade_id, signal, current, LOT_SIZE, sl, tp_final, signal_type)


# =============================================================
# QUICK ALERT (modifié)
# =============================================================
def _qa_key(symbol: str, action: str, channel_name: str = "") -> str:
    clean_channel = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f\u00a0]', '', channel_name)
    ch_num = CHANNEL_NUM_MAP.get(clean_channel, CHANNEL_NUM_MAP.get(clean_channel.lstrip("-"), "?"))
    return f"CH{ch_num}_{symbol}_{action}"

def execute_quick_alert(signal: dict, bridge: MT5Bridge, manager: TradeManager,
                        tracker: PerformanceTracker, quick_alerts: dict):
    signal_number = get_next_signal_number()
    log.info("=" * 55)
    
    action = signal["action"]
    symbol = signal["symbol"]
    sl = signal["sl"]
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

    if not signal.get("tps") or len(signal["tps"]) == 0:
        if action == "BUY":
            default_tp = entry_price + (entry_price - sl) * DEFAULT_ALERT_TP_RR
        else:
            default_tp = entry_price - (sl - entry_price) * DEFAULT_ALERT_TP_RR
        default_tp = round(default_tp, 2)
        log.info(f"TP par défaut calculé : {default_tp} (RR={DEFAULT_ALERT_TP_RR})")
    else:
        default_tp = 0

    key = _qa_key(symbol, action, canal)
    if key in quick_alerts and quick_alerts[key]:
        existing = quick_alerts[key][0]
        existing_ticket = existing.get("ticket")
        log.info(f"QUICK ALERT déjà existante pour {key} → mise à jour du SL (provisoire → {sl})")

        if existing.get("is_limit", False):
            order = mt5.orders_get(ticket=existing_ticket)
            if order:
                bridge.modify_order_sl_tp(existing_ticket, sl, default_tp, "[QA-UPDATE-SL-TP]")
                log.info(f"  ✓ SL/TP de l'ordre #{existing_ticket} mis à jour → SL={sl}, TP={default_tp}")
                existing["signal"]["sl"] = sl
                return
        else:
            pos = mt5.positions_get(ticket=existing_ticket)
            if pos:
                bridge.modify_sl_tp(existing_ticket, sl, default_tp, "[QA-UPDATE-SL-TP]")
                log.info(f"  ✓ SL/TP de la position #{existing_ticket} mis à jour → SL={sl}, TP={default_tp}")
                existing["signal"]["sl"] = sl
                return
            else:
                log.warning(f"QUICK ALERT existante mais ordre/position #{existing_ticket} introuvable → nouvelle alerte")

    if action == "SELL":
        in_zone = entry_price <= current <= sl
    else:
        in_zone = sl <= current <= entry_price

    orders = []
    tickets = []
    order_ticket = None
    is_limit_order = False
    log_lines = [f"SIGNAL {signal_number} (QUICK) | {action} {symbol} | Canal: {canal} | CH{ch_num}-AL"]
    log_lines.append(f"Zone [{entry_price}–{entry_price}] | Prix {current} | TP par défaut: {default_tp} | SL provisoire: {sl}")

    if in_zone:
        log.info(f"QUICK ALERT MARKET {action} {symbol} @{current} SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}")
        try:
            t = bridge.place_market_order(signal, LOT_UNIQUE_TRADE, tp=default_tp, comment=f"CH{ch_num}-AL")
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
            })
            order_ticket = t
            log_lines.append(f"ORDER MARKET {action} @{current} | Lot: {LOT_UNIQUE_TRADE} | TP: {default_tp} | SL: {sl} | Ticket: #{t}")
            log.info(f"  ✓ QUICK MARKET #{t} @{current} SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}")
        else:
            log.error("  ✗ QUICK MARKET échoué")
            return
    else:
        log.info(f"QUICK ALERT LIMIT {action} {symbol} @{entry_price} SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}")
        o = bridge.place_limit_order(signal, LOT_UNIQUE_TRADE, entry_price, default_tp, expiry, comment=f"CH{ch_num}-AL")
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
            log_lines.append(f"ORDER LIMIT {action} @{entry_price} | Lot: {LOT_UNIQUE_TRADE} | TP: {default_tp} | SL: {sl} | Ticket: #{o} (pending)")
            log.info(f"  ✓ QUICK LIMIT #{o} @{entry_price} SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}")
        else:
            log.error("  ✗ QUICK LIMIT échoué")
            return

    for line in log_lines:
        log.info(line)

    entry = {
        "signal": signal,
        "orders": orders,
        "tickets": tickets,
        "expiry": expiry,
        "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "_is_quick_alert": True,
        "_signal_number": signal_number,
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
    log.info(f"QUICK ALERT enregistré: {key} avec TP={default_tp}, lot={LOT_UNIQUE_TRADE}")


# =============================================================
# MERGE QUICK ALERT (modifié)
# =============================================================
def merge_quick_alert(qa: dict, key: str, full_signal: dict,
                      bridge: MT5Bridge, manager: TradeManager,
                      tracker: PerformanceTracker, quick_alerts: dict):
    qa_ticket = qa["ticket"]
    qa_is_limit = qa["is_limit"]
    entry = qa["entry"]
    real_sl = full_signal["sl"]
    tp_final = full_signal["tps"][-1] if full_signal["tps"] else 0
    
    signal_number = entry.get("_signal_number", get_next_signal_number())
    log.info("=" * 55)

    if qa_is_limit:
        pos = manager._resolve_order(qa_ticket, full_signal["symbol"])
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
            sl_hit = False
            tp_hit = False
            if deals:
                for deal in reversed(deals):
                    if (deal.symbol == full_signal["symbol"] and
                        (deal.position_id == qa_ticket or deal.order == qa_ticket)):
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

    canal = full_signal.get("source_channel", "Inconnu")
    ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
    action = full_signal["action"]
    symbol = full_signal["symbol"]
    
    log_lines = [f"SIGNAL {signal_number} (MERGE) | {action} {symbol} | Canal: {canal} | CH{ch_num}-MG"]
    log_lines.append(f"Zone [{full_signal['zone_low']}–{full_signal['zone_high']}] | TPs={full_signal['tps']} | SL={real_sl}")

    if not qa_is_limit:
        log.info(f"MERGE Scénario 1: Position #{qa_ticket} ouverte → SL/TP + LIMIT")
        bridge.modify_sl_tp(qa_ticket, real_sl, tp_final, "[MERGE-SL-TP]")
        for t in entry["tickets"]:
            if t["ticket"] == qa_ticket:
                if len(full_signal["tps"]) == 1:
                    tp_trigger_idx = 0
                else:
                    tp_trigger_idx = TP_TRIGGER - 1 if TP_TRIGGER <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
                t["tp_final"] = tp_final
                t["tp_target"] = full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final
                t["tp3"] = t["tp_target"]
                t["tp_index"] = tp_trigger_idx
                break
        _place_merge_limit(full_signal, bridge, entry, real_sl, tp_final)
        entry["signal"] = full_signal
        entry["_is_quick_alert"] = False
        log_lines.append(f"ORDER MARKET {action} @{t['entry_price']} | Ticket: #{qa_ticket} (modifié) | TP: {tp_final} | SL: {real_sl}")
    else:
        resolved_pos = manager._resolve_order(qa_ticket, full_signal["symbol"])
        if resolved_pos:
            log.info(f"MERGE Scénario 1: LIMIT #{qa_ticket} rempli → SL/TP + LIMIT")
            if len(full_signal["tps"]) == 1:
                tp_trigger_idx = 0
            else:
                tp_trigger_idx = TP_TRIGGER - 1 if TP_TRIGGER <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
            tk = {
                "ticket": resolved_pos.ticket,
                "lot": qa["entry"]["orders"][0]["lot"] if qa["entry"]["orders"] else LOT_UNIQUE_TRADE,
                "role": "quick_limit_filled",
                "entry_price": resolved_pos.price_open,
                "tp_index": tp_trigger_idx,
                "tp_target": full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final,
                "tp3": full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final,
                "tp_final": tp_final,
                "sl_step": 0,
                "trail_active": False,
            }
            entry["tickets"].append(tk)
            entry["orders"] = [o for o in entry["orders"] if o["order"] != qa_ticket]
            bridge.modify_sl_tp(resolved_pos.ticket, real_sl, tp_final, "[MERGE-SL-TP]")
            _place_merge_limit(full_signal, bridge, entry, real_sl, tp_final)
            entry["signal"] = full_signal
            entry["_is_quick_alert"] = False
            log_lines.append(f"ORDER LIMIT rempli {action} @{resolved_pos.price_open} | Ticket: #{resolved_pos.ticket} | TP: {tp_final} | SL: {real_sl}")
        else:
            log.info(f"MERGE Scénario 2: LIMIT #{qa_ticket} pending → modif SL/TP + LIMIT")
            if len(full_signal["tps"]) == 1:
                tp_trigger_idx = 0
            else:
                tp_trigger_idx = TP_TRIGGER - 1 if TP_TRIGGER <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
            bridge.modify_order_sl_tp(qa_ticket, real_sl, tp_final, "[MERGE-ORD-SL-TP]")
            for o in entry["orders"]:
                if o["order"] == qa_ticket:
                    o["tp_final"] = tp_final
                    o["tp_target"] = full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final
                    o["tp3"] = o["tp_target"]
                    o["tp_index"] = tp_trigger_idx
                    break
            _place_merge_limit(full_signal, bridge, entry, real_sl, tp_final)
            entry["signal"] = full_signal
            entry["_is_quick_alert"] = False
            log_lines.append(f"ORDER LIMIT {action} @{full_signal['zone_mid']} | Ticket: #{qa_ticket} (modifié) | TP: {tp_final} | SL: {real_sl}")

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
            action = full_signal["action"]
            if action == "BUY":
                entry["_grade_limit_price"] = full_signal["zone_low"]
            else:
                entry["_grade_limit_price"] = full_signal["zone_high"]
            log.info(f"[GRADE] Prix stockés pour quick alert : MARKET={market_entry_price}, LIMIT={entry['_grade_limit_price']}")

    if key in quick_alerts and qa in quick_alerts[key]:
        quick_alerts[key].remove(qa)
        if not quick_alerts[key]:
            del quick_alerts[key]
    
    for line in log_lines:
        log.info(line)
    log.info(f"MERGE terminé: {full_signal['action']} {full_signal['symbol']}")


def _place_merge_limit(full_signal: dict, bridge: MT5Bridge, entry: dict,
                       real_sl: float, tp_final: float):
    zone_low = full_signal["zone_low"]
    zone_high = full_signal["zone_high"]
    action = full_signal["action"]
    if abs(zone_high - zone_low) < 1:
        return
    sym_info = bridge._sym(full_signal["symbol"])
    if not sym_info:
        return
    if action == "SELL":
        limit_price = zone_high
    else:
        limit_price = zone_low
    expiry = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MIN)
    canal = full_signal.get("source_channel", "Inconnu")
    ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
    log.info(f"MERGE LIMIT {action} @{limit_price} lot={LOT_UNIQUE_TRADE} TP={tp_final} SL={real_sl}")
    o = bridge.place_limit_order(full_signal, LOT_UNIQUE_TRADE, limit_price, tp_final, expiry, comment=f"CH{ch_num}-MG")
    if o:
        if len(full_signal["tps"]) == 1:
            tp_trigger_idx = 0
        else:
            tp_trigger_idx = TP_TRIGGER - 1 if TP_TRIGGER <= len(full_signal["tps"]) else len(full_signal["tps"]) - 1
        entry["orders"].append({
            "order": o,
            "lot": LOT_UNIQUE_TRADE,
            "price": limit_price,
            "role": "merge_limit",
            "tp_index": len(full_signal["tps"]) - 1,
            "tp_target": tp_final,
            "tp3": full_signal["tps"][tp_trigger_idx] if len(full_signal["tps"]) > tp_trigger_idx else tp_final,
            "tp_final": tp_final,
            "sl_step": 0,
            "trail_active": False,
        })
        log.info(f"  ✓ MERGE LIMIT #{o} @{limit_price} lot={LOT_UNIQUE_TRADE}")
    else:
        log.error(f"  ✗ MERGE LIMIT échoué @{limit_price}")


# =============================================================
# TRADE MANAGER (modifié)
# =============================================================
class TradeManager:
    def __init__(self, bridge: MT5Bridge, tracker=None):
        self.bridge = bridge
        self.tracker = tracker
        self.active = []
        self._lock = threading.Lock()
        self._stop = False
        self._task = None
        # ── Récupération du P&L réalisé depuis l'historique ──
        self._daily_pnl = self._recover_daily_pnl()
        self._daily_pnl_day = datetime.now(timezone.utc).day
        log.info(f"[DAILY P&L] Récupéré depuis l'historique : {self._daily_pnl:.2f}$")

    def _recover_daily_pnl(self) -> float:
        """Récupère le P&L réalisé depuis minuit (UTC) pour les trades du bot."""
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start_of_day, now)
        if deals is None or len(deals) == 0:
            return 0.0
        total = 0.0
        for deal in deals:
            if deal.magic == MAGIC_NUMBER and deal.entry == mt5.DEAL_ENTRY_OUT:
                total += deal.profit
        return total

    async def start(self):
        self._task = asyncio.create_task(self._loop_async())

    def register(self, entry: dict):
        with self._lock:
            self.active.append(entry)
        sig = entry["signal"]
        canal = sig.get("source_channel", "Inconnu")
        mode = "DEMO" if DEMO_MODE else "LIVE"
        log.info(f"TradeManager [{mode}]: {sig['action']} {sig['symbol']} Canal: {canal} | {len(entry['orders'])} ordres")

    def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()

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
        now = datetime.now(timezone.utc)
        if now.day != self._daily_pnl_day:
            self._daily_pnl = 0.0
            self._daily_pnl_day = now.day
            log.info("[DAILY P&L] Reset journalier")
        self._daily_pnl += pnl
        total = self._daily_pnl + self._get_floating_pnl()
        log.info(f"[DAILY P&L] Réalisé {self._daily_pnl:.2f} | Flottant {self._get_floating_pnl():.2f} | Total {total:.2f} / {DAILY_PROFIT_LIMIT:.2f}")

    def _check_daily_pnl_limit(self) -> bool:
        now = datetime.now(timezone.utc)
        if now.day != self._daily_pnl_day:
            self._daily_pnl = 0.0
            self._daily_pnl_day = now.day
            log.info("[DAILY P&L] Reset journalier")
        total_pnl = self._daily_pnl + self._get_floating_pnl()
        if total_pnl >= DAILY_PROFIT_LIMIT:
            log.info(f"[DAILY P&L] Limite atteinte : {total_pnl:.2f}$ (réalisé {self._daily_pnl:.2f} + flottant {self._get_floating_pnl():.2f})")
            return False
        return True

    def _close_all_active_trades(self) -> float:
        total_closed_pnl = 0.0
        with self._lock:
            entries = self.active.copy()
            for entry in entries:
                for o in entry.get("orders", []):
                    self.bridge.cancel_order(o["order"])
                for t in entry.get("tickets", []):
                    pos = self._get_pos(t["ticket"])
                    if pos:
                        self.bridge.close_position(t["ticket"], comment="DAILY-LIMIT-CLOSE")
                        total_closed_pnl += pos.profit
                entry["orders"] = []
                entry["tickets"] = []
            self.active.clear()
        if total_closed_pnl != 0.0:
            self._update_daily_pnl(total_closed_pnl)
        return total_closed_pnl

    async def _loop_async(self):
        while not self._stop:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                await asyncio.to_thread(self._check_all)
            except Exception as exc:
                log.error(f"TradeManager erreur: {exc}")

    def _get_pos(self, ticket: int):
        r = mt5.positions_get(ticket=ticket)
        return r[0] if r else None

    def _resolve_order(self, order_ticket: int, symbol: str):
        since = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
        if not deals:
            return None
        for deal in deals:
            if deal.order == order_ticket and deal.entry == mt5.DEAL_ENTRY_IN:
                positions = mt5.positions_get(ticket=deal.position_id)
                if positions:
                    return positions[0]
        return None

    def _get_last_pnl(self, ticket: int, symbol: str) -> float:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
        if deals:
            for deal in reversed(deals):
                if deal.symbol == symbol and (deal.position_id == ticket or deal.order == ticket):
                    if deal.entry == mt5.DEAL_ENTRY_OUT:
                        return deal.profit
            for deal in reversed(deals):
                if deal.position_id == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
                    return deal.profit
        return 0.0

    def _get_close_reason(self, ticket: int, symbol: str) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
        if deals:
            for deal in reversed(deals):
                if deal.symbol == symbol and (deal.position_id == ticket or deal.order == ticket):
                    if deal.entry == mt5.DEAL_ENTRY_OUT:
                        if deal.reason == mt5.DEAL_REASON_TP:
                            return "TP"
                        elif deal.reason == mt5.DEAL_REASON_SL:
                            return "SL"
            for deal in reversed(deals):
                if deal.position_id == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
                    if deal.reason == mt5.DEAL_REASON_TP:
                        return "TP"
                    elif deal.reason == mt5.DEAL_REASON_SL:
                        return "SL"
        return "OTHER"

    def _check_pnl_trigger(self, entry: dict) -> bool:
        min_profit = float('inf')
        has_active = False
        for t in entry.get("tickets", []):
            if t.get("trail_active") or t.get("_pnl_handled"):
                continue
            pos = self._get_pos(t["ticket"])
            if pos:
                has_active = True
                if pos.profit < min_profit:
                    min_profit = pos.profit
        if not has_active:
            return False
        return min_profit >= PNL_TRIGGER_USD

    def _check_tp3_by_ohlc(self, entry: dict) -> bool:
        sig = entry["signal"]
        action = sig["action"]
        symbol = sig["symbol"]
        tp3_level = 0
        for t in entry.get("tickets", []):
            if t.get("tp3"):
                tp3_level = t["tp3"]
                break
        if not tp3_level:
            for o in entry.get("orders", []):
                if o.get("tp3"):
                    tp3_level = o["tp3"]
                    break
        if not tp3_level:
            return False
        for t in entry.get("tickets", []):
            if self._get_pos(t["ticket"]):
                return False
        sym_info = self.bridge._sym(symbol)
        if sym_info is None:
            return False
        rates = mt5.copy_rates_from_pos(sym_info.name, mt5.TIMEFRAME_M1, 0, 5)
        if rates is None:
            return False
        for rate in rates:
            if action == "SELL" and rate["low"] <= tp3_level:
                log.info(f"OHLC TP3 détecté: low={rate['low']} <= TP3={tp3_level}")
                return True
            elif action == "BUY" and rate["high"] >= tp3_level:
                log.info(f"OHLC TP3 détecté: high={rate['high']} >= TP3={tp3_level}")
                return True
        return False

    def _manage_grade(self, entry: dict, symbol: str, action: str, current: float, sym_info, now: datetime):
        market_price = entry.get("_grade_market_price")
        limit_price = entry.get("_grade_limit_price")

        if not market_price or not limit_price:
            log.debug("[GRADE] Prix de référence non trouvés dans l'entry")
            return

        if action == "BUY":
            if not (limit_price < current < market_price):
                return
        else:
            if not (market_price < current < limit_price):
                return

        signal_sl = entry["signal"].get("sl", 0.0)

        grade_positions = []
        for t in entry["tickets"]:
            if t.get("role", "").startswith("grade"):
                pos = self._get_pos(t["ticket"])
                if pos:
                    grade_positions.append({
                        "ticket": t["ticket"],
                        "entry_price": t["entry_price"],
                        "pos": pos,
                        "level": t.get("grade_level", 0),
                    })

        if action == "BUY":
            grade_positions.sort(key=lambda x: x["entry_price"])
        else:
            grade_positions.sort(key=lambda x: x["entry_price"], reverse=True)

        direction = -1 if action == "BUY" else 1
        if grade_positions:
            last_price = grade_positions[-1]["entry_price"]
            target_price = last_price + direction * REVERSE_PRICE
        else:
            target_price = market_price + direction * REVERSE_PRICE

        if len(grade_positions) >= MAX_GRADE_POSITIONS:
            ready = False
        else:
            if action == "BUY":
                ready = current <= target_price
            else:
                ready = current >= target_price

        if ready:
            ch_num = CHANNEL_NUM_MAP.get(entry["signal"].get("source_channel", "Inconnu"), "?")
            comment = f"CH{ch_num}-G{len(grade_positions)+1}"
            grade_signal = entry["signal"].copy()
            grade_signal["symbol"] = symbol
            grade_signal["action"] = action
            grade_signal["sl"] = signal_sl

            ticket = self.bridge.place_market_order(
                grade_signal,
                LOT_UNIQUE_TRADE,
                tp=0,
                sl=signal_sl,
                comment=comment
            )
            if ticket:
                grade_tk = {
                    "ticket": ticket,
                    "lot": LOT_UNIQUE_TRADE,
                    "role": f"grade_{len(grade_positions)+1}",
                    "entry_price": target_price,
                    "grade_level": len(grade_positions)+1,
                    "tp_index": 0,
                    "tp_target": 0,
                    "tp3": 0,
                    "tp_final": 0,
                    "sl_step": 0,
                    "trail_active": False,
                    "_grade_profit_handled": False,
                }
                entry["tickets"].append(grade_tk)
                log.info(f"GRADE: Ouverture {comment} @{target_price:.2f} (palier {len(grade_positions)+1}) | SL={signal_sl}")
            else:
                log.error(f"GRADE: Échec d'ouverture de {comment}")

        for g in grade_positions:
            if g["pos"].profit >= REALISED_GRADE:
                self.bridge.close_position(g["ticket"], comment=f"GRADE-PROFIT")
                for t in entry["tickets"]:
                    if t["ticket"] == g["ticket"]:
                        t["_grade_profit_handled"] = True
                        break
                log.info(f"GRADE: Fermeture #{g['ticket']} P&L={g['pos'].profit:.2f} (>= {REALISED_GRADE})")

    def _check_all(self):
        now = datetime.now(timezone.utc)

        # ── Vérification du P&L quotidien ──
        if not self._check_daily_pnl_limit():
            if self.active:
                log.warning("[DAILY P&L] Limite atteinte ! Fermeture de toutes les positions et annulation des ordres.")
                self._close_all_active_trades()
                log.info("[DAILY P&L] Toutes les positions sont fermées. Le bot n'ouvrira plus de trades aujourd'hui.")
            if not self.active:
                return

        with self._lock:
            entries_snapshot = list(self.active)

        for entry in entries_snapshot:
            sig = entry["signal"]
            symbol = sig["symbol"]
            action = sig["action"]
            canal = sig.get("source_channel", "Inconnu")
            ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
            signal_number = entry.get("_signal_number", "?")

            # ── Résoudre les ordres pending ──
            still_pending = []
            limit_filled = False
            for o in entry["orders"]:
                pos = self._resolve_order(o["order"], symbol)
                if pos:
                    tk = {
                        "ticket": pos.ticket, "lot": o["lot"], "role": o["role"],
                        "entry_price": pos.price_open, "tp_index": o.get("tp_index", 0),
                        "tp_target": o.get("tp_target", 0), "tp3": o.get("tp3", 0),
                        "tp_final": o.get("tp_final", 0), "sl_step": 0, "trail_active": False,
                    }
                    entry["tickets"].append(tk)
                    limit_filled = True
                    log.info(f"SIGNAL {signal_number} | LIMIT rempli | {action} {symbol} | Canal: {canal}")
                    log.info(f"Ticket: #{pos.ticket} | Prix: {pos.price_open} | Lot: {o['lot']}")
                    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    send_alert_sync(
                        f"✅ LIMIT REMPLI {action} {symbol}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"Prix: @{pos.price_open} | Lot: {o['lot']}\n"
                        f"Ticket: #{pos.ticket}\n"
                        f"Time: {now_str}\n"
                        f"Canal: {canal}"
                    )
                elif now > entry["expiry"]:
                    self.bridge.cancel_order(o["order"])
                    log.info(f"SIGNAL {signal_number} | LIMIT annulé (expiration) | {action} {symbol} | Canal: {canal}")
                    log.info(f"Ticket: #{o['order']} | Prix: {o['price']} | Raison: Ordre non rempli dans le délai imparti")
                else:
                    still_pending.append(o)
            entry["orders"] = still_pending

            if limit_filled:
                supa_id = entry.get("_supa_trade_id")
                if supa_id and _supa_connected and _supa:
                    try:
                        current_tickets = [t["ticket"] for t in entry["tickets"]]
                        _supa._retry_call(
                            lambda: _supa.client.table("trades")
                            .update({"tickets": current_tickets})
                            .eq("id", supa_id).execute()
                        )
                        log.info(f"[SUPA] Tickets mis à jour: {current_tickets}")
                    except Exception as e:
                        log.warning(f"[SUPA] Erreur update tickets: {e}")

            active_tks = [t for t in entry["tickets"] if self._get_pos(t["ticket"])]
            if not entry["orders"] and not active_tks:
                with self._lock:
                    if entry in self.active:
                        self.active.remove(entry)
                continue

            sym_info = self.bridge._sym(symbol)
            if sym_info is None:
                continue
            tick = mt5.symbol_info_tick(sym_info.name)
            if tick is None:
                continue
            current = tick.bid if action == "BUY" else tick.ask

            # ── Rapports de clôture ──
            for t in entry["tickets"]:
                pos = self._get_pos(t["ticket"])
                if pos is None and not t.get("_reported"):
                    t["_reported"] = True
                    pnl = self._get_last_pnl(t["ticket"], symbol)
                    t["_last_pnl"] = pnl
                    tp_idx = t.get("tp_index", -1)
                    tp_val = t.get("tp_target", 0)
                    close_reason = self._get_close_reason(t["ticket"], symbol)
                    emoji = "🎯" if close_reason == "TP" else ("🛑" if close_reason == "SL" else "⚪")
                    result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BE")
                    signal_number = entry.get("_signal_number", "?")
                    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    
                    if close_reason == "TP" and tp_val == t.get("tp_final", 0):
                        log.info(f"SIGNAL {signal_number} | TP FINAL atteint | {action} {symbol} | Canal: {canal}")
                    elif close_reason == "TP":
                        log.info(f"SIGNAL {signal_number} | TP{tp_idx+1} atteint | {action} {symbol} | Canal: {canal}")
                    elif close_reason == "SL":
                        log.info(f"SIGNAL {signal_number} | SL touché | {action} {symbol} | Canal: {canal}")
                    else:
                        log.info(f"SIGNAL {signal_number} | Fermé ({close_reason}) | {action} {symbol} | Canal: {canal}")
                    
                    log.info(f"P&L: {pnl:+.2f}$ ({result}) | Ticket: #{t['ticket']}")
                    
                    send_alert_sync(
                        f"{emoji} FERMÉ {action} {symbol} ({close_reason})\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"P&L: {pnl:+.2f}$ ({result})\n"
                        f"Ticket: #{t['ticket']}\n"
                        f"Time: {now_str}\n"
                        f"Canal: {canal}"
                    )
                    if _supa_connected and _supa:
                        supa_id = entry.get("_supa_trade_id")
                        if supa_id:
                            if close_reason == "TP":
                                _supa.log_tp_hit(supa_id, f"TP{tp_idx+1}", tp_val, pnl)
                            elif close_reason == "SL":
                                _supa.log_sl_hit(supa_id, pnl)
                            else:
                                if pnl >= 0:
                                    _supa.log_tp_hit(supa_id, f"TP{tp_idx+1}", tp_val, pnl)
                                else:
                                    _supa.log_sl_hit(supa_id, pnl)

            # ==================== PRIX UNIQUE ====================
            pu_tp3_level = 0
            pu_market_tk = None
            pu_limit_tk = None
            pu_limit_order = None
            for t in entry["tickets"]:
                if t.get("role") == "market_single":
                    pu_market_tk = t
                    if t.get("tp3"):
                        pu_tp3_level = t["tp3"]
                elif t.get("role") == "limit_single":
                    pu_limit_tk = t
                    if t.get("tp3") and pu_tp3_level == 0:
                        pu_tp3_level = t["tp3"]
            for o in entry["orders"]:
                if o.get("role") == "limit_single":
                    pu_limit_order = o
                    if o.get("tp3") and pu_tp3_level == 0:
                        pu_tp3_level = o["tp3"]

            pu_pnl_hit = self._check_pnl_trigger(entry)
            if pu_pnl_hit and not entry.get("_pu_handled"):
                entry["_pu_handled"] = True
                log.info(f"SIGNAL {signal_number} | PRIX UNIQUE TP3 atteint → BE + trailing")
                if pu_market_tk and self._get_pos(pu_market_tk["ticket"]) is None:
                    if pu_limit_tk:
                        lpos = self._get_pos(pu_limit_tk["ticket"])
                        if lpos:
                            log.info(f"PU → limit exécutée, BE @{pu_market_tk['entry_price']} + trail")
                            self.bridge.modify_sl(pu_limit_tk["ticket"], pu_market_tk["entry_price"], "[PU TP3 BE]")
                            pu_limit_tk["trail_active"] = True
                            pu_limit_tk["sl_step"] = 1
                            pu_limit_tk["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL → {pu_market_tk['entry_price']} (prix d'entrée) | Ticket: #{pu_limit_tk['ticket']}")
                            log.info(f"Trailing activé | Dernier prix: {current}")
                            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            send_alert_sync(
                                f"🔒 BE activé {action} {symbol}\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"SL → @{pu_market_tk['entry_price']} (prix d'entrée)\n"
                                f"Ticket: #{pu_limit_tk['ticket']}\n"
                                f"Time: {now_str}\n"
                                f"Canal: {canal} | PU"
                            )
                    elif pu_limit_order:
                        lpos = self._resolve_order(pu_limit_order["order"], symbol)
                        if lpos:
                            log.info(f"PU → limit tardive, BE @{pu_market_tk['entry_price']} + trail")
                            self.bridge.modify_sl(lpos.ticket, pu_market_tk["entry_price"], "[PU TP3 BE]")
                            tk = {"ticket": lpos.ticket, "lot": pu_limit_order["lot"], "role": "limit_single",
                                  "entry_price": lpos.price_open, "tp_index": pu_limit_order.get("tp_index", 0),
                                  "tp_target": pu_limit_order.get("tp_target", 0), "tp3": pu_limit_order["tp3"],
                                  "tp_final": pu_limit_order["tp_final"], "sl_step": 1, "trail_active": True,
                                  "trail_last_price": current}
                            entry["tickets"].append(tk)
                            entry["orders"].remove(pu_limit_order)
                        else:
                            self.bridge.cancel_order(pu_limit_order["order"])
                            entry["orders"].remove(pu_limit_order)
                elif pu_limit_tk and not pu_market_tk:
                    lpos = self._get_pos(pu_limit_tk["ticket"])
                    if lpos and not pu_limit_tk.get("trail_active"):
                        self.bridge.modify_sl(pu_limit_tk["ticket"], pu_limit_tk.get("entry_price", 0), "[PU S2 BE]")
                        pu_limit_tk["trail_active"] = True
                        pu_limit_tk["sl_step"] = 1
                        pu_limit_tk["trail_last_price"] = current
                        log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                        log.info(f"SL → {pu_limit_tk.get('entry_price', 0)} (prix d'entrée) | Ticket: #{pu_limit_tk['ticket']}")
                        log.info(f"Trailing activé | Dernier prix: {current}")
                elif pu_market_tk and not pu_limit_tk and not pu_limit_order:
                    pos = self._get_pos(pu_market_tk["ticket"])
                    if pos and not pu_market_tk.get("trail_active"):
                        self.bridge.modify_sl(pu_market_tk["ticket"], pu_market_tk.get("entry_price", 0), "[PU S1 BE]")
                        pu_market_tk["trail_active"] = True
                        pu_market_tk["sl_step"] = 1
                        pu_market_tk["trail_last_price"] = current
                        log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                        log.info(f"SL → {pu_market_tk.get('entry_price', 0)} (prix d'entrée) | Ticket: #{pu_market_tk['ticket']}")
                        log.info(f"Trailing activé | Dernier prix: {current}")

            # ==================== CAS 1 ====================
            market_tk = None
            for t in entry["tickets"]:
                if t.get("role") == "market_tp3":
                    market_tk = t
                    break
            if market_tk and not market_tk.get("_cas1_handled"):
                if self._check_pnl_trigger(entry):
                    market_tk["_cas1_handled"] = True
                    market_entry = market_tk.get("entry_price", 0)
                    log.info(f"SIGNAL {signal_number} | CAS 1 P&L trigger atteint ({PNL_TRIGGER_USD}$) → prix={current}")
                    limit_ticket = None
                    for tk in entry["tickets"]:
                        if tk.get("role") == "limit_catch":
                            limit_ticket = tk
                            break
                    limit_order = None
                    for o in entry["orders"]:
                        if o.get("role") == "limit_catch":
                            limit_order = o
                            break
                    if limit_ticket:
                        pos = self._get_pos(limit_ticket["ticket"])
                        if pos:
                            market_pos = self._get_pos(market_tk["ticket"])
                            if market_pos:
                                self.bridge.close_position(market_tk["ticket"], "CAS1-TP3-close-market")
                                log.info(f"  MARKET #{market_tk['ticket']} fermé @ TP3")
                            log.info(f"CAS 1 → 2-b limit remplie → BE @{market_entry} + trail")
                            self.bridge.modify_sl(limit_ticket["ticket"], market_entry, "[CAS1 TP3 BE]")
                            limit_ticket["trail_active"] = True
                            limit_ticket["sl_step"] = 1
                            limit_ticket["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL → {market_entry} (prix d'entrée) | Ticket: #{limit_ticket['ticket']}")
                            log.info(f"Trailing activé | Dernier prix: {current}")
                            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            send_alert_sync(
                                f"🔒 BE activé {action} {symbol}\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"SL → @{market_entry} (prix d'entrée)\n"
                                f"Ticket: #{limit_ticket['ticket']}\n"
                                f"Time: {now_str}\n"
                                f"Canal: {canal} | CAS 1"
                            )
                    elif limit_order:
                        pos = self._resolve_order(limit_order["order"], symbol)
                        if pos:
                            market_pos = self._get_pos(market_tk["ticket"])
                            if market_pos:
                                self.bridge.close_position(market_tk["ticket"], "CAS1-TP3-close-market")
                                log.info(f"  MARKET #{market_tk['ticket']} fermé @ TP3")
                            log.info(f"CAS 1 → 2-b limit tardive → BE @{market_entry} + trail")
                            self.bridge.modify_sl(pos.ticket, market_entry, "[CAS1 TP3 BE]")
                            tk = {"ticket": pos.ticket, "lot": limit_order["lot"], "role": "limit_catch",
                                  "entry_price": pos.price_open, "tp_index": limit_order.get("tp_index", 0),
                                  "tp_target": limit_order.get("tp_target", 0), "tp3": limit_order["tp3"],
                                  "tp_final": limit_order["tp_final"], "sl_step": 1, "trail_active": True,
                                  "trail_last_price": current}
                            entry["tickets"].append(tk)
                            entry["orders"].remove(limit_order)
                        else:
                            log.info(f"CAS 1 → 2-a limit non remplie → annulation #{limit_order['order']}")
                            self.bridge.cancel_order(limit_order["order"])
                            entry["orders"].remove(limit_order)
                            self.bridge.modify_sl(market_tk["ticket"], market_entry, "[CAS1 BE]")
                            market_tk["trail_active"] = True
                            market_tk["sl_step"] = 1
                            market_tk["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL → {market_entry} (prix d'entrée) | Ticket: #{market_tk['ticket']}")
                            log.info(f"Trailing activé | Dernier prix: {current}")
                    else:
                        self.bridge.modify_sl(market_tk["ticket"], market_entry, "[CAS1 BE]")
                        market_tk["trail_active"] = True
                        market_tk["sl_step"] = 1
                        market_tk["trail_last_price"] = current
                        log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                        log.info(f"SL → {market_entry} (prix d'entrée) | Ticket: #{market_tk['ticket']}")
                        log.info(f"Trailing activé | Dernier prix: {current}")

            # ==================== CAS 2-a ====================
            if not entry.get("_cas2a_handled"):
                mc2_tk = None
                lc2_tk = None
                lc2_order = None
                for t in entry["tickets"]:
                    if t.get("role") == "market_cas2":
                        mc2_tk = t
                    elif t.get("role") == "limit_cas2":
                        lc2_tk = t
                for o in entry["orders"]:
                    if o.get("role") == "limit_cas2":
                        lc2_order = o
                if mc2_tk:
                    if self._check_pnl_trigger(entry):
                        entry["_cas2a_handled"] = True
                        market_entry_c2 = mc2_tk.get("entry_price", 0)
                        log.info(f"SIGNAL {signal_number} | CAS 2-a P&L trigger atteint ({PNL_TRIGGER_USD}$) → prix={current}")
                        if lc2_tk:
                            lpos = self._get_pos(lc2_tk["ticket"])
                            if lpos:
                                mc2_pos = self._get_pos(mc2_tk["ticket"])
                                if mc2_pos:
                                    self.bridge.close_position(mc2_tk["ticket"], "C2a-TP3-close-market")
                                    log.info(f"  MARKET #{mc2_tk['ticket']} fermé @ TP3")
                                log.info(f"CAS 2-a → 3-a-2 limit remplie → BE @{market_entry_c2} + trail")
                                self.bridge.modify_sl(lc2_tk["ticket"], market_entry_c2, "[C2a TP3 BE]")
                                lc2_tk["trail_active"] = True
                                lc2_tk["sl_step"] = 1
                                lc2_tk["trail_last_price"] = current
                                log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                                log.info(f"SL → {market_entry_c2} (prix d'entrée) | Ticket: #{lc2_tk['ticket']}")
                                log.info(f"Trailing activé | Dernier prix: {current}")
                                now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                                send_alert_sync(
                                    f"🔒 BE activé {action} {symbol}\n"
                                    f"━━━━━━━━━━━━━━━━━━\n"
                                    f"SL → @{market_entry_c2} (prix d'entrée)\n"
                                    f"Ticket: #{lc2_tk['ticket']}\n"
                                    f"Time: {now_str}\n"
                                    f"Canal: {canal} | CAS 2-a"
                                )
                        elif lc2_order:
                            lpos = self._resolve_order(lc2_order["order"], symbol)
                            if lpos:
                                mc2_pos = self._get_pos(mc2_tk["ticket"])
                                if mc2_pos:
                                    self.bridge.close_position(mc2_tk["ticket"], "C2a-TP3-close-market")
                                    log.info(f"  MARKET #{mc2_tk['ticket']} fermé @ TP3")
                                log.info(f"CAS 2-a → 3-a-2 limit tardive → BE @{market_entry_c2} + trail")
                                self.bridge.modify_sl(lpos.ticket, market_entry_c2, "[C2a TP3 BE]")
                                tk = {"ticket": lpos.ticket, "lot": lc2_order["lot"], "role": "limit_cas2",
                                      "entry_price": lpos.price_open, "tp_index": lc2_order.get("tp_index", 0),
                                      "tp_target": lc2_order.get("tp_target", 0), "tp3": lc2_order["tp3"],
                                      "tp_final": lc2_order["tp_final"], "sl_step": 1, "trail_active": True,
                                      "trail_last_price": current}
                                entry["tickets"].append(tk)
                                entry["orders"].remove(lc2_order)
                            else:
                                log.info(f"CAS 2-a → 3-a-1 limit non remplie → annulation #{lc2_order['order']}")
                                self.bridge.cancel_order(lc2_order["order"])
                                entry["orders"].remove(lc2_order)
                                self.bridge.modify_sl(mc2_tk["ticket"], market_entry_c2, "[C2a BE]")
                                mc2_tk["trail_active"] = True
                                mc2_tk["sl_step"] = 1
                                mc2_tk["trail_last_price"] = current
                                log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                                log.info(f"SL → {market_entry_c2} (prix d'entrée) | Ticket: #{mc2_tk['ticket']}")
                                log.info(f"Trailing activé | Dernier prix: {current}")
                        else:
                            self.bridge.modify_sl(mc2_tk["ticket"], market_entry_c2, "[C2a BE]")
                            mc2_tk["trail_active"] = True
                            mc2_tk["sl_step"] = 1
                            mc2_tk["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL → {market_entry_c2} (prix d'entrée) | Ticket: #{mc2_tk['ticket']}")
                            log.info(f"Trailing activé | Dernier prix: {current}")

            # ==================== CAS 2-b ====================
            if not entry.get("_cas2_handled"):
                cas2_pnl_hit = self._check_pnl_trigger(entry) or self._check_tp3_by_ohlc(entry)
                if cas2_pnl_hit:
                    cas2_limit1_tk = None
                    for tk in entry["tickets"]:
                        if tk.get("role") == "limit_1":
                            cas2_limit1_tk = tk
                            break
                    cas2_limit1_order = None
                    for o in entry["orders"]:
                        if o.get("role") == "limit_1":
                            cas2_limit1_order = o
                            break
                    limit2_ticket = None
                    for tk in entry["tickets"]:
                        if tk.get("role") == "limit_2":
                            limit2_ticket = tk
                            break
                    limit2_order = None
                    for o in entry["orders"]:
                        if o.get("role") == "limit_2":
                            limit2_order = o
                            break
                    l1_filled = cas2_limit1_tk is not None and cas2_limit1_tk.get("entry_price", 0) > 0
                    l2_filled = limit2_ticket is not None and limit2_ticket.get("entry_price", 0) > 0

                    if not l1_filled and not l2_filled:
                        log.info(f"SIGNAL {signal_number} | CAS 2-b TP3 → 3-b-1 aucun rempli → annulation des 2 limits")
                        for o in list(entry["orders"]):
                            if o.get("role") in ("limit_1", "limit_2"):
                                self.bridge.cancel_order(o["order"])
                                entry["orders"].remove(o)
                        entry["_cas2_handled"] = True
                    elif l1_filled and not l2_filled:
                        log.info(f"SIGNAL {signal_number} | CAS 2-b TP3 → 3-b-2 limit_1 remplie → BE @ entry L1 + trail")
                        if limit2_order:
                            self.bridge.cancel_order(limit2_order["order"])
                            entry["orders"].remove(limit2_order)
                        if cas2_limit1_tk:
                            l1_entry = cas2_limit1_tk.get("entry_price", 0)
                            pos1 = self._get_pos(cas2_limit1_tk["ticket"])
                            if pos1:
                                self.bridge.modify_sl(cas2_limit1_tk["ticket"], l1_entry, "[C2b TP3 BE]")
                                cas2_limit1_tk["trail_active"] = True
                                cas2_limit1_tk["sl_step"] = 1
                                cas2_limit1_tk["trail_last_price"] = current
                                log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                                log.info(f"SL → {l1_entry} (prix d'entrée L1) | Ticket: #{cas2_limit1_tk['ticket']}")
                                log.info(f"Trailing activé | Dernier prix: {current}")
                        entry["_cas2_handled"] = True
                    elif l1_filled and l2_filled:
                        l1_entry = cas2_limit1_tk.get("entry_price", 0) if cas2_limit1_tk else 0
                        log.info(f"SIGNAL {signal_number} | CAS 2-b TP3 → 3-b-3 les 2 remplies → fermer L1, BE @{l1_entry} + trail L2")
                        if cas2_limit1_tk and self._get_pos(cas2_limit1_tk["ticket"]):
                            self.bridge.close_position(cas2_limit1_tk["ticket"], "C2b-TP3-close-L1")
                        if limit2_ticket:
                            pos2 = self._get_pos(limit2_ticket["ticket"])
                            if pos2 and l1_entry > 0:
                                self.bridge.modify_sl(limit2_ticket["ticket"], l1_entry, "[C2b TP3 BE]")
                                limit2_ticket["trail_active"] = True
                                limit2_ticket["sl_step"] = 1
                                limit2_ticket["trail_last_price"] = current
                                log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                                log.info(f"SL → {l1_entry} (prix d'entrée L1) | Ticket: #{limit2_ticket['ticket']}")
                                log.info(f"Trailing activé | Dernier prix: {current}")
                        entry["_cas2_handled"] = True

            # ── Trailing SL ──
            for t in entry["tickets"]:
                if not t.get("trail_active"):
                    continue
                if t.get("role", "").startswith("grade"):
                    continue
                pos = self._get_pos(t["ticket"])
                if not pos:
                    continue
                sym2 = mt5.symbol_info(pos.symbol)
                if sym2 is None:
                    continue
                d = sym2.digits
                trail_step = TRAIL_RATIO_R1
                trigger_step = TRAIL_RATIO_R2
                last_price = t.get("trail_last_price", 0)
                if action == "BUY":
                    price_moved = current - last_price
                    if price_moved >= trigger_step:
                        nsl = pos.sl + trail_step if pos.sl > 0 else current - trail_step
                        ok = self.bridge.modify_sl(t["ticket"], round(nsl, d), label="[Trail BUY]")
                        if ok:
                            t["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | Trail SL déplacé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL: {pos.sl} → {nsl} | Ticket: #{t['ticket']}")
                else:
                    price_moved = last_price - current
                    if price_moved >= trigger_step:
                        nsl = pos.sl - trail_step if pos.sl > 0 else current + trail_step
                        ok = self.bridge.modify_sl(t["ticket"], round(nsl, d), label="[Trail SELL]")
                        if ok:
                            t["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | Trail SL déplacé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL: {pos.sl} → {nsl} | Ticket: #{t['ticket']}")

            # ── GRADE ──
            if ACTIVE_GRADE and ch_num == NUM_CHANEL_GRADE:
                self._manage_grade(entry, symbol, action, current, sym_info, now)

            # ── GESTION BE POUR QUICK ALERT FUSIONNÉE ──
            if entry.get("_is_quick_alert") and not entry.get("_be_handled"):
                if self._check_pnl_trigger(entry):
                    entry["_be_handled"] = True
                    log.info(f"SIGNAL {signal_number} | QUICK ALERT BE déclenché (PnL min >= {PNL_TRIGGER_USD}$)")
                    market_ticket = None
                    limit_ticket = None
                    limit_order = None
                    for t in entry["tickets"]:
                        if t.get("role") == "quick_market":
                            market_ticket = t
                        elif t.get("role") in ("quick_limit", "quick_limit_filled"):
                            limit_ticket = t
                    for o in entry["orders"]:
                        if o.get("role") in ("quick_limit", "merge_limit"):
                            limit_order = o
                            break
                    if limit_order and not limit_ticket:
                        self.bridge.cancel_order(limit_order["order"])
                        entry["orders"].remove(limit_order)
                        position_to_keep = market_ticket
                        log.info("  Scénario 1 : LIMIT annulé, BE sur MARKET")
                    elif limit_ticket:
                        if market_ticket:
                            self.bridge.close_position(market_ticket["ticket"], "QA-BE-close-market")
                        position_to_keep = limit_ticket
                        log.info("  Scénario 2 : MARKET fermé, BE sur LIMIT")
                    else:
                        position_to_keep = market_ticket
                        log.info("  Cas particulier : BE sur MARKET seul")
                    if position_to_keep:
                        pos = self._get_pos(position_to_keep["ticket"])
                        if pos:
                            entry_price = market_ticket["entry_price"] if market_ticket else position_to_keep["entry_price"]
                            self.bridge.modify_sl(position_to_keep["ticket"], entry_price, "[QA BE]")
                            position_to_keep["trail_active"] = True
                            position_to_keep["sl_step"] = 1
                            position_to_keep["trail_last_price"] = current
                            log.info(f"SIGNAL {signal_number} | BE activé | {action} {symbol} | Canal: {canal}")
                            log.info(f"SL → {entry_price} (prix d'entrée) | Ticket: #{position_to_keep['ticket']}")
                            log.info(f"Trailing activé | Dernier prix: {current}")
                            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            send_alert_sync(
                                f"🔒 BE activé {action} {symbol}\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"SL → @{entry_price} (prix d'entrée)\n"
                                f"Ticket: #{position_to_keep['ticket']}\n"
                                f"Time: {now_str}\n"
                                f"Canal: {canal} | Quick Alert"
                            )

            # ── Fin du trade ──
            active_tks = [t for t in entry["tickets"] if self._get_pos(t["ticket"])]
            if not entry["orders"] and not active_tks:
                total_pnl = sum(t.get("_last_pnl", 0.0) for t in entry["tickets"])
                canal = sig.get("source_channel", "Inconnu")
                log.info(f"SIGNAL {signal_number} | Trade terminé ({symbol}) | Canal: {canal} | P&L total: {total_pnl:+.2f}")
                if hasattr(self, "tracker") and self.tracker:
                    self.tracker.log_trade_close(entry, total_pnl)
                self._update_daily_pnl(total_pnl)
                if _supa_connected and _supa:
                    supa_id = entry.get("_supa_trade_id")
                    if supa_id:
                        result_str = "WIN" if total_pnl > 0 else ("BE" if total_pnl == 0 else "LOSS")
                        open_date = entry.get("_open_date", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
                        try:
                            open_dt = datetime.strptime(open_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                            duree = (datetime.now(timezone.utc) - open_dt).total_seconds() / 60
                        except Exception:
                            duree = 0
                        _supa.log_trade_close(supa_id, result_str, total_pnl, duree)
                        if _tracker:
                            tracking_data = _tracker.track_close(supa_id, total_pnl, result_str)
                            if tracking_data:
                                _tracker.update_trade_tracking(supa_id, {
                                    "r_multiple": tracking_data["r_multiple"],
                                    "max_drawdown": tracking_data["max_drawdown"],
                                    "signal_type": tracking_data["signal_type"],
                                })
                with self._lock:
                    if entry in self.active:
                        self.active.remove(entry)


# =============================================================
# MAIN
# =============================================================
async def main():
    global _main_loop, _alert_client
    _main_loop = asyncio.get_running_loop()
    
    parser = SignalParser()
    bridge = MT5Bridge()
    tracker = PerformanceTracker()
    manager = None

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
    channel_list = [ch for _, ch in channel_names if ch]
    if _supa_connected and _supa:
        _supa.start_session(runtime_minutes=RUNTIME_MINUTES, channels=channel_list,
                            lot_size=LOT_SIZE, mode="DEMO" if DEMO_MODE else "LIVE")
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
            log.debug(f"[SPAM] {canal_name} : {text[:50].replace(chr(10), ' ')}")
            return

        log.info(f"[{canal_name}] {text[:150].replace(chr(10), ' | ')}")

        signal_data = parser.parse(text)
        if signal_data is None:
            log.debug(f"[PARSING ECHOUÉ] Message ignoré : {text[:200].replace(chr(10), ' ')}")
            return

        signal_data._source_channel = canal_name

        if signal_data.signal_type == "CLOSE":
            canal = canal_name
            ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), None))
            bridge.close_all(symbol=signal_data.close_symbol, channel_num=ch_num)
            log.info(f"CLOSE reçu → Fermeture de {signal_data.close_symbol or 'ALL'} sur canal {canal_name}")
            return

        elif signal_data.signal_type == "SL_MOVE":
            log.info(f"SL MOVE reçu → nouveau SL={signal_data.new_sl}")
            bridge.update_sl_all(signal_data.new_sl)
            return

        elif signal_data.signal_type == "TRADE":
            if NEWS_ENABLED and news_mgr.is_blocked():
                log.info("[NEWS] Signal ignoré — protection news")
                return

            blocked, reason = in_blocked_window()
            if blocked:
                log.info(f"[{canal_name}] Signal ignoré - Filtre horaire : {reason}")
                return

            if not manager._check_daily_pnl_limit():
                log.info(f"[{canal_name}] Signal ignoré - Limite de P&L quotidien atteinte ({DAILY_PROFIT_LIMIT}$)")
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
    log.info(f" TRADINGBOT V4.8.6 — {mode}")
    log.info(f" Canaux surveillés : {len(chats)}")
    for env_name, ch_value in channel_names:
        if ch_value:
            log.info(f"  {env_name} : {ch_value}")
    log.info(f" Lot : {LOT_SIZE} | Lot unique trade : {LOT_UNIQUE_TRADE}")
    log.info(f" TP par défaut alerte : RR={DEFAULT_ALERT_TP_RR}")
    log.info(f" Trail SL : {TRAIL_POINTS} pts")
    log.info(f" Poll interval : {POLL_INTERVAL_SEC}s | P&L trigger : {PNL_TRIGGER_USD}$")
    log.info(f" Quick alert SL offset : {QUICK_ALERT_SL_OFFSET}$")
    log.info(f" News filter : {'ON' if NEWS_ENABLED else 'OFF'}")
    log.info(f" Filtre horaire : {'ON' if TIME_FILTER_ENABLED else 'OFF'} ({TRADING_START_HOUR}h-{TRADING_END_HOUR}h UTC)")
    log.info(f" Max signaux actifs : {MAX_POSITIONS} (tous types confondus)")
    log.info(f" Limite P&L quotidien : {DAILY_PROFIT_LIMIT}$ (réalisé + flottant)")
    log.info(f" Logique prix unique : S1 (SL<prix<entry) → MARKET | S2 (entry<prix<TP1) → LIMIT")
    log.info(f" Signal zone : annulé si prix > TP2 (BUY) ou prix < TP2 (SELL)")
    if ACTIVE_GRADE:
        log.info(f" GRADE ACTIF sur canal {NUM_CHANEL_GRADE} | Reverse: {REVERSE_PRICE} | Profit: {REALISED_GRADE} | Max: {MAX_GRADE_POSITIONS}")
        log.info(f" NOTE : Les grades fonctionnent désormais pour les signaux normaux (CAS 1 et CAS 2-a)")
    else:
        log.info(" GRADE : désactivé")
    if RUNTIME_MINUTES > 0:
        end = START_TIME + timedelta(minutes=RUNTIME_MINUTES)
        log.info(f" Session : {RUNTIME_MINUTES} min (fin {end:%H:%M})")
    log.info(f" Performance : Supabase")
    log.info("=" * 55)

    try:
        await client.run_until_disconnected()
    finally:
        if _supa_connected and _supa:
            total_t = len(tracker._trades_cache)
            total_p = sum(t.get("pnl", 0) for t in tracker._trades_cache)
            _supa.end_session(total_t, total_p)
        if manager:
            manager.stop()
        if news_mgr:
            news_mgr.stop()
        bridge.disconnect()
        tracker.print_final_report()
        log.info("[SHUTDOWN] Bot arrêté proprement.")

if __name__ == "__main__":
    asyncio.run(main())