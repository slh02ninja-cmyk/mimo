"""
=============================================================
 TELEGRAM → MT5 | Bot Trading
 Version 4.9.0 — TIMESFM VALIDATOR INTÉGRÉ
 Basé sur v4.8.6 — GAIN FIXE + BE OPTIMISÉ + TP_TRIGGER PENDING
 NOUVEAUTÉ : Validateur TimesFM (filtre de direction avant exécution)
=============================================================
"""

import subprocess, sys
_deps = {
    "dotenv": "python-dotenv",
    "telethon": "telethon",
    "MetaTrader5": "MetaTrader5",
}
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
API_ID           = int(os.getenv("TG_API_ID", "0"))
API_HASH         = os.getenv("TG_API_HASH", "")
CHANNEL_NAME     = os.getenv("TG_CHANNEL_1", os.getenv("TG_CHANNEL", ""))
CHANNEL_NAME_2   = os.getenv("TG_CHANNEL_2", "")
CHANNEL_NAME_3   = os.getenv("TG_CHANNEL_3", "")
CHANNEL_NAME_4   = os.getenv("TG_CHANNEL_4", "")
CHANNEL_NAME_5   = os.getenv("TG_CHANNEL_5", "")
CHANNEL_NAME_6   = os.getenv("TG_CHANNEL_6", "")
CHANNEL_NAME_7   = os.getenv("TG_CHANNEL_7", "")
CHANNEL_NAME_8   = os.getenv("TG_CHANNEL_8", "")
CHANNEL_NAME_9   = os.getenv("TG_CHANNEL_9", "")

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

MAGIC_NUMBER       = int(os.getenv("MAGIC_NUMBER", "20250226"))
SLIPPAGE           = int(os.getenv("SLIPPAGE", "20"))
ORDER_EXPIRY_MIN   = int(os.getenv("ORDER_EXPIRY_MINUTES", "240"))
LOT_SIZE           = float(os.getenv("LOT_TOTAL", "0.01"))
LOT_UNIQUE_TRADE   = float(os.getenv("LOT_UNIQUE_TRADE", "0.01"))
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS", "3"))
MAX_SPREAD_POINTS  = float(os.getenv("MAX_SPREAD_POINTS", "50"))

# === GAIN FIXE ===
TP_FIXED_ENABLED   = os.getenv("TP_FIXED_ENABLED", "true").lower() == "true"
TP_FIXED_GAIN_USD  = float(os.getenv("TP_FIXED_GAIN_USD", "15.0"))
PNL_TRIGGER_USD    = float(os.getenv("PNL_TRIGGER_USD", "8.0"))

# === FILTRES ===
TIME_FILTER_ENABLED  = os.getenv("TIME_FILTER_ENABLED", "true").lower() == "true"
TRADING_START_HOUR   = int(os.getenv("TRADING_START_HOUR", "3"))
TRADING_END_HOUR     = int(os.getenv("TRADING_END_HOUR", "20"))
DAILY_PROFIT_LIMIT   = float(os.getenv("DAILY_PROFIT_LIMIT", "30.0"))

# === AUTRES ===
TG_ALERT_CHANNEL    = os.getenv("TG_ALERT_CHANNEL", "")
ACTIVE_GRADE        = os.getenv("ACTIVE_GRADE", "false").lower() == "true"
NUM_CHANEL_GRADE    = int(os.getenv("NUM_CHANEL_GRADE", "0"))
REVERSE_PRICE       = float(os.getenv("REVERSE_PRICE", "2.0"))
REALISED_GRADE      = float(os.getenv("REALISED_GRADE", "3.0"))
MAX_GRADE_POSITIONS = int(os.getenv("MAX_GRADE_POSITIONS", "10"))
DEMO_MODE           = os.getenv("DEMO_MODE", "true").lower() == "true"
NEWS_ENABLED        = os.getenv("NEWS_FILTER_ENABLED", "false").lower() == "true"
NEWS_BLOCK_MIN      = int(os.getenv("NEWS_WINDOW_BEFORE_BLOCK", "15"))
NEWS_CLOSE_MIN      = int(os.getenv("NEWS_WINDOW_BEFORE_CLOSE", "5"))
NEWS_AFTER_MIN      = int(os.getenv("NEWS_WINDOW_AFTER", "15"))
POLL_INTERVAL_SEC   = int(os.getenv("POLL_INTERVAL_SEC", "1"))
RUNTIME_MINUTES     = int(os.getenv("RUNTIME_MINUTES", "0"))

# =============================================================
# CONFIG TIMESFM
# =============================================================
TIMESFM_ENABLED         = os.getenv("TIMESFM_ENABLED", "true").lower() == "true"
TIMESFM_TIMEFRAME       = os.getenv("TIMESFM_TIMEFRAME", "M5")   # M1, M5, M15, M30, H1
TIMESFM_CONTEXT_BARS    = int(os.getenv("TIMESFM_CONTEXT_BARS", "256"))
TIMESFM_HORIZON         = int(os.getenv("TIMESFM_HORIZON", "12"))
TIMESFM_MIN_MOVE_PIPS   = float(os.getenv("TIMESFM_MIN_MOVE_PIPS", "5.0"))
TIMESFM_MIN_CONFIDENCE  = float(os.getenv("TIMESFM_MIN_CONFIDENCE", "0.35"))
TIMESFM_SYMBOL          = os.getenv("TIMESFM_SYMBOL", "XAUUSDm")  # symbole MT5 exact

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
_main_loop    = None

def send_alert_sync(message: str):
    if not TG_ALERT_CHANNEL or not _alert_client or not _main_loop:
        return
    coro = _alert_client.send_message(TG_ALERT_CHANNEL, message)
    future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
    try:
        future.result(timeout=5)
    except Exception as e:
        log.warning(f"[ALERT] Erreur envoi alerte Telegram (sync): {e}")

# =============================================================
# PERFORMANCE TRACKER
# =============================================================
class PerformanceTracker:
    def __init__(self):
        self._trades_cache = []
        self._report_sent  = False

    def log_trade_open(self, entry):
        sig = entry["signal"]
        now = datetime.now(timezone.utc)
        row = {
            "canal":       sig.get("source_channel", "Inconnu"),
            "symbol":      sig["symbol"],
            "action":      sig["action"],
            "result":      "OPEN",
            "pnl":         0.0,
            "duree_min":   0,
            "_entry_time": now,
            "_entry":      entry,
        }
        self._trades_cache.append(row)

    def log_trade_close(self, entry, total_pnl):
        sig    = entry["signal"]
        canal  = sig.get("source_channel", "Inconnu")
        now    = datetime.now(timezone.utc)
        result = "WIN" if total_pnl > 0 else ("BE" if total_pnl == 0 else "LOSS")
        for t in reversed(self._trades_cache):
            if (t["canal"] == canal and
                    t["symbol"] == sig["symbol"] and
                    t["action"] == sig["action"] and
                    t["result"] == "OPEN"):
                entry_time = t.get("_entry_time", now)
                duree = (now - entry_time).total_seconds() / 60
                t["result"]    = result
                t["pnl"]       = round(total_pnl, 2)
                t["duree_min"] = round(duree, 1)
                break

    def format_session_summary(self) -> str:
        if not self._trades_cache:
            return "📊 Aucun trade cette session."
        wins       = sum(1 for t in self._trades_cache if t["result"] == "WIN")
        losses     = sum(1 for t in self._trades_cache if t["result"] == "LOSS")
        be         = sum(1 for t in self._trades_cache if t["result"] == "BE")
        still_open = sum(1 for t in self._trades_cache if t["result"] == "OPEN")
        total_pnl  = sum(t["pnl"] for t in self._trades_cache)
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
# SIGNAL PARSER
# =============================================================
from signal_parser import SignalParser, is_spam, TradeSignal

# =============================================================
# TIMESFM VALIDATOR
# =============================================================
_TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
}

class TimesFMValidator:
    """
    Valide la direction d'un signal Telegram en comparant
    avec la prévision TimesFM sur l'historique MT5.

    Nécessite : pip install timesfm[torch]
    Modèle utilisé : TimesFM 2.5 (200M paramètres, google/timesfm-2.5-200m-pytorch)
    """

    def __init__(self):
        self._model   = None
        self._ready   = False
        self._loading = False
        self._lock    = threading.Lock()

        if TIMESFM_ENABLED:
            # Chargement en arrière-plan pour ne pas bloquer le démarrage
            t = threading.Thread(target=self._load_model, daemon=True)
            t.start()

    def _load_model(self):
        with self._lock:
            if self._ready or self._loading:
                return
            self._loading = True
        try:
            log.info("[TIMESFM] Chargement du modèle TimesFM 2.5 …")
            # Installation automatique si absent
            try:
                import timesfm  # noqa: F401
            except ImportError:
                log.info("[TIMESFM] Installation de timesfm[torch] …")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "timesfm[torch]", "-q"]
                )

            import timesfm
            import torch

            torch.set_float32_matmul_precision("high")

            model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                "google/timesfm-2.5-200m-pytorch"
            )
            model.compile(
                timesfm.ForecastConfig(
                    max_context=TIMESFM_CONTEXT_BARS,
                    max_horizon=TIMESFM_HORIZON,
                    normalize_inputs=True,
                    use_continuous_quantile_head=True,
                )
            )
            with self._lock:
                self._model  = model
                self._ready  = True
                self._loading = False
            log.info("[TIMESFM] ✅ Modèle chargé et prêt.")
        except Exception as e:
            with self._lock:
                self._loading = False
            log.warning(f"[TIMESFM] ⚠️  Impossible de charger le modèle : {e}")
            log.warning("[TIMESFM] Le bot fonctionnera sans validation TimesFM.")

    # ----------------------------------------------------------
    def _get_closes(self) -> list[float] | None:
        """Récupère les cours de clôture depuis MT5."""
        tf_key = TIMESFM_TIMEFRAME.upper()
        tf     = _TF_MAP.get(tf_key, mt5.TIMEFRAME_M5)
        symbol = TIMESFM_SYMBOL

        # Vérifier / activer le symbole
        info = mt5.symbol_info(symbol)
        if info is None:
            log.warning(f"[TIMESFM] Symbole {symbol} introuvable dans MT5")
            return None
        if not info.visible:
            mt5.symbol_select(symbol, True)
            time.sleep(0.3)

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, TIMESFM_CONTEXT_BARS)
        if rates is None or len(rates) == 0:
            log.warning(f"[TIMESFM] Aucune donnée pour {symbol} {tf_key}")
            return None

        import numpy as np
        closes = np.array([r[4] for r in rates], dtype=float)  # index 4 = close
        return closes.tolist()

    # ----------------------------------------------------------
    def validate(self, signal_direction: str) -> dict:
        """
        Valide un signal.

        Retourne :
            {
                "valid":               bool,
                "reason":              str,
                "predicted_direction": str,
                "confidence":          float,
                "predicted_move_pips": float,
            }
        """
        _pass = {
            "valid": True,
            "reason": "TimesFM désactivé ou non prêt",
            "predicted_direction": signal_direction,
            "confidence": 0.0,
            "predicted_move_pips": 0.0,
        }

        if not TIMESFM_ENABLED:
            return _pass

        with self._lock:
            ready = self._ready
            model = self._model

        if not ready or model is None:
            log.info("[TIMESFM] Modèle non prêt → signal accepté sans validation")
            return _pass

        try:
            import numpy as np

            closes = self._get_closes()
            if closes is None or len(closes) < 32:
                log.warning("[TIMESFM] Historique insuffisant → signal accepté")
                return _pass

            point_forecast, quantile_forecast = model.forecast(
                horizon=TIMESFM_HORIZON,
                inputs=[np.array(closes)],
            )

            predicted   = point_forecast[0]       # array (horizon,)
            last_price  = closes[-1]
            pred_end    = float(predicted[-1])

            # Direction prédite
            pred_dir = "BUY" if pred_end > last_price else "SELL"

            # Amplitude en pips (Gold : 1 pip = 0.1)
            move_pips = abs(pred_end - last_price) / 0.1

            # Confiance basée sur l'écart quantile 10%-90%
            q10 = float(quantile_forecast[0, -1, 0])
            q90 = float(quantile_forecast[0, -1, -1])
            spread = abs(q90 - q10)
            raw_move = abs(pred_end - last_price)
            confidence = max(0.0, 1.0 - (spread / (raw_move + 1e-6)))
            confidence = min(confidence, 1.0)

            direction_ok  = (pred_dir == signal_direction)
            move_ok       = (move_pips >= TIMESFM_MIN_MOVE_PIPS)
            confidence_ok = (confidence >= TIMESFM_MIN_CONFIDENCE)

            valid = direction_ok and move_ok and confidence_ok

            reasons = []
            if not direction_ok:
                reasons.append(f"direction prédite={pred_dir} ≠ signal={signal_direction}")
            if not move_ok:
                reasons.append(f"move={move_pips:.1f} pips < min={TIMESFM_MIN_MOVE_PIPS}")
            if not confidence_ok:
                reasons.append(f"confiance={confidence:.2f} < min={TIMESFM_MIN_CONFIDENCE}")

            reason = " | ".join(reasons) if reasons else "OK"

            log.info(
                f"[TIMESFM] Signal={signal_direction} Prédit={pred_dir} "
                f"Move={move_pips:.1f}pips Conf={confidence:.2f} → {'✅ VALID' if valid else '❌ REJETÉ'}"
            )
            if not valid:
                log.info(f"[TIMESFM] Raison rejet : {reason}")

            return {
                "valid":               valid,
                "reason":              reason,
                "predicted_direction": pred_dir,
                "confidence":          round(confidence, 2),
                "predicted_move_pips": round(move_pips, 1),
            }

        except Exception as e:
            log.error(f"[TIMESFM] Erreur lors de la validation : {e}")
            # En cas d'erreur, on laisse passer le signal
            return _pass


# Instance globale unique (chargement modèle en background)
timesfm_validator = TimesFMValidator()

# =============================================================
# NEWS MANAGER
# =============================================================
class NewsManager:
    FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, bridge):
        self.bridge  = bridge
        self.manager = None
        self._news   = []
        self._blocked = False
        self._stop   = False
        self._task   = None

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
                    log.info(
                        f"[NEWS] {news.get('title', '?')} dans {diff_minutes:.0f} min "
                        f"→ fermeture positions"
                    )
                    if self.manager:
                        self._close_all()
                    break
            elif NEWS_CLOSE_MIN < diff_minutes <= NEWS_BLOCK_MIN:
                if not self._blocked:
                    self._blocked = True
                    log.info(
                        f"[NEWS] {news.get('title', '?')} dans {diff_minutes:.0f} min "
                        f"→ signaux bloqués"
                    )
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
                log.info(
                    f"MT5 déjà connecté → {info.name} | Balance: {info.balance} {info.currency}"
                )
                return self._check_algo()
        mt5.shutdown()
        if not mt5.initialize(
            login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER,
            path=MT5_PATH if os.path.exists(MT5_PATH) else None,
        ):
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
        vol_min  = sym_info.volume_min
        vol_max  = sym_info.volume_max
        vol_step = sym_info.volume_step
        if lot < vol_min:
            lot = vol_min
        elif lot > vol_max:
            lot = vol_max
        if vol_step > 0:
            lot = round(lot / vol_step) * vol_step
            lot = round(lot, 8)
        return lot

    def place_market_order(
        self, signal: dict, lot: float, tp: float, sl: float = 0.0,
        comment: str = "TG-market"
    ) -> int | None:
        sym = self._sym(signal["symbol"])
        if not sym:
            return None
        lot    = self._validate_volume(sym, lot)
        action = signal["action"]
        tick   = mt5.symbol_info_tick(sym.name)
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
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       sym.name,
                "volume":       lot,
                "type":         otype,
                "price":        price,
                "sl":           round(sl, sym.digits) if sl else 0,
                "tp":           round(tp, sym.digits) if tp else 0,
                "deviation":    SLIPPAGE,
                "magic":        MAGIC_NUMBER,
                "comment":      comment,
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": fill_mode,
            })
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info(f"MARKET {action} {sym.name} lot={lot} @{price} ticket#{result.order}")
                return result.order
        return None

    def place_limit_order(
        self, signal: dict, lot: float, price: float, tp: float,
        expiry: datetime, comment: str = "TG-limit"
    ) -> int | None:
        sym = self._sym(signal["symbol"])
        if not sym:
            return None
        lot    = self._validate_volume(sym, lot)
        action = signal["action"]
        if tp:
            if action == "BUY"  and tp <= price:
                return None
            if action == "SELL" and tp >= price:
                return None
        otype   = mt5.ORDER_TYPE_BUY_LIMIT if action == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        filling = self._get_filling(sym)
        result  = mt5.order_send({
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       sym.name,
            "volume":       lot,
            "type":         otype,
            "price":        round(price, sym.digits),
            "sl":           round(signal.get("sl", 0), sym.digits) if signal.get("sl", 0) else 0,
            "tp":           round(tp, sym.digits) if tp else 0,
            "deviation":    SLIPPAGE,
            "magic":        MAGIC_NUMBER,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_SPECIFIED,
            "expiration":   int(expiry.timestamp()),
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
        pos  = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        cprice  = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        ctype   = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        filling = self._get_filling(mt5.symbol_info(pos.symbol))
        result  = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       pos.volume,
            "type":         ctype,
            "position":     ticket,
            "price":        cprice,
            "deviation":    SLIPPAGE,
            "magic":        MAGIC_NUMBER,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
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
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   pos.symbol,
            "position": ticket,
            "sl":       round(new_sl, sym.digits),
            "tp":       pos.tp,
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
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   pos.symbol,
            "position": ticket,
            "sl":       round(new_sl, sym.digits),
            "tp":       round(new_tp, sym.digits),
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.info(f"SL/TP modifiés #{ticket} → SL={new_sl} TP={new_tp} {label}")
        return ok

    # ★★★ BUG #4 : modifier un ordre pending ★★★
    def modify_pending_order(
        self, order_ticket: int, new_sl: float, new_tp: float, label: str = ""
    ) -> bool:
        orders = mt5.orders_get(ticket=order_ticket)
        if not orders:
            log.warning(f"Ordre pending #{order_ticket} introuvable")
            return False
        order = orders[0]
        sym   = mt5.symbol_info(order.symbol)
        if sym is None:
            log.warning(f"Symbole introuvable pour l'ordre #{order_ticket}")
            return False
        result = mt5.order_send({
            "action":      mt5.TRADE_ACTION_MODIFY,
            "order":       order_ticket,
            "price":       order.price_open,
            "sl":          round(new_sl, sym.digits),
            "tp":          round(new_tp, sym.digits),
            "type_time":   order.type_time,
            "expiration":  order.time_expiration,
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.info(f"Ordre pending modifié #{order_ticket} → SL={new_sl} TP={new_tp} {label}")
        else:
            log.error(f"Échec modification ordre pending #{order_ticket}")
        return ok

    # ★★★ BUG #5 : SL_MOVE filtré par canal ★★★
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
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   pos.symbol,
                "position": pos.ticket,
                "sl":       round(new_sl, sym.digits),
                "tp":       pos.tp,
            })
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                updated += 1
                log.info(f"SL modifié #{pos.ticket} (canal CH{channel_num}) → {new_sl}")
        log.info(f"SL MOVE appliqué sur {updated} position(s) du canal CH{channel_num}")

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
                    "action":   mt5.TRADE_ACTION_SLTP,
                    "symbol":   pos.symbol,
                    "position": pos.ticket,
                    "sl":       round(new_sl, sym.digits),
                    "tp":       pos.tp,
                })
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    updated += 1
        log.info(f"SL MOVE appliqué sur {updated} positions → SL={new_sl}")

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
# TRADE MANAGER
# =============================================================
class TradeManager:
    def __init__(self, bridge: MT5Bridge, tracker=None):
        self.bridge  = bridge
        self.tracker = tracker
        self.active  = []
        self._lock   = threading.Lock()
        self._stop   = False
        self._task   = None

        self._daily_pnl     = self._recover_daily_pnl()
        self._daily_pnl_day = get_trading_day_start().day
        log.info(f"[DAILY P&L] Récupéré depuis l'historique : {self._daily_pnl:.2f}$")

        # ★★★ BUG #8 : cache pour _resolve_order() ★★★
        self._order_cache       = {}   # {order_ticket: position_ticket ou None}
        self._cache_ttl         = 60   # secondes
        self._cache_timestamps  = {}   # {order_ticket: datetime}

    # ----------------------------------------------------------
    # P&L QUOTIDIEN
    # ----------------------------------------------------------
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
        return sum(p.profit for p in positions if p.magic == MAGIC_NUMBER)

    def _update_daily_pnl(self, pnl: float):
        start = get_trading_day_start()
        if start.day != self._daily_pnl_day:
            self._daily_pnl     = 0.0
            self._daily_pnl_day = start.day
            log.info(f"[DAILY P&L] Reset journalier à {TRADING_START_HOUR}h UTC")
        self._daily_pnl += pnl
        total = self._daily_pnl + self._get_floating_pnl()
        log.info(
            f"[DAILY P&L] Réalisé {self._daily_pnl:.2f} | "
            f"Flottant {self._get_floating_pnl():.2f} | "
            f"Total {total:.2f} / {DAILY_PROFIT_LIMIT:.2f}"
        )

    def _check_daily_pnl_limit(self) -> bool:
        start = get_trading_day_start()
        if start.day != self._daily_pnl_day:
            self._daily_pnl     = 0.0
            self._daily_pnl_day = start.day
            log.info(f"[DAILY P&L] Reset journalier à {TRADING_START_HOUR}h UTC")
        total_pnl = self._daily_pnl + self._get_floating_pnl()
        if total_pnl >= DAILY_PROFIT_LIMIT:
            log.info(f"[DAILY P&L] Limite atteinte : {total_pnl:.2f}$")
            return False
        return True

    # ----------------------------------------------------------
    # ARRÊT QUOTIDIEN
    # ----------------------------------------------------------
    def _cancel_all_pending_orders(self) -> int:
        orders = mt5.orders_get()
        if not orders:
            return 0
        cancelled = 0
        for order in orders:
            if order.magic == MAGIC_NUMBER:
                if self.bridge.cancel_order(order.ticket):
                    cancelled += 1
                    self._order_cache.pop(order.ticket, None)
                    self._cache_timestamps.pop(order.ticket, None)
        log.info(f"📌 Annulation de {cancelled} ordre(s) pending (tous signaux)")
        return cancelled

    def _close_all_positions(self) -> float:
        positions = mt5.positions_get()
        if not positions:
            return 0.0
        total_pnl = 0.0
        for pos in positions:
            if pos.magic == MAGIC_NUMBER:
                if self.bridge.close_position(pos.ticket, comment="DAILY-LIMIT-CLOSE"):
                    total_pnl += pos.profit
                    log.info(f"  ✓ Fermeture #{pos.ticket} (P&L={pos.profit:.2f})")
        log.info("📌 Fermeture de toutes les positions")
        return total_pnl

    def _clear_all_entries(self):
        with self._lock:
            for entry in self.active:
                entry["orders"] = []
                for t in entry.get("tickets", []):
                    t["_daily_limit_closed"] = True
            self.active.clear()
        log.info("📌 Liste des entrées vidée")

    def _shutdown_for_daily_limit(self):
        log.info("=" * 55)
        log.info("🚨 OBJECTIF QUOTIDIEN ATTEINT !")
        log.info(f"   Limite: {DAILY_PROFIT_LIMIT}$")
        self._cancel_all_pending_orders()
        total_pnl = self._close_all_positions()
        if total_pnl != 0:
            self._update_daily_pnl(total_pnl)
        self._clear_all_entries()
        total = self._daily_pnl + self._get_floating_pnl()
        send_alert_sync(
            f"🚨 OBJECTIF QUOTIDIEN ATTEINT !\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 P&L total: {total:.2f}$\n"
            f"🎯 Limite: {DAILY_PROFIT_LIMIT}$\n"
            f"📌 Toutes les positions sont fermées\n"
            f"📌 Tous les ordres sont annulés\n"
            f"⏸️ Trading arrêté pour aujourd'hui"
        )
        log.info("=" * 55)

    # ----------------------------------------------------------
    # GESTION DU BE
    # ----------------------------------------------------------
    def _cancel_pending_orders_for_entry(self, entry: dict):
        orders_to_cancel = [o.get("order", 0) for o in entry.get("orders", []) if o.get("order")]
        if not orders_to_cancel:
            return
        log.info(f"📌 Annulation des ordres pending du signal {entry.get('_signal_id', '?')}")
        for ticket in orders_to_cancel:
            self.bridge.cancel_order(ticket)
            self._order_cache.pop(ticket, None)
            self._cache_timestamps.pop(ticket, None)
            log.info(f"  ✓ Annulation ordre pending #{ticket}")
        entry["orders"] = []

    def _get_gain_per_position(self, entry: dict) -> float:
        signal     = entry.get("signal", {})
        action     = signal.get("action", "")
        zone_low   = signal.get("zone_low", 0)
        zone_high  = signal.get("zone_high", 0)
        entry_price = (zone_low + zone_high) / 2
        tps        = signal.get("tps", [])
        if not tps:
            return TP_FIXED_GAIN_USD
        tp_final = tps[-1]
        if action == "BUY":
            potential_gain = tp_final - entry_price
        else:
            potential_gain = entry_price - tp_final
        return min(TP_FIXED_GAIN_USD, potential_gain)

    def _get_tp_trigger(self, entry: dict) -> float:
        tps = entry.get("signal", {}).get("tps", [])
        if len(tps) >= 3:
            return tps[2]
        elif len(tps) >= 2:
            return tps[1]
        elif len(tps) >= 1:
            return tps[0]
        return 0.0

    def _apply_be_on_open_positions(self, entry: dict, action: str):
        self._cancel_pending_orders_for_entry(entry)

        open_tickets = [t for t in entry.get("tickets", []) if self._get_pos(t["ticket"])]
        open_count   = len(open_tickets)
        if open_count == 0:
            log.warning(
                f"Aucune position ouverte au moment du BE pour le signal "
                f"{entry.get('_signal_id', '?')}"
            )
            return

        if open_count == 1:
            t = open_tickets[0]
            entry_price = t.get("entry_price", 0)
            if entry_price == 0:
                return
            pos = self._get_pos(t["ticket"])
            if pos:
                sym      = mt5.symbol_info(pos.symbol)
                be_price = round(entry_price, sym.digits if sym else 2)
                log.info(f"🔒 BE 1 POSITION : SL = {be_price:.2f} (P&L = 0$)")
                if self.bridge.modify_sl(t["ticket"], be_price, f"[BE 1POS @{be_price}]"):
                    t["be_active"] = True
                    t["be_sl"]     = be_price
                    log.info(f"  ✓ BE sur #{t['ticket']} → SL={be_price}")
            gain_per_position = self._get_gain_per_position(entry)
            target_gain       = gain_per_position * 1

        elif open_count == 2:
            entry_1 = open_tickets[0].get("entry_price", 0)
            entry_2 = open_tickets[1].get("entry_price", 0)
            if entry_1 == 0 or entry_2 == 0:
                return
            be_price = (entry_1 + entry_2) / 2
            pos = self._get_pos(open_tickets[0]["ticket"])
            if pos:
                sym      = mt5.symbol_info(pos.symbol)
                be_price = round(be_price, sym.digits if sym else 2)
            log.info(f"🔒 BE 2 POSITIONS : prix médian = {be_price:.2f}")
            log.info(f"   Pos1 entry={entry_1:.2f} → P&L={be_price - entry_1:+.2f}")
            log.info(f"   Pos2 entry={entry_2:.2f} → P&L={be_price - entry_2:+.2f}")
            log.info(f"   P&L TOTAL si SL touché = 0$ ✅")
            for t in open_tickets:
                if self.bridge.modify_sl(t["ticket"], be_price, f"[BE 2POS @{be_price}]"):
                    t["be_active"] = True
                    t["be_sl"]     = be_price
                    log.info(f"  ✓ BE sur #{t['ticket']} → SL={be_price}")
            gain_per_position = self._get_gain_per_position(entry)
            target_gain       = gain_per_position * 2
        else:
            log.warning(f"Nombre de positions inattendu : {open_count}")
            return

        entry["_target_gain"]          = target_gain
        entry["_be_activated"]         = True
        entry["_open_positions_at_be"] = open_count
        log.info(
            f"   Signal {entry.get('_signal_id', '?')} : "
            f"Objectif = {target_gain:.2f}$ ({gain_per_position:.2f}$ × {open_count})"
        )

        signal   = entry.get("signal", {})
        canal    = signal.get("source_channel", "Inconnu")
        symbol   = signal["symbol"]
        be_type  = "1POS (entry)" if open_count == 1 else "2POS (médian)"
        send_alert_sync(
            f"🔒 BE ACTIVÉ {action} {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Positions: {open_count} ({be_type})\n"
            f"Objectif: {target_gain:.2f}$\n"
            f"SL: {be_price:.2f}\n"
            f"Ordres pending du signal: ANNULÉS\n"
            f"Canal: {canal}"
        )

    # ----------------------------------------------------------
    # TP_TRIGGER PENDING UNIQUEMENT
    # ----------------------------------------------------------
    def _check_pending_only_expiry(self, entry: dict, symbol: str, action: str):
        has_open_position = any(self._get_pos(t["ticket"]) for t in entry.get("tickets", []))
        if has_open_position:
            return
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
        current   = tick.bid if action == "BUY" else tick.ask
        triggered = (action == "BUY" and current >= tp_trigger) or \
                    (action == "SELL" and current <= tp_trigger)
        if triggered:
            log.info(
                f"⚠️ TP_TRIGGER ({tp_trigger:.2f}) atteint sans position ouverte "
                f"→ annulation des ordres pending"
            )
            self._cancel_pending_orders_for_entry(entry)
            signal = entry.get("signal", {})
            send_alert_sync(
                f"⚠️ ANNULATION DES ORDRES PENDING\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{action} {symbol}\n"
                f"TP_TRIGGER ({tp_trigger:.2f}) atteint\n"
                f"Aucune position ouverte\n"
                f"Canal: {signal.get('source_channel', 'Inconnu')}"
            )

    # ----------------------------------------------------------
    # MÉTHODES UTILITAIRES
    # ----------------------------------------------------------
    def _get_pos(self, ticket: int):
        r = mt5.positions_get(ticket=ticket)
        return r[0] if r else None

    # ★★★ BUG #3 : utiliser position_id ★★★
    def _get_last_pnl(self, ticket: int, symbol: str) -> float:
        start = get_trading_day_start()
        deals = mt5.history_deals_get(symbol=symbol, from_time=start)
        if deals is None:
            return 0.0
        for deal in reversed(deals):
            if deal.position_id == ticket and deal.entry == mt5.DEAL_ENTRY_OUT:
                return deal.profit
        return 0.0

    def _get_close_reason(self, ticket: int, symbol: str) -> str:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(since, datetime.now(timezone.utc))
        if deals:
            for deal in reversed(deals):
                if deal.symbol == symbol and (
                    deal.position_id == ticket or deal.order == ticket
                ):
                    if deal.entry == mt5.DEAL_ENTRY_OUT:
                        if deal.reason == mt5.DEAL_REASON_TP:
                            return "TP"
                        elif deal.reason == mt5.DEAL_REASON_SL:
                            return "SL"
        return "OTHER"

    def _check_pnl_trigger(self, entry: dict) -> bool:
        for t in entry.get("tickets", []):
            if t.get("be_active"):
                continue
            pos = self._get_pos(t["ticket"])
            if pos and pos.profit >= PNL_TRIGGER_USD:
                return True
        return False

    # ----------------------------------------------------------
    # BOUCLE PRINCIPALE
    # ----------------------------------------------------------
    async def start(self):
        self._task = asyncio.create_task(self._loop_async())

    def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()

    def register(self, entry: dict):
        with self._lock:
            self.active.append(entry)
        sig   = entry["signal"]
        canal = sig.get("source_channel", "Inconnu")
        mode  = "DEMO" if DEMO_MODE else "LIVE"
        log.info(
            f"TradeManager [{mode}]: {sig['action']} {sig['symbol']} "
            f"Canal: {canal} | {len(entry['orders'])} ordres"
        )

    async def _loop_async(self):
        while not self._stop:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                await asyncio.to_thread(self._check_all)
            except Exception as exc:
                log.error(f"TradeManager erreur: {exc}")

    def _check_all(self):
        now = datetime.now(timezone.utc)

        # ── Vérification du P&L quotidien ──
        if not self._check_daily_pnl_limit():
            if self.active:
                log.warning("[DAILY P&L] Limite atteinte ! Fermeture de toutes les positions et annulation des ordres.")
                self._shutdown_for_daily_limit()
            if not self.active:
                return

        with self._lock:
            entries_snapshot = list(self.active)

        for entry in entries_snapshot:
            signal = entry.get("signal", {})
            symbol = signal.get("symbol", "")
            action = signal.get("action", "")
            canal  = signal.get("source_channel", "Inconnu")

            # ── Résoudre les ordres pending ──
            still_pending = []
            for o in entry.get("orders", []):
                pos = self._resolve_order(o["order"], symbol)
                if pos:
                    tk = {
                        "ticket":      pos.ticket,
                        "lot":         o["lot"],
                        "role":        o["role"],
                        "entry_price": pos.price_open,
                        "tp_index":    o.get("tp_index", 0),
                        "tp_target":   o.get("tp_target", 0),
                        "tp3":         o.get("tp3", 0),
                        "tp_final":    o.get("tp_final", 0),
                        "sl_step":     0,
                        "trail_active": False,
                        "be_active":   False,
                        "be_sl":       0,
                    }
                    entry["tickets"].append(tk)
                    log.info(f"Ordre #{o['order']} rempli → ticket={pos.ticket} @{pos.price_open}")
                    send_alert_sync(
                        f"✅ LIMIT REMPLI {action} {symbol}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"Prix: @{pos.price_open} | Lot: {o['lot']}\n"
                        f"Ticket: #{pos.ticket}\n"
                        f"Canal: {canal}"
                    )
                elif now > entry.get("expiry", now):
                    self.bridge.cancel_order(o["order"])
                    self._order_cache.pop(o["order"], None)
                    self._cache_timestamps.pop(o["order"], None)
                    log.info(f"Ordre #{o['order']} expiré → annulation")
                else:
                    still_pending.append(o)
            entry["orders"] = still_pending

            # ── Vérifier si un ticket est fermé ──
            for t in entry.get("tickets", []):
                pos = self._get_pos(t["ticket"])
                if pos is None and not t.get("_reported"):
                    t["_reported"]  = True
                    pnl             = self._get_last_pnl(t["ticket"], symbol)
                    t["_last_pnl"]  = pnl
                    close_reason    = self._get_close_reason(t["ticket"], symbol)
                    emoji           = "🎯" if close_reason == "TP" else ("🛑" if close_reason == "SL" else "⚪")
                    result          = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BE")
                    send_alert_sync(
                        f"{emoji} FERMÉ {action} {symbol} ({close_reason})\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"P&L: {pnl:+.2f}$ ({result})\n"
                        f"Ticket: #{t['ticket']}\n"
                        f"Canal: {canal}"
                    )

            # ── Compter les positions actives ──
            active_tickets = [t for t in entry.get("tickets", []) if self._get_pos(t["ticket"])]

            # ── Si plus de positions ni d'ordres, terminer ──
            if not entry.get("orders") and not active_tickets:
                total_pnl = sum(t.get("_last_pnl", 0.0) for t in entry.get("tickets", []))
                log.info(
                    f"Trade terminé ({symbol}) | Canal: {canal} | P&L total: {total_pnl:+.2f}"
                )
                if self.tracker:
                    self.tracker.log_trade_close(entry, total_pnl)
                self._update_daily_pnl(total_pnl)
                with self._lock:
                    if entry in self.active:
                        self.active.remove(entry)
                continue

            # ── TP_TRIGGER : Vérification pending uniquement ──
            if not entry.get("_be_activated") and not active_tickets:
                self._check_pending_only_expiry(entry, symbol, action)
                if not entry.get("orders"):
                    with self._lock:
                        if entry in self.active:
                            self.active.remove(entry)
                    continue

            # ── GESTION DU BE (si TP_FIXED_ENABLED) ──
            if TP_FIXED_ENABLED and not entry.get("_be_activated"):
                if self._check_pnl_trigger(entry):
                    self._apply_be_on_open_positions(entry, action)
                    continue

            # ── VÉRIFICATION DE L'OBJECTIF (si BE activé) ──
            if entry.get("_be_activated"):
                target_gain = entry.get("_target_gain", 0)
                if target_gain > 0:
                    total_pnl    = 0.0
                    active_tickets = []
                    for t in entry.get("tickets", []):
                        pos = self._get_pos(t["ticket"])
                        if pos:
                            total_pnl += pos.profit
                            active_tickets.append(t)
                    if total_pnl >= target_gain:
                        log.info(f"🎯 OBJECTIF ATTEINT : {total_pnl:.2f}$ (>= {target_gain:.2f}$)")
                        for t in active_tickets:
                            if not t.get("_tp_fixed_closed"):
                                self.bridge.close_position(t["ticket"], "TP-FIXED")
                                t["_tp_fixed_closed"] = True
                                log.info(f"  ✓ Fermeture #{t['ticket']}")
                        send_alert_sync(
                            f"🎯 GAIN VERROUILLÉ {action} {symbol}\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"P&L total: +{total_pnl:.2f}$\n"
                            f"Objectif: {target_gain:.2f}$\n"
                            f"Positions: {len(active_tickets)}\n"
                            f"Canal: {canal}"
                        )
                        continue

    # ★★★ BUG #8 : _resolve_order() avec cache et fenêtre réduite ★★★
    def _resolve_order(self, order_ticket: int, symbol: str):
        now = datetime.now(timezone.utc)

        if order_ticket in self._order_cache:
            cache_time = self._cache_timestamps.get(order_ticket, now - timedelta(hours=1))
            if (now - cache_time).total_seconds() < self._cache_ttl:
                cached = self._order_cache[order_ticket]
                if cached is None:
                    return None
                pos = mt5.positions_get(ticket=cached)
                if pos:
                    return pos[0]
                else:
                    del self._order_cache[order_ticket]
                    del self._cache_timestamps[order_ticket]
                    return None

        since = now - timedelta(days=1)
        deals = mt5.history_deals_get(symbol=symbol, from_time=since)
        if deals is None or len(deals) == 0:
            self._order_cache[order_ticket]      = None
            self._cache_timestamps[order_ticket] = now
            return None

        for deal in reversed(deals):
            if deal.order == order_ticket and deal.entry == mt5.DEAL_ENTRY_IN:
                positions = mt5.positions_get(ticket=deal.position_id)
                if positions:
                    pos = positions[0]
                    self._order_cache[order_ticket]      = pos.ticket
                    self._cache_timestamps[order_ticket] = now
                    return pos

        self._order_cache[order_ticket]      = None
        self._cache_timestamps[order_ticket] = now
        return None


# =============================================================
# CONFLIT & EXÉCUTION
# =============================================================
def check_conflict(signal: dict, bridge: MT5Bridge, manager) -> bool:
    if DEMO_MODE:
        return False
    symbol     = signal["symbol"]
    new_action = signal["action"]
    opposite   = "SELL" if new_action == "BUY" else "BUY"
    conflict   = False

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


def execute_signal(signal: dict, bridge: MT5Bridge, manager, tracker):
    action    = signal["action"]
    symbol    = signal["symbol"]
    zone_low  = signal["zone_low"]
    zone_mid  = signal["zone_mid"]
    zone_high = signal["zone_high"]

    all_tps = signal["tps"]
    if not all_tps:
        log.warning(f"Signal ignoré — aucun TP trouvé ({symbol} {action})")
        return

    all_tps = sorted(all_tps, reverse=(action == "SELL"))

    if len(all_tps) == 1:
        tp_trigger_idx = 0
    elif len(all_tps) < 3:
        tp_trigger_idx = len(all_tps) - 1
    else:
        tp_trigger_idx = 2

    tp_final = all_tps[-1]
    tp3      = all_tps[tp_trigger_idx]
    sl       = signal["sl"]
    expiry   = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MIN)

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
        spread_pips = abs(tick.ask - tick.bid) / sym_info.point
        if spread_pips > MAX_SPREAD_POINTS:
            log.warning(
                f"Signal ignoré — spread trop large: {spread_pips:.0f} pts "
                f"(max={MAX_SPREAD_POINTS}) | {sym_info.name}"
            )
            return

    if len(manager.active) >= MAX_POSITIONS:
        log.warning(
            f"Signal ignoré — max signaux atteint ({len(manager.active)}/{MAX_POSITIONS}) "
            f"| {symbol} {action}"
        )
        return

    in_zone          = zone_low <= current <= zone_high
    between_zone_tp1 = False

    canal    = signal.get("source_channel", "Inconnu")
    mode     = "DEMO" if DEMO_MODE else "LIVE"
    ch_num   = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), "?"))
    cas_num  = 1 if in_zone else 2
    mt5_comment = f"CH{ch_num}-C{cas_num}"

    log.info("=" * 55)
    log.info(f"SIGNAL [{mode}] {action} {symbol} | Canal: {canal} ({mt5_comment})")
    log.info(f"Zone [{zone_low} — {zone_mid} — {zone_high}] | Prix={current}")
    log.info(f"{'DANS la zone → CAS 1' if in_zone else 'HORS zone → CAS 2'}")
    log.info(f"TPs={all_tps} ({len(all_tps)}) | SL={sl}")
    log.info("=" * 55)

    orders, tickets = [], []
    is_single_price = signal.get("is_single_price", False)

    # ── Prix unique ──
    if is_single_price and len(all_tps) >= 1:
        entry_price = zone_mid
        tp1         = all_tps[0]
        sl_price    = sl

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
        log.info(f"PRIX UNIQUE — Scénario {scenario} | entry={entry_price} TP1={tp1} prix={current}")
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
                    "be_active": False, "be_sl": 0,
                })
                log.info(f"  ✓ MARKET #{t} @{current} TP={tp_final}")
                send_alert_sync(
                    f"🟢 {action} {symbol} | {mt5_comment_pu}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"MARKET: @{current} | Lot: {unique_lot}\n"
                    f"TP: {tp_final} | SL: {sl}\n"
                    f"Canal: {canal}"
                )
            else:
                log.error("  ✗ MARKET échoué")

        elif scenario == 2:
            log.info(f"  → LIMIT {action} @{entry_price} lot={unique_lot} TP={tp_final} SL={sl}")
            o = bridge.place_limit_order(
                signal, unique_lot, entry_price, tp_final, expiry, comment=mt5_comment_pu
            )
            if o:
                orders.append({
                    "order": o, "lot": unique_lot, "price": entry_price, "role": "limit_single",
                    "tp_index": tp_trigger_idx, "tp_target": tp3, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.info(f"  ✓ LIMIT #{o} @{entry_price} TP={tp_final}")
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
            "signal": signal, "orders": orders, "tickets": tickets, "expiry": expiry,
            "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "_signal_id": f"{symbol}_{action}_{int(time.time())}",
            "_expected_positions": 1,
        }
        manager.register(entry)
        tracker.log_trade_open(entry)
        return

    # ── Signal avec zone ──
    if in_zone:
        vol_min    = sym_info.volume_min
        lot_market = max(round(LOT_SIZE * 0.5, 2), vol_min)
        lot_limit  = max(round(LOT_SIZE * 0.5, 2), vol_min)
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
                "be_active": False, "be_sl": 0,
            })
            log.info(f"  ✓ MARKET #{t} @{market_entry_price} TP={tp_final}")
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
            log.info(f"  ✓ LIMIT #{o} @{limit_price} TP={tp_final}")
        else:
            log.error(f"  ✗ LIMIT échoué @{limit_price}")

        market_str = f"MARKET: @{market_entry_price} | Lot: {lot_market}" if t else "MARKET: ÉCHOUÉ"
        limit_str  = f"LIMIT : @{limit_price} | Lot: {lot_limit}" if o else "LIMIT : ÉCHOUÉ"
        send_alert_sync(
            f"🟢 {action} {symbol} | {mt5_comment}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{market_str}\n{limit_str}\n"
            f"TP: {tp_final} | SL: {sl}\n"
            f"Canal: {canal}"
        )

    else:
        tp1 = all_tps[0]
        tp2 = all_tps[1] if len(all_tps) >= 2 else None

        if tp2 is not None:
            if action == "BUY"  and current > tp2:
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
            other_limit   = zone_low if action == "BUY" else zone_high
            log.info(
                f"CAS 2-a → Prix entre zone et TP1 ({zone_low}-{zone_high} ↔ {tp1}) | prix={current}"
            )
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
                    "be_active": False, "be_sl": 0,
                })
                log.info(f"  ✓ MARKET #{t} @{current} TP={tp_final}")
            else:
                log.error("  ✗ MARKET échoué")

            log.info(f"  → LIMIT {action} @{other_limit} lot={lot_per_order} TP={tp_final} SL={sl}")
            o = bridge.place_limit_order(
                signal, lot_per_order, other_limit, tp_final, expiry, comment=mt5_comment
            )
            if o:
                orders.append({
                    "order": o, "lot": lot_per_order, "price": other_limit, "role": "limit_cas2",
                    "tp_index": tp_trigger_idx, "tp_target": tp3, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.info(f"  ✓ LIMIT #{o} @{other_limit} TP={tp_final}")
            else:
                log.error(f"  ✗ LIMIT échoué @{other_limit}")

            market_str = f"MARKET: @{current} | Lot: {lot_per_order}" if t else "MARKET: ÉCHOUÉ"
            limit_str  = f"LIMIT : @{other_limit} | Lot: {lot_per_order}" if o else "LIMIT : ÉCHOUÉ"
            send_alert_sync(
                f"🟢 {action} {symbol} | {mt5_comment}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{market_str}\n{limit_str}\n"
                f"TP: {tp_final} | SL: {sl}\n"
                f"Canal: {canal}"
            )

        else:
            lot_per_order = max(round(LOT_SIZE / 2, 2), sym_info.volume_min)
            if action == "BUY":
                price_1, price_2 = zone_high, zone_low
            else:
                price_1, price_2 = zone_low, zone_high

            log.info("CAS 2-b → prix loin de la zone (mais <= TP2) → 2 × LIMIT")
            log.info(f"  → LIMIT_1 {action} @{price_1} lot={lot_per_order} TP={tp_final} SL={sl}")

            o1 = bridge.place_limit_order(
                signal, lot_per_order, price_1, tp_final, expiry, comment=mt5_comment
            )
            if o1:
                orders.append({
                    "order": o1, "lot": lot_per_order, "price": price_1, "role": "limit_1",
                    "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.info(f"  ✓ LIMIT_1 #{o1} @{price_1} TP={tp_final}")
            else:
                log.error(f"  ✗ LIMIT_1 échoué @{price_1}")

            log.info(f"  → LIMIT_2 {action} @{price_2} lot={lot_per_order} TP={tp_final} SL={sl}")
            o2 = bridge.place_limit_order(
                signal, lot_per_order, price_2, tp_final, expiry, comment=mt5_comment
            )
            if o2:
                orders.append({
                    "order": o2, "lot": lot_per_order, "price": price_2, "role": "limit_2",
                    "tp_index": len(all_tps) - 1, "tp_target": tp_final, "tp3": tp3,
                    "tp_final": tp_final, "sl_step": 0, "trail_active": False,
                })
                log.info(f"  ✓ LIMIT_2 #{o2} @{price_2} TP={tp_final}")
            else:
                log.error(f"  ✗ LIMIT_2 échoué @{price_2}")

            l1_str = f"LIMIT_1: @{price_1} | Lot: {lot_per_order}" if o1 else "LIMIT_1: ÉCHOUÉ"
            l2_str = f"LIMIT_2: @{price_2} | Lot: {lot_per_order}" if o2 else "LIMIT_2: ÉCHOUÉ"
            send_alert_sync(
                f"🔵 {action} {symbol} | {mt5_comment}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{l1_str}\n{l2_str}\n"
                f"TP: {tp_final} | SL: {sl}\n"
                f"Canal: {canal}"
            )

    if not orders and not tickets:
        log.error("Aucun ordre placé.")
        return

    entry = {
        "signal":  signal,
        "orders":  orders,
        "tickets": tickets,
        "expiry":  expiry,
        "_open_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "_signal_id": f"{symbol}_{action}_{int(time.time())}",
        "_expected_positions": 2 if (in_zone or between_zone_tp1 or len(orders) >= 2) else 1,
    }
    manager.register(entry)
    tracker.log_trade_open(entry)


# =============================================================
# QUICK ALERT
# =============================================================
def _qa_key(symbol: str, action: str, channel_name: str = "") -> str:
    clean_channel = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f\u00a0]', '', channel_name)
    ch_num = CHANNEL_NUM_MAP.get(
        clean_channel, CHANNEL_NUM_MAP.get(clean_channel.lstrip("-"), "?")
    )
    return f"CH{ch_num}_{symbol}_{action}"


def execute_quick_alert(
    signal: dict, bridge: MT5Bridge, manager: TradeManager,
    tracker: PerformanceTracker, quick_alerts: dict
):
    action      = signal["action"]
    symbol      = signal["symbol"]
    sl          = signal["sl"]
    entry_price = signal["zone_mid"]

    if len(manager.active) >= MAX_POSITIONS:
        log.warning(
            f"Quick Alert ignorée — max signaux atteint ({len(manager.active)}/{MAX_POSITIONS}) "
            f"| {symbol} {action}"
        )
        return

    sym_info = bridge._sym(symbol)
    if not sym_info:
        log.error(f"Quick alert rejeté — symbole introuvable: {symbol}")
        return
    current = bridge.current_price(sym_info.name, action)
    if current is None:
        log.error(f"Quick alert rejeté — prix indisponible: {symbol}")
        return

    canal       = signal.get("source_channel", "Inconnu")
    clean_canal = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u206f\u00a0]', '', canal)
    ch_num      = CHANNEL_NUM_MAP.get(clean_canal, CHANNEL_NUM_MAP.get(clean_canal.lstrip("-"), "?"))
    expiry      = datetime.now(timezone.utc) + timedelta(minutes=ORDER_EXPIRY_MIN)

    # ★★★ BUG #6 : TP provisoire = entry ± QUICK_ALERT_SL_OFFSET ★★★
    if not signal.get("tps") or len(signal["tps"]) == 0:
        sl_offset  = float(os.getenv("QUICK_ALERT_SL_OFFSET", "10.0"))
        default_tp = round(entry_price + (sl_offset if action == "BUY" else -sl_offset), 2)
        log.info(f"TP provisoire Quick Alert : {default_tp} (RR=1:1, distance={sl_offset})")
    else:
        default_tp = 0

    key = _qa_key(symbol, action, canal)
    if key in quick_alerts and quick_alerts[key]:
        existing        = quick_alerts[key][0]
        existing_ticket = existing.get("ticket")
        log.info(f"QUICK ALERT déjà existante pour {key} → mise à jour du SL (provisoire → {sl})")
        if existing.get("is_limit", False):
            order = mt5.orders_get(ticket=existing_ticket)
            if order:
                bridge.modify_pending_order(existing_ticket, sl, default_tp, "[QA-UPDATE-SL-TP]")
                log.info(
                    f"  ✓ SL/TP de l'ordre pending #{existing_ticket} mis à jour "
                    f"→ SL={sl}, TP={default_tp}"
                )
                existing["signal"]["sl"] = sl
                return
        else:
            pos = mt5.positions_get(ticket=existing_ticket)
            if pos:
                bridge.modify_sl_tp(existing_ticket, sl, default_tp, "[QA-UPDATE-SL-TP]")
                log.info(
                    f"  ✓ SL/TP de la position #{existing_ticket} mis à jour "
                    f"→ SL={sl}, TP={default_tp}"
                )
                existing["signal"]["sl"] = sl
                return
            else:
                log.warning(
                    f"QUICK ALERT existante mais ordre/position #{existing_ticket} introuvable "
                    f"→ nouvelle alerte"
                )

    in_zone = (entry_price <= current <= sl) if action == "SELL" else (sl <= current <= entry_price)

    orders, tickets        = [], []
    order_ticket           = None
    is_limit_order         = False

    if in_zone:
        log.info(
            f"QUICK ALERT MARKET {action} {symbol} @{current} "
            f"SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}"
        )
        try:
            t = bridge.place_market_order(signal, LOT_UNIQUE_TRADE, tp=default_tp, comment=f"CH{ch_num}-AL")
        except Exception as e:
            log.error(f"Quick alert MARKET exception: {e}")
            t = None
        if t:
            tickets.append({
                "ticket": t, "lot": LOT_UNIQUE_TRADE, "role": "quick_market",
                "entry_price": current, "tp_index": 0, "tp_target": default_tp,
                "tp3": default_tp, "tp_final": default_tp, "sl_step": 0,
                "trail_active": False, "be_active": False, "be_sl": 0,
            })
            order_ticket = t
            log.info(f"  ✓ QUICK MARKET #{t} @{current} SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}")
        else:
            log.error("  ✗ QUICK MARKET échoué")
            return
    else:
        log.info(
            f"QUICK ALERT LIMIT {action} {symbol} @{entry_price} "
            f"SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}"
        )
        o = bridge.place_limit_order(
            signal, LOT_UNIQUE_TRADE, entry_price, default_tp, expiry, comment=f"CH{ch_num}-AL"
        )
        if o:
            orders.append({
                "order": o, "lot": LOT_UNIQUE_TRADE, "price": entry_price,
                "role": "quick_limit", "tp_index": 0, "tp_target": default_tp,
                "tp3": default_tp, "tp_final": default_tp, "sl_step": 0, "trail_active": False,
            })
            order_ticket   = o
            is_limit_order = True
            log.info(f"  ✓ QUICK LIMIT #{o} @{entry_price} SL={sl}, TP={default_tp}, lot={LOT_UNIQUE_TRADE}")
        else:
            log.error("  ✗ QUICK LIMIT échoué")
            return

    entry = {
        "signal": signal, "orders": orders, "tickets": tickets, "expiry": expiry,
        "_open_date":        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "_is_quick_alert":   True,
        "_signal_id":        f"{symbol}_{action}_{int(time.time())}_QA",
        "_expected_positions": 1,
    }
    manager.register(entry)

    if key not in quick_alerts:
        quick_alerts[key] = []
    quick_alerts[key].append({
        "entry":        entry,
        "signal":       signal,
        "ticket":       order_ticket,
        "is_limit":     is_limit_order,
        "entry_price":  entry_price,
        "time":         datetime.now(timezone.utc),
    })
    log.info(f"QUICK ALERT enregistré: {key} avec TP={default_tp}, lot={LOT_UNIQUE_TRADE}")


def merge_quick_alert(
    qa: dict, key: str, full_signal: dict, bridge: MT5Bridge,
    manager: TradeManager, tracker: PerformanceTracker, quick_alerts: dict
):
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
        log.info(f"MERGE Scénario 1: Position #{qa_ticket} ouverte → SL/TP + LIMIT")
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
        resolved_pos = manager._resolve_order(qa_ticket, full_signal["symbol"])
        if resolved_pos:
            log.info(f"MERGE Scénario 1: LIMIT #{qa_ticket} rempli → SL/TP + LIMIT")
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
            log.info(f"MERGE Scénario 2: LIMIT #{qa_ticket} pending → modif SL/TP + LIMIT")
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
            log.info(
                f"[GRADE] Prix stockés pour quick alert : "
                f"MARKET={market_entry_price}, LIMIT={entry['_grade_limit_price']}"
            )

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
    log.info(f"MERGE LIMIT {action} @{limit_price} lot={LOT_UNIQUE_TRADE} TP={tp_final} SL={real_sl}")
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
        log.info(f"  ✓ MERGE LIMIT #{o} @{limit_price} lot={LOT_UNIQUE_TRADE}")
    else:
        log.error(f"  ✗ MERGE LIMIT échoué @{limit_price}")


# =============================================================
# MAIN
# =============================================================
async def main():
    global _main_loop, _alert_client
    _main_loop = asyncio.get_running_loop()

    parser  = SignalParser()
    bridge  = MT5Bridge()
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
    entity_to_name = {}

    for env_name, ch_value in channel_names:
        if not ch_value:
            continue
        try:
            ch_resolved = int(ch_value) if ch_value.lstrip("-").isdigit() else ch_value
            entity      = await client.get_entity(ch_resolved)
            title       = getattr(entity, "title", ch_value)
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

        log.info(f"[{canal_name}] {text[:150].replace(chr(10), ' | ')}")

        signal_data = parser.parse(text)
        if signal_data is None:
            log.warning(f"[PARSING ECHOUÉ] Message ignoré : {text[:200].replace(chr(10), ' ')}")
            return

        # ★★★ BUG #1 : utilisation de l'attribut déclaré ★★★
        signal_data.source_channel = canal_name

        if signal_data.signal_type == "CLOSE":
            canal  = canal_name
            ch_num = CHANNEL_NUM_MAP.get(canal, CHANNEL_NUM_MAP.get(canal.lstrip("-"), None))
            bridge.close_all(symbol=signal_data.close_symbol, channel_num=ch_num)
            return

        elif signal_data.signal_type == "SL_MOVE":
            log.info(f"SL MOVE reçu → nouveau SL={signal_data.new_sl}")
            ch_num = CHANNEL_NUM_MAP.get(canal_name, CHANNEL_NUM_MAP.get(canal_name.lstrip("-"), None))
            if ch_num is not None:
                bridge.update_sl_by_channel(signal_data.new_sl, ch_num)
            else:
                log.warning(f"SL MOVE ignoré : canal inconnu ({canal_name})")
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
                log.info(
                    f"[{canal_name}] Signal ignoré - "
                    f"Limite de P&L quotidien atteinte ({DAILY_PROFIT_LIMIT}$)"
                )
                return

            sig_dict = signal_data.to_dict()

            # ============================================================
            # ★★★ VALIDATION TIMESFM ★★★
            # Appliquée uniquement aux signaux TRADE (pas aux quick alerts)
            # ============================================================
            if TIMESFM_ENABLED and not signal_data.is_quick_alert:
                tfm_result = timesfm_validator.validate(sig_dict["action"])
                if not tfm_result["valid"]:
                    log.info(
                        f"[TIMESFM] 🚫 Signal {sig_dict['action']} {sig_dict['symbol']} REJETÉ "
                        f"— Prédit={tfm_result['predicted_direction']} "
                        f"Move={tfm_result['predicted_move_pips']}pips "
                        f"Conf={tfm_result['confidence']} "
                        f"({tfm_result['reason']})"
                    )
                    send_alert_sync(
                        f"🚫 SIGNAL REJETÉ PAR TIMESFM\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"{sig_dict['action']} {sig_dict['symbol']}\n"
                        f"Prédit: {tfm_result['predicted_direction']} "
                        f"({tfm_result['predicted_move_pips']} pips)\n"
                        f"Confiance: {tfm_result['confidence']}\n"
                        f"Raison: {tfm_result['reason']}\n"
                        f"Canal: {canal_name}"
                    )
                    return
                else:
                    log.info(
                        f"[TIMESFM] ✅ Signal {sig_dict['action']} validé — "
                        f"Move prédit={tfm_result['predicted_move_pips']}pips "
                        f"Conf={tfm_result['confidence']}"
                    )
            # ============================================================

            if signal_data.is_quick_alert:
                execute_quick_alert(sig_dict, bridge, manager, tracker, _quick_alerts)
                return

            key     = _qa_key(sig_dict["symbol"], sig_dict["action"], canal_name)
            qa_list = _quick_alerts.get(key, [])
            found_qa  = None
            found_idx = -1
            zone_low  = sig_dict["zone_low"]
            zone_high = sig_dict["zone_high"]

            for idx, qa in enumerate(qa_list):
                qa_price = qa["entry_price"]
                if zone_low - 2 <= qa_price <= zone_high + 2:
                    found_qa  = qa
                    found_idx = idx
                    break

            if found_qa is not None:
                merge_quick_alert(found_qa, key, sig_dict, bridge, manager, tracker, _quick_alerts)
            else:
                execute_signal(sig_dict, bridge, manager, tracker)

    # Banner
    mode = "🧪 DEMO" if DEMO_MODE else "💰 LIVE"
    log.info("=" * 55)
    log.info(" TRADINGBOT V4.9.0 — TIMESFM INTÉGRÉ")
    log.info(f" Mode: {mode}")
    log.info(f" Canaux surveillés : {len(chats)}")
    for env_name, ch_value in channel_names:
        if ch_value:
            log.info(f"  {env_name} : {ch_value}")
    log.info(f" Lot total : {LOT_SIZE} | Lot unique : {LOT_UNIQUE_TRADE}")
    log.info(f" Gain fixe par position : {TP_FIXED_GAIN_USD}$")
    log.info(f" BE déclenché à : {PNL_TRIGGER_USD}$")
    log.info(f" Objectif quotidien : {DAILY_PROFIT_LIMIT}$")
    log.info(f" Filtre horaire : {'ON' if TIME_FILTER_ENABLED else 'OFF'} ({TRADING_START_HOUR}h-{TRADING_END_HOUR}h UTC)")
    log.info(f" Max signaux actifs : {MAX_POSITIONS}")
    log.info(f" TimesFM : {'✅ ACTIVÉ' if TIMESFM_ENABLED else '⛔ DÉSACTIVÉ'}")
    if TIMESFM_ENABLED:
        log.info(f"   Timeframe : {TIMESFM_TIMEFRAME} | Contexte : {TIMESFM_CONTEXT_BARS} bars")
        log.info(f"   Horizon : {TIMESFM_HORIZON} bougies")
        log.info(f"   Seuil move : {TIMESFM_MIN_MOVE_PIPS} pips | Confiance min : {TIMESFM_MIN_CONFIDENCE}")
        log.info(f"   Symbole MT5 : {TIMESFM_SYMBOL}")
    log.info("=" * 55)

    try:
        await client.run_until_disconnected()
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
