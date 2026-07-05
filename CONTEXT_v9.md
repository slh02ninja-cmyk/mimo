# CHANGELOG — Bot Trading v9.0.0

## Version : 9.0.0
**Date :** 2026-07-05
**Auteur :** SaLaH + MIMO

---

## 🔴 Bugs corrigés (5)

### 1. Race condition dans `_cancel_pending_orders_for_entry`
**Problème :** Le BE annule les pending orders, mais un limit peut se remplir entre le `mt5.orders_get()` et le `bridge.cancel_order()`. Le fill n'est détecté qu'au cycle suivant → le limit reste sans protection BE pendant 1 seconde.
**Fix :** Vérifier le retour de `cancel_order` → si False, résoudre immédiatement la position et l'ajouter aux tickets avec `be_active = False`.

### 2. BE LATE — Limit rempli après BE initial jamais protégé
**Problème :** Quand `_be_activated = True`, le bloc BE initial ne se redéclenche plus. Si un limit se remplit après (via race condition ou timing MT5), il reste avec `be_active = False` pour toujours → position sans protection BE.
**Fix :** Nouveau bloc dans `_check_all()` après le BE initial → détecte les tickets `be_active = False`, recalcule le médian des entrées, applique le SL sur le nouveau ticket.

### 3. TP_TRIGGER ne nettoie pas `self.active`
**Problème :** Après annulation de tous les pending orders par TP_TRIGGER, l'entry reste dans `self.active` (entry fantôme) pendant 1 cycle. Le compteur `total_signals` compte cette entry → un vrai signal pourrait être rejeté par `MAX_POSITIONS`.
**Fix :** Suppression immédiate de `self.active` si aucun ticket ni order restant après TP_TRIGGER.

### 4. SL_MOVE ignore les ordres pending
**Problème :** Le signal "SL MOVE" modifie le SL des positions ouvertes via `update_sl_by_channel()`, mais les ordres pending gardent l'ancien SL. Si le limit se remplit plus tard, il entre avec un SL trop large.
**Fix :** Nouvelle méthode `update_pending_orders_sl()` dans TradeManager. Modifie le SL dans le signal dict + appelle `modify_pending_order()` sur chaque ordre pending du canal.

### 5. Alerte BE LATE sans info sur le changement de target_gain
**Problème :** Quand le limit remplit après BE, le target_gain passe de `TP_FIXED_GAIN_USD × 1` à `TP_FIXED_GAIN_USD × 2` sans notification. Le trader ne sait pas que l'objectif a changé.
**Fix :** L'alerte Telegram BE LATE inclut maintenant l'ancien et le nouveau objectif de gain.

---

## 📁 Fichiers modifiés

| Fichier | Modifications |
|---|---|
| `telegram_listener_v9.py` | 5 fixes appliqués (nouveau fichier basé sur v8) |

---

## 📋 Détail des modifications

### `_cancel_pending_orders_for_entry()` — Fix #1
```python
# AVANT : cancel_order ignorait le retour
for ticket in orders_to_cancel:
    self.bridge.cancel_order(ticket)

# APRÈS : si cancel échoué → résoudre la position remplie
for ticket in orders_to_cancel:
    ok = self.bridge.cancel_order(ticket)
    if not ok:
        pos = self._resolve_order(ticket, symbol)
        if pos:
            # Ajouter le ticket avec be_active = False
            entry["tickets"].append(tk)
```

### `_check_all()` — Fix #2 + #5
```python
# NOUVEAU BLOC après le BE initial
if entry.get("_be_activated"):
    unprotected = [t for t in entry["tickets"] if not t.get("be_active")]
    if unprotected:
        # Recalculer le médian avec la nouvelle position
        # Appliquer le SL + alerter avec ancien/nouveau target_gain
```

### `_check_pending_only_expiry()` — Fix #3
```python
# APRÈS l'alerte TP_TRIGGER :
if not has_open_position:
    remaining = [t for t in entry["tickets"] if self._get_pos(t["ticket"])]
    if not remaining and not entry.get("orders"):
        self.active.remove(entry)
```

### `update_pending_orders_sl()` — Fix #4 (nouvelle méthode)
```python
def update_pending_orders_sl(self, channel_num, new_sl):
    # Met à jour signal["sl"] + modify_pending_order sur chaque ordre
```

### Handler `main()` — Fix #4 (appel)
```python
# SL_MOVE handler :
bridge.update_sl_by_channel(new_sl, ch_num)
manager.update_pending_orders_sl(ch_num, new_sl)  # ← ajouté
```

---

## 🔗 Commits

| Hash | Description |
|---|---|
| — | fix: race condition _cancel_pending_orders_for_entry |
| — | fix: BE LATE protection des limits remplis après BE |
| — | fix: TP_TRIGGER nettoyage immédiat self.active |
| — | fix: SL_MOVE mise à jour pending orders |
| — | fix: alerte BE LATE avec target_gain info |
