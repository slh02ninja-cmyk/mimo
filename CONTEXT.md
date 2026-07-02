# CHANGELOG — Bot Trading v8.2.5

## Version : 8.2.5
**Date :** 2026-07-02
**Auteur :** SaLaH + MIMO

---

## 🔴 Bugs critiques corrigés

### 1. BE — `be_price` potentiellement non définie
**Fichier :** `telegram_listener_v8.py`
**Problème :** Dans `_apply_be_on_open_positions`, cas `open_count == 1`, si `pos` est None, `be_price` n'était jamais assigné → `UnboundLocalError`.
**Correction :** `be_price = entry_price` initialisé avant le bloc `if pos:`.

### 2. BE — `_apply_be_on_open_positions` ne modifiait pas le SL correctement
**Fichier :** `telegram_listener_v8.py`
**Problème :** La fonction utilisait `modify_sl` seul, sans logique de gain cible.
**Correction :**
- SL modifié via `modify_sl` (TP reste le TP final du signal, jamais modifié)
- `target_gain = TP_FIXED_GAIN_USD × N` (N = nombre de positions ouvertes après BE)
- Bot ferme manuellement les positions quand `total_pnl ≥ target_gain`

### 3. BE — Whitelist incomplète
**Fichier :** `telegram_listener_v8.py`
**Problème :** Les rôles `limit_2`, `limit_cas1`, `limit_cas2`, `merge_limit` n'étaient pas dans `_be_allowed_roles`.
**Correction :** Ajout de tous les rôles à la whitelist :
```python
"market_single", "limit_single",
"market_cas1", "market_cas2",
"limit_1", "limit_2",
"limit_cas1", "limit_cas2",
"quick_market", "quick_limit", "quick_limit_filled",
"merge_limit"
```

### 4. TP_TRIGGER — Ne fonctionnait pas avec position ouverte
**Fichier :** `telegram_listener_v8.py`
**Problème :** `_check_pending_only_expiry` faisait un `return` si une position était déjà ouverte → les ordres pending restants (ex: limit_2 dans CAS 2-b) n'étaient jamais annulés.
**Correction :** Le TP_TRIGGER annule les pending restants même si une position est déjà ouverte.

### 5. TP_TRIGGER — Display bug (compte et prix)
**Fichier :** `telegram_listener_v8.py`
**Problème :** Le log affichait `Ordres annulés: 0` et `Prix: inconnu` car les valeurs étaient capturées APRÈS `_cancel_pending_orders_for_entry` (qui vide la liste).
**Correction :** Compte et prix capturés AVANT l'annulation.

### 6. Fusion QA — `merge_quick_alert` et `_place_merge_limit` vides
**Fichier :** `telegram_listener_v8.py`
**Problème :** Les deux fonctions étaient des stubs (`pass`), jamais implémentées depuis v7.
**Correction :** Implémentation complète depuis `telegram_listener_v7.py`.

### 7. Entry non retirée après TP_FIXED
**Fichier :** `telegram_listener_v8.py`
**Problème :** Après TP_FIXED ferme toutes les positions, l'entry restait dans `self.active` jusqu'au prochain cycle. Pendant ce cycle, le code re-entrait dans le bloc `_be_activated` avec `total_pnl = 0`.
**Correction :** Retrait immédiat de `self.active` après TP_FIXED.

### 8. CAS 2-b — Condition par élimination fragile
**Fichier :** `telegram_listener_v8.py`
**Problème :** La condition CAS 2-b utilisait une logique par élimination (vérifier TP2 → CAS 2-a → else CAS 2-b). Peu lisible et sujette aux erreurs.
**Correction :** Vérification explicite :
- CAS 2-a : `tp1 < current < zone_low` (SELL) / `zone_high < current < tp1` (BUY)
- CAS 2-b : `tp2 < current < tp1` (SELL) / `tp1 < current < tp2` (BUY)
- Else : prix hors zone → ANNULÉ

---

## 🟡 Bugs majeurs corrigés

### 7. Heartbeat — Messages "BOT ACTIF" toutes les 10 min
**Fichier :** `telegram_listener_v8.py`
**Problème :** Heartbeat envoyait un message Telegram toutes les 10 min, causant des erreurs de timeout.
**Correction :** Désactivation complète du heartbeat (`return` immédiat).

### 8. Alertes Telegram — Timeout trop court
**Fichier :** `telegram_listener_v8.py`
**Problème :** `send_alert_sync` avait un timeout de 5s, insuffisant pour Telegram.
**Correction :**
- Timeout : 5s → 15s
- Gestion explicite de `TimeoutError`
- Message d'erreur : `type: message` (pas vide)

### 9. Logs — Message brut Telegram affiché en INFO
**Fichier :** `telegram_listener_v8.py`
**Problème :** Le message Telegram brut (avec `**`, emojis) était loggé en INFO.
**Correction :**
- Message brut → DEBUG seulement
- Signal parsé → INFO au format standard

### 10. Logs — Format `LMT` au lieu de `LIMIT`
**Fichier :** `telegram_listener_v8.py`
**Problème :** Les logs d'exécution prix unique utilisaient `LMT` au lieu de `LIMIT`.
**Correction :** `LMT` → `LIMIT` dans tous les logs.

---

## 🟢 Améliorations

### 11. Logs — Formats standardisés (max 3 lignes)
**Fichier :** `telegram_listener_v8.py`
**17 formats de log standardisés :**

| # | Événement | Format |
|---|---|---|
| 1 | Signal reçu — Prix Unique | `===== \| CH{num}-PU-S{1\|2} \| =====` + `{action} {symbol} \| Entrée: {entry} \| TPf: {tp} SL: {sl}` |
| 2 | Signal reçu — Zone | `===== \| CH{num}-C{1\|2} \| =====` + `{action} {symbol} \| Zone: {low}-{high} \| TPf: {tp} SL: {sl}` |
| 3 | Signal reçu — QA | `===== \| CH{num}-QA \| =====` + `{action} {symbol} \| Entrée: {entry} \| TPf: {tp} SL: {sl}` |
| 4 | Exécution PU S1 (market) | `===== \| CH{num}-PU-S1 \| =====` + `MKT #{ticket} @{price} lot{lot}` |
| 5 | Exécution PU S2 (limit) | `===== \| CH{num}-PU-S2 \| =====` + `LIMIT #{ticket} @{price} lot{lot}` |
| 6 | Exécution CAS 1 | `===== \| CH{num}-C1 \| =====` + `MKT #{t} \| LIMIT_1 #{o}` |
| 7 | Exécution CAS 2-a | `===== \| CH{num}-C2 \| =====` + `MKT #{t} \| LIMIT_2 #{o}` |
| 8 | Exécution CAS 2-b | `===== \| CH{num}-C2 \| =====` + `LIMIT_1 #{o1} \| LIMIT_2 #{o2}` |
| 9 | QA Market | `===== \| CH{num}-QA \| =====` + `MKT #{t} @{price} lot{lot}` |
| 10 | QA Limit | `===== \| CH{num}-QA \| =====` + `LIMIT #{o} @{price} lot{lot}` |
| 11 | Limit remplie | `===== \| {comment} \| LIMIT \| =====` + `#{ticket} @{price} lot{lot}` |
| 12 | BE activé | `===== \| {comment} \| BE \| =====` + `SL @{price} \| N POS` |
| 13 | TP-FIXED | `===== \| {comment} \| TP-FIXED \| =====` + `P&L: {pnl}$ \| N POS` + tickets |
| 14 | TP / SL / CLOSE | `===== \| {comment} \| {label} \| =====` + `P&L: {pnl}$ \| idx/total #{ticket}` |
| 15 | EXPIRATION | `===== \| {comment} \| EXPIRATION \| =====` + `@{prices} \| N ordres annulés` |
| 16 | TP_TRIGGER | `===== \| {comment} \| TP_TRIGGER \| =====` + `@{prices} \| N ordres annulés` |
| 17 | DAILY-LIMIT | `===== \| DAILY-LIMIT \| =====` + `P&L: {pnl}$ \| N positions \| N ordres` |

### 12. Debug BE — Log quand le BE ne se déclenche pas
**Fichier :** `telegram_listener_v8.py`
**Ajout :** `[BE] PnL insuffisant : X.XX$ < 8.0$ (rôle=limit_1)` en mode debug.

### 13. Suffixes de log
| Suffixe | Signification |
|---|---|
| `PU-S1` | Prix Unique Scénario 1 (market) |
| `PU-S2` | Prix Unique Scénario 2 (limit) |
| `C1` | CAS 1 (zone, prix dans la zone) |
| `C2` | CAS 2 (zone, prix hors zone) |
| `QA` | Quick Alert seul |
| `QA-F` | Quick Alert + Fusion |
| `MG` | Merge (fusion QA → signal complet) |

---

## 📋 Rôles déclencheurs du BE

| Cas | Scénario | Rôle déclenche BE |
|---|---|---|
| CAS 1 | 1 pos | `market_cas1` |
| CAS 1 | 2 pos | `market_cas1` |
| CAS 2-a | 1 pos | `market_cas2` |
| CAS 2-a | 2 pos | `market_cas2` |
| CAS 2-b | 1 pos | `limit_1` |
| CAS 2-b | 2 pos | `limit_1` |
| Prix Unique | Scénario 1 (market) | `market_single` |
| Prix Unique | Scénario 2 (limit) | `limit_single` |
| Alert | 1 pos (market) | `quick_market` |
| Alert | 1 pos (limit) | `quick_limit_filled` |
| Alert + Fusion | 1 pos (market) | `quick_market` |
| Alert + Fusion | 1 pos (limit) | `quick_limit_filled` |
| Alert + Fusion | 2 pos (alert market) | `quick_market` |
| Alert + Fusion | 2 pos (alert limit) | `quick_limit_filled` |

---

## ⚙️ Fonctionnement BE + TP_FIXED

### Déclenchement du BE
1. Quand le P&L d'une position atteint `PNL_TRIGGER_USD` → BE activé
2. Annuler les ordres pending non remplis
3. Compter les positions ouvertes (N)
4. Si N = 1 : SL @ entry_price
5. Si N = 2 : SL au médian des deux entrées
6. TP reste le TP final du signal (jamais modifié)

### Fermeture manuelle (TP_FIXED)
1. `target_gain = TP_FIXED_GAIN_USD × N`
2. Le bot vérifie à chaque poll (1s) : `total_pnl ≥ target_gain`
3. Si oui → ferme manuellement toutes les positions
4. Si non → le trade continue, le broker TP peut fermer en premier

---

## 🔍 Conditions CAS 2 (zone)

### CAS 2-a (MARKET + LIMIT)
Prix entre TP1 et zone :
```python
# SELL
cas2a = tp1 < current < zone_low
# BUY
cas2a = zone_high < current < tp1
```

### CAS 2-b (2 × LIMIT)
Prix entre TP1 et TP2 :
```python
# SELL
cas2b = tp2 < current < tp1
# BUY
cas2b = tp1 < current < tp2
```

### Else
Prix hors zone → signal ANNULÉ.

---

## 🔍 Conditions QA-Limit

Fenêtre de 3 points autour de l'entrée :
```python
# SELL
in_limit_zone = entry_price - 3 <= current < entry_price
# BUY
in_limit_zone = entry_price < current <= entry_price + 3
```
Si le prix est hors de cette fenêtre → QA ignoré.

---

## 📁 Fichiers modifiés

| Fichier | Modifications |
|---|---|
| `telegram_listener_v8.py` | BE, logs, alertes, fusion QA, heartbeat |
| `.env` | Inchangé |
| `signal_parser_v8.py` | Inchangé |

---

## 🔗 Commits

| Hash | Description |
|---|---|
| `20a3be0` | CAS 2-b condition explicite (prix entre TP1 et TP2) |
| `8b63088` | Retrait immédiat entry après TP_FIXED |
| `3eb7ca7` | CONTEXT.md — changelog complet |
| `b302829` | Implémentation merge_quick_alert + _place_merge_limit |
| `bdfc602` | Formats de log standardisés |
| `ab663be` | Log signal au format standard |
| `70de1f9` | Log signal parsé (pas brut) |
| `6c484d8` | Nettoyage gras/emojis dans les logs |
| `30ebcf1` | Désactivation heartbeat |
| `eedf62f` | Alertes Telegram timeout 15s |
| `21700e0` | BE + TP_FIXED corrections |
