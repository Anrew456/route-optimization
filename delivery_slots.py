"""
Sistema di determinazione slot liberi e assegnazione rider per pizzeria da asporto.

Dato un nuovo ordine con coordinate e numero di pizze, determina quali slot di consegna
sono disponibili e, per ciascuno, quale fattorino assegnare per massimizzare l'efficienza.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Parametri di configurazione
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """Parametri configurabili per pizzeria."""

    num_fattorini: int = 3
    capacita_pizze: int = 8  # pizze per giro (P)
    t_max_minuti: float = 30.0  # tempo max dalla partenza all'ultima consegna
    tolleranza_anticipo_minuti: float = 5.0   # anticipo massimo rispetto allo slot
    tolleranza_ritardo_minuti: float = 10.0  # ritardo massimo rispetto allo slot
    fattore_detour: float = 1.3  # moltiplicatore distanza reale vs linea d'aria
    velocita_media_kmh: float = 25.0  # velocità media fattorino
    tempo_sosta_minuti: float = 3.0  # tempo per ogni consegna (parcheggio, citofono...)
    penalita_nuovo_giro: float = 1.5  # fattore penalità per preferire inserimenti

    @property
    def t_max(self) -> timedelta:
        return timedelta(minutes=self.t_max_minuti)

    @property
    def tolleranza_anticipo(self) -> timedelta:
        return timedelta(minutes=self.tolleranza_anticipo_minuti)

    @property
    def tolleranza_ritardo(self) -> timedelta:
        return timedelta(minutes=self.tolleranza_ritardo_minuti)

    @property
    def tempo_sosta(self) -> timedelta:
        return timedelta(minutes=self.tempo_sosta_minuti)


# ---------------------------------------------------------------------------
# Modelli dati
# ---------------------------------------------------------------------------


@dataclass
class Coordinate:
    lat: float
    lon: float


@dataclass
class Consegna:
    """Una singola consegna assegnata a uno slot."""

    id: str
    coordinate: Coordinate
    num_pizze: int
    slot: datetime  # orario di consegna promesso al cliente


@dataclass
class Giro:
    """
    Un giro = una singola uscita del fattorino dalla pizzeria.
    Contiene una sequenza ordinata di consegne.
    """

    fattorino_id: int
    consegne: list[Consegna] = field(default_factory=list)
    orario_partenza: Optional[datetime] = None
    tempo_totale: Optional[timedelta] = None  # partenza → ultima consegna (no ritorno)
    tempo_ritorno: Optional[timedelta] = None  # partenza → ritorno in pizzeria

    @property
    def pizze_totali(self) -> int:
        return sum(c.num_pizze for c in self.consegne)


@dataclass
class Fattorino:
    id: int
    giri: list[Giro] = field(default_factory=list)

    def giri_ordinati(self) -> list[Giro]:
        """Restituisce i giri ordinati per orario di partenza."""
        return sorted(self.giri, key=lambda g: g.orario_partenza or datetime.min)


@dataclass
class SlotDisponibile:
    """Risultato: uno slot disponibile con il fattorino ottimale assegnato."""

    slot: datetime
    fattorino_id: int
    costo: float  # costo effettivo (per ranking interno)
    tipo: str  # "inserimento" o "nuovo_giro"
    giro_risultante: Giro


# ---------------------------------------------------------------------------
# Utilità geografiche
# ---------------------------------------------------------------------------


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    """Distanza in linea d'aria tra due punti (km), formula di Haversine."""
    R = 6371.0  # raggio terrestre in km

    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(h))


def tempo_percorrenza(a: Coordinate, b: Coordinate, config: Config) -> timedelta:
    """Stima il tempo di percorrenza tra due punti."""
    distanza = haversine_km(a, b) * config.fattore_detour
    ore = distanza / config.velocita_media_kmh
    return timedelta(hours=ore)


# ---------------------------------------------------------------------------
# Calcolo tempi di un giro
# ---------------------------------------------------------------------------


def calcola_tempi_giro(
    giro: Giro,
    pizzeria: Coordinate,
    config: Config,
) -> Giro:
    """
    Calcola orario_partenza, tempo_totale e tempo_ritorno per un giro.

    L'orario di partenza è determinato dallo slot più vicino: il fattorino
    deve partire in tempo per arrivare alla prima consegna entro il suo slot.
    Poi si simula il percorso nell'ordine delle consegne.

    Strategia per l'orario di partenza:
    - Si simula il giro in avanti partendo da un orario provvisorio t=0
    - Si calcola per ogni consegna il "latest departure" compatibile con il suo slot
    - L'orario di partenza è il minimo di questi latest departure
    """
    if not giro.consegne:
        return giro

    # Fase 1: calcola i tempi cumulativi di arrivo a ogni tappa (partendo da t=0)
    tempi_arrivo_relativi: list[timedelta] = []
    pos = pizzeria
    t = timedelta(0)
    for consegna in giro.consegne:
        t += tempo_percorrenza(pos, consegna.coordinate, config)
        tempi_arrivo_relativi.append(t)
        t += config.tempo_sosta
        pos = consegna.coordinate

    # Fase 2: determina l'orario di partenza come il più tardi possibile
    # tale che OGNI consegna arrivi entro il suo slot
    # (senza tolleranza qui — la tolleranza si usa nella validazione)
    latest_departures: list[datetime] = []
    for consegna, arrivo_rel in zip(giro.consegne, tempi_arrivo_relativi):
        # Se parto a orario X, arrivo alla consegna a X + arrivo_rel
        # Voglio X + arrivo_rel <= consegna.slot
        # Quindi X <= consegna.slot - arrivo_rel
        latest = consegna.slot - arrivo_rel
        latest_departures.append(latest)

    giro.orario_partenza = min(latest_departures)

    # Fase 3: tempo dall'uscita all'ultima consegna
    giro.tempo_totale = tempi_arrivo_relativi[-1] + config.tempo_sosta

    # Fase 4: tempo di ritorno in pizzeria
    ultima_pos = giro.consegne[-1].coordinate
    tempo_rientro = tempo_percorrenza(ultima_pos, pizzeria, config)
    giro.tempo_ritorno = giro.tempo_totale + tempo_rientro

    return giro


def orario_ritorno(giro: Giro) -> datetime:
    """Orario in cui il fattorino rientra in pizzeria dopo il giro."""
    return giro.orario_partenza + giro.tempo_ritorno


# ---------------------------------------------------------------------------
# Validazione di un giro
# ---------------------------------------------------------------------------


def giro_valido(giro: Giro, pizzeria: Coordinate, config: Config) -> bool:
    """
    Verifica che un giro rispetti tutti i vincoli:
    1. Capacità pizze
    2. Tempo massimo (T_max) dalla partenza all'ultima consegna
    3. Ogni consegna arriva entro slot + tolleranza (non troppo tardi)
    4. Ogni consegna non arriva troppo in anticipo (slot - tolleranza)
    """
    # Vincolo capacità
    if giro.pizze_totali > config.capacita_pizze:
        return False

    # Vincolo T_max
    if giro.tempo_totale > config.t_max:
        return False

    # Vincolo rispetto slot con tolleranza (sia ritardo che anticipo)
    pos = pizzeria
    t = giro.orario_partenza
    for consegna in giro.consegne:
        t += tempo_percorrenza(pos, consegna.coordinate, config)
        # Troppo tardi: il cliente aspetta troppo
        if t > consegna.slot + config.tolleranza_ritardo:
            return False
        # Troppo presto: la pizza sarebbe fredda all'ora dello slot
        if t < consegna.slot - config.tolleranza_anticipo:
            return False
        t += config.tempo_sosta
        pos = consegna.coordinate

    return True


# ---------------------------------------------------------------------------
# Verifica conflitti nella timeline del fattorino
# ---------------------------------------------------------------------------


def causa_conflitto_timeline(
    fattorino: Fattorino,
    giro_candidato: Giro,
    giro_originale: Optional[Giro],
) -> bool:
    """
    Verifica che il giro candidato non si sovrapponga con altri giri del fattorino.

    giro_originale: se stiamo modificando un giro esistente, è il giro prima
    della modifica (da escludere dal confronto). None se è un giro nuovo.
    """
    partenza = giro_candidato.orario_partenza
    ritorno = orario_ritorno(giro_candidato)

    for giro in fattorino.giri_ordinati():
        # Salta il giro che stiamo sostituendo
        if giro_originale is not None and giro is giro_originale:
            continue

        giro_partenza = giro.orario_partenza
        giro_ritorno = orario_ritorno(giro)

        # C'è sovrapposizione se i due intervalli [partenza, ritorno] si intersecano
        if partenza < giro_ritorno and giro_partenza < ritorno:
            return True

    return False


# ---------------------------------------------------------------------------
# Cheapest insertion
# ---------------------------------------------------------------------------


def cheapest_insertion(
    giro: Giro,
    nuova_consegna: Consegna,
    pizzeria: Coordinate,
    config: Config,
) -> list[Giro]:
    """
    Prova a inserire la nuova consegna in ogni posizione del giro.
    Restituisce la lista di giri candidati validi, ordinati per tempo totale crescente.
    """
    candidati: list[Giro] = []

    for i in range(len(giro.consegne) + 1):
        g = deepcopy(giro)
        g.consegne.insert(i, nuova_consegna)
        calcola_tempi_giro(g, pizzeria, config)

        if giro_valido(g, pizzeria, config):
            candidati.append(g)

    # Ordina per tempo totale crescente (il migliore prima)
    candidati.sort(key=lambda g: g.tempo_totale)
    return candidati


# ---------------------------------------------------------------------------
# Algoritmo principale
# ---------------------------------------------------------------------------


def calcola_slot_disponibili(
    slot_list: list[datetime],
    nuovo_ordine_coordinate: Coordinate,
    nuovo_ordine_num_pizze: int,
    nuovo_ordine_id: str,
    fattorini: list[Fattorino],
    pizzeria: Coordinate,
    config: Config,
) -> list[SlotDisponibile]:
    """
    Per ogni slot nella lista, determina se è disponibile per il nuovo ordine
    e quale fattorino assegnare.

    Restituisce la lista degli slot disponibili con il fattorino ottimale per ciascuno.
    """

    if nuovo_ordine_num_pizze > config.capacita_pizze:
        return []  # ordine troppo grande per qualsiasi fattorino

    risultati: list[SlotDisponibile] = []

    for slot in slot_list:
        nuova_consegna = Consegna(
            id=nuovo_ordine_id,
            coordinate=nuovo_ordine_coordinate,
            num_pizze=nuovo_ordine_num_pizze,
            slot=slot,
        )

        miglior_opzione: Optional[SlotDisponibile] = None
        miglior_costo = float("inf")

        for fattorino in fattorini:
            # === OPZIONE A: inserire in un giro esistente ===
            for giro in fattorino.giri:
                # Verifica rapida capacità
                if giro.pizze_totali + nuovo_ordine_num_pizze > config.capacita_pizze:
                    continue

                # Cheapest insertion
                candidati = cheapest_insertion(giro, nuova_consegna, pizzeria, config)

                for giro_candidato in candidati:
                    # Verifica conflitti timeline
                    if causa_conflitto_timeline(fattorino, giro_candidato, giro):
                        continue

                    # Costo marginale: incremento del tempo totale
                    costo = (
                        giro_candidato.tempo_ritorno - giro.tempo_ritorno
                    ).total_seconds()

                    if costo < miglior_costo:
                        miglior_costo = costo
                        miglior_opzione = SlotDisponibile(
                            slot=slot,
                            fattorino_id=fattorino.id,
                            costo=costo,
                            tipo="inserimento",
                            giro_risultante=giro_candidato,
                        )

                    break  # prendi solo il miglior candidato per questo giro

            # === OPZIONE B: creare un nuovo giro ===
            nuovo_giro = Giro(
                fattorino_id=fattorino.id,
                consegne=[nuova_consegna],
            )
            calcola_tempi_giro(nuovo_giro, pizzeria, config)

            if giro_valido(
                nuovo_giro, pizzeria, config
            ) and not causa_conflitto_timeline(fattorino, nuovo_giro, None):
                # Costo pieno con penalità
                costo = (
                    nuovo_giro.tempo_ritorno.total_seconds()
                    * config.penalita_nuovo_giro
                )

                if costo < miglior_costo:
                    miglior_costo = costo
                    miglior_opzione = SlotDisponibile(
                        slot=slot,
                        fattorino_id=fattorino.id,
                        costo=costo,
                        tipo="nuovo_giro",
                        giro_risultante=nuovo_giro,
                    )

        if miglior_opzione is not None:
            risultati.append(miglior_opzione)

    return risultati


# ---------------------------------------------------------------------------
# Conferma ordine: applica l'assegnazione
# ---------------------------------------------------------------------------


def conferma_ordine(
    slot_scelto: SlotDisponibile,
    fattorini: list[Fattorino],
    pizzeria: Coordinate,
    config: Config,
) -> None:
    """
    Dopo che l'operatore ha scelto uno slot, applica l'assegnazione:
    aggiorna i giri del fattorino.
    """
    fattorino = next(f for f in fattorini if f.id == slot_scelto.fattorino_id)

    if slot_scelto.tipo == "inserimento":
        # Trova e sostituisci il giro originale con quello aggiornato
        giro_aggiornato = slot_scelto.giro_risultante
        for i, giro in enumerate(fattorino.giri):
            if giro.fattorino_id == giro_aggiornato.fattorino_id:
                # Confronta: il giro originale è quello che, privato della nuova
                # consegna, corrisponde a un giro esistente.
                # Usiamo l'euristica: il giro che contiene un sottoinsieme delle
                # consegne del giro aggiornato.
                ids_giro = {c.id for c in giro.consegne}
                ids_aggiornato = {c.id for c in giro_aggiornato.consegne}
                if ids_giro.issubset(ids_aggiornato):
                    fattorino.giri[i] = giro_aggiornato
                    return

    # tipo == "nuovo_giro" oppure fallback
    fattorino.giri.append(slot_scelto.giro_risultante)
