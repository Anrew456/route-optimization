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
    max_consegne_per_giro: int = 3  # massimo numero di consegne per giro
    peso_deviazione: float = 1.0  # peso penalità deviazione |arrivo - slot|

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


def deviazione_giro(giro: Giro, pizzeria: Coordinate, config: Config) -> float:
    """Somma delle deviazioni |arrivo - slot| per ogni consegna (in minuti)."""
    if not giro.consegne or not giro.orario_partenza:
        return 0.0
    pos = pizzeria
    t = giro.orario_partenza
    dev = 0.0
    for consegna in giro.consegne:
        t += tempo_percorrenza(pos, consegna.coordinate, config)
        dev += abs((t - consegna.slot).total_seconds()) / 60.0
        t += config.tempo_sosta
        pos = consegna.coordinate
    return dev


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

    # Vincolo numero massimo consegne per giro
    if len(giro.consegne) > config.max_consegne_per_giro:
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
# Ri-ottimizzazione globale
# ---------------------------------------------------------------------------


def estrai_tutte_consegne(fattorini: list[Fattorino]) -> list[Consegna]:
    """Raccoglie tutte le consegne da tutti i giri di tutti i fattorini."""
    consegne: list[Consegna] = []
    for f in fattorini:
        for g in f.giri:
            for c in g.consegne:
                consegne.append(
                    Consegna(
                        id=c.id,
                        coordinate=Coordinate(c.coordinate.lat, c.coordinate.lon),
                        num_pizze=c.num_pizze,
                        slot=c.slot,
                    )
                )
    return consegne


def fattorino_ha_conflitti(giri: list[Giro]) -> bool:
    """Verifica se ci sono sovrapposizioni tra i giri di un fattorino."""
    for i in range(len(giri)):
        for j in range(i + 1, len(giri)):
            if giri[i].orario_partenza < orario_ritorno(giri[j]) and \
               giri[j].orario_partenza < orario_ritorno(giri[i]):
                return True
    return False


def costo_totale(fattorini: list[Fattorino], pizzeria: Coordinate, config: Config) -> float:
    """Costo complessivo di tutti i giri."""
    total = 0.0
    for f in fattorini:
        for g in f.giri:
            if g.tempo_ritorno:
                # --- Variante 1: costo per consegna ---
                total += g.tempo_ritorno.total_seconds() / len(g.consegne)
                # --- Variante 3: savings (usa tempo di ritorno grezzo) ---
                # total += g.tempo_ritorno.total_seconds()
                total += config.peso_deviazione * deviazione_giro(g, pizzeria, config)
    return total


def ricostruisci_giri(
    tutte_consegne: list[Consegna],
    num_fattorini: int,
    pizzeria: Coordinate,
    config: Config,
) -> list[Fattorino]:
    """
    Ricostruisce tutti i giri da zero con round-robin seeding + cheapest insertion.

    Fase 1 (round-robin): per ogni slot, assegna le prime consegne a fattorini diversi
    (una per fattorino, partendo dal meno carico) per bilanciare il carico.

    Fase 2 (greedy): le consegne rimanenti vengono inserite con cheapest insertion
    o creano nuovi giri (con penalità).

    Seed ordering: per slot (crescente), poi per distanza dalla pizzeria (decrescente).
    """
    # Seed ordering
    ordinati = sorted(
        tutte_consegne,
        key=lambda c: (c.slot, -haversine_km(pizzeria, c.coordinate)),
    )

    fattorini = [Fattorino(id=i + 1) for i in range(num_fattorini)]

    # -- Fase 1: round-robin seeding per slot --
    # Raggruppa per slot
    consegne_per_slot: dict[datetime, list[Consegna]] = {}
    for c in ordinati:
        consegne_per_slot.setdefault(c.slot, []).append(c)

    assegnate: set[str] = set()

    for slot in sorted(consegne_per_slot.keys()):
        consegne_slot = consegne_per_slot[slot]
        n_seeds = min(len(consegne_slot), num_fattorini)

        # Fattorini ordinati per carico crescente (meno giri prima)
        fattorini_ordinati = sorted(fattorini, key=lambda f: len(f.giri))

        for i in range(n_seeds):
            consegna = consegne_slot[i]
            fattorino = fattorini_ordinati[i]

            nuovo_giro = Giro(fattorino_id=fattorino.id, consegne=[consegna])
            calcola_tempi_giro(nuovo_giro, pizzeria, config)

            if giro_valido(nuovo_giro, pizzeria, config) and not causa_conflitto_timeline(
                fattorino, nuovo_giro, None
            ):
                fattorino.giri.append(nuovo_giro)
                assegnate.add(consegna.id)

    # -- Fase 2: greedy insertion per le consegne rimanenti --
    rimanenti = [c for c in ordinati if c.id not in assegnate]

    for consegna in rimanenti:
        miglior_opzione = None
        miglior_costo = float("inf")

        # Costo standalone: giro con solo questa consegna (serve per V3)
        giro_standalone = Giro(fattorino_id=0, consegne=[consegna])
        calcola_tempi_giro(giro_standalone, pizzeria, config)
        standalone_sec = giro_standalone.tempo_ritorno.total_seconds()

        for fattorino in fattorini:
            # Opzione A: inserire in un giro esistente
            for idx_giro, giro in enumerate(fattorino.giri):
                if giro.pizze_totali + consegna.num_pizze > config.capacita_pizze:
                    continue
                if len(giro.consegne) >= config.max_consegne_per_giro:
                    continue
                # Single-slot: solo giri con lo stesso slot
                if giro.consegne and giro.consegne[0].slot != consegna.slot:
                    continue

                candidati = cheapest_insertion(giro, consegna, pizzeria, config)
                for giro_candidato in candidati:
                    if causa_conflitto_timeline(fattorino, giro_candidato, giro):
                        continue
                    delta = (
                        giro_candidato.tempo_ritorno - giro.tempo_ritorno
                    ).total_seconds()

                    # --- Variante 1: costo per consegna ---
                    costo = (
                        giro_candidato.tempo_ritorno.total_seconds()
                        / len(giro_candidato.consegne)
                    )
                    # --- Variante 3: savings ---
                    # savings = standalone_sec - delta
                    # costo = delta * (standalone_sec / max(savings, 60))
                    costo += config.peso_deviazione * deviazione_giro(giro_candidato, pizzeria, config)

                    if costo < miglior_costo:
                        miglior_costo = costo
                        miglior_opzione = (
                            "inserimento",
                            fattorino,
                            idx_giro,
                            giro_candidato,
                        )
                    break

            # Opzione B: nuovo giro
            nuovo_giro = Giro(fattorino_id=fattorino.id, consegne=[consegna])
            calcola_tempi_giro(nuovo_giro, pizzeria, config)
            if giro_valido(nuovo_giro, pizzeria, config) and not causa_conflitto_timeline(
                fattorino, nuovo_giro, None
            ):
                # --- Variante 1: costo per consegna ---
                costo = (
                    nuovo_giro.tempo_ritorno.total_seconds()
                    + len(fattorino.giri) * 0.001
                )
                # --- Variante 3: savings ---
                # costo = standalone_sec + len(fattorino.giri) * 0.001
                costo += config.peso_deviazione * deviazione_giro(nuovo_giro, pizzeria, config)

                if costo < miglior_costo:
                    miglior_costo = costo
                    miglior_opzione = (
                        "nuovo_giro",
                        fattorino,
                        -1,
                        nuovo_giro,
                    )

        if miglior_opzione:
            tipo, fattorino, idx, giro_result = miglior_opzione
            if tipo == "inserimento":
                fattorino.giri[idx] = giro_result
            else:
                fattorino.giri.append(giro_result)

    return fattorini


def two_opt(giro: Giro, pizzeria: Coordinate, config: Config) -> Giro:
    """Migliora l'ordine delle consegne invertendo sotto-sequenze (2-opt)."""
    n = len(giro.consegne)
    if n < 3:
        return giro

    best = deepcopy(giro)
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                candidato = deepcopy(best)
                candidato.consegne[i + 1 : j + 1] = reversed(
                    candidato.consegne[i + 1 : j + 1]
                )
                calcola_tempi_giro(candidato, pizzeria, config)
                if (
                    giro_valido(candidato, pizzeria, config)
                    and candidato.tempo_ritorno < best.tempo_ritorno
                ):
                    best = candidato
                    improved = True
    return best


def two_opt_all(fattorini: list[Fattorino], pizzeria: Coordinate, config: Config) -> None:
    """Applica 2-opt a tutti i giri."""
    for f in fattorini:
        for i, g in enumerate(f.giri):
            f.giri[i] = two_opt(g, pizzeria, config)


def or_opt(fattorini: list[Fattorino], pizzeria: Coordinate, config: Config) -> None:
    """Prova a spostare ogni consegna in un giro migliore."""
    improved = True
    while improved:
        improved = False
        for sf in fattorini:
            if improved:
                break
            for si, sg in enumerate(sf.giri):
                if improved:
                    break
                for di in range(len(sg.consegne)):
                    if improved:
                        break
                    consegna = sg.consegne[di]
                    for df in fattorini:
                        if improved:
                            break
                        for dgi, dg in enumerate(df.giri):
                            if sf is df and si == dgi:
                                continue
                            if dg.consegne and dg.consegne[0].slot != consegna.slot:
                                continue
                            if len(dg.consegne) >= config.max_consegne_per_giro:
                                continue
                            if dg.pizze_totali + consegna.num_pizze > config.capacita_pizze:
                                continue

                            # Costruisci source senza la consegna
                            nuovo_src = deepcopy(sg)
                            nuovo_src.consegne.pop(di)
                            if nuovo_src.consegne:
                                calcola_tempi_giro(nuovo_src, pizzeria, config)

                            # Prova inserimento nel destination
                            candidati_dst = cheapest_insertion(
                                dg, consegna, pizzeria, config
                            )
                            if not candidati_dst:
                                continue
                            nuovo_dst = candidati_dst[0]

                            # Verifica miglioramento
                            # --- Variante 1: costo per consegna ---
                            old_total = (
                                sg.tempo_ritorno.total_seconds() / len(sg.consegne)
                                + dg.tempo_ritorno.total_seconds() / len(dg.consegne)
                            )
                            new_src_cost = (
                                nuovo_src.tempo_ritorno.total_seconds() / len(nuovo_src.consegne)
                                if nuovo_src.consegne else 0
                            )
                            new_total = (
                                new_src_cost
                                + nuovo_dst.tempo_ritorno.total_seconds() / len(nuovo_dst.consegne)
                            )
                            # --- Variante 3: savings (usa tempo di ritorno grezzo) ---
                            # old_total = sg.tempo_ritorno.total_seconds() + dg.tempo_ritorno.total_seconds()
                            # new_total = (
                            #     (nuovo_src.tempo_ritorno.total_seconds() if nuovo_src.consegne else 0)
                            #     + nuovo_dst.tempo_ritorno.total_seconds()
                            # )
                            old_total += config.peso_deviazione * (
                                deviazione_giro(sg, pizzeria, config) + deviazione_giro(dg, pizzeria, config)
                            )
                            new_total += config.peso_deviazione * (
                                (deviazione_giro(nuovo_src, pizzeria, config) if nuovo_src.consegne else 0)
                                + deviazione_giro(nuovo_dst, pizzeria, config)
                            )
                            if new_total >= old_total - 0.01:
                                continue

                            # Verifica conflitti timeline
                            valid = True
                            if sf is df:
                                temp_giri = [
                                    (nuovo_src if i == si else nuovo_dst if i == dgi else g)
                                    for i, g in enumerate(sf.giri)
                                    if not (i == si and not nuovo_src.consegne)
                                ]
                                valid = not fattorino_ha_conflitti(temp_giri)
                            else:
                                src_giri = [
                                    (nuovo_src if i == si else g)
                                    for i, g in enumerate(sf.giri)
                                    if not (i == si and not nuovo_src.consegne)
                                ]
                                dst_giri = [
                                    (nuovo_dst if i == dgi else g)
                                    for i, g in enumerate(df.giri)
                                ]
                                valid = not fattorino_ha_conflitti(src_giri) and not fattorino_ha_conflitti(dst_giri)
                            if not valid:
                                continue

                            # Applica
                            sf.giri[si] = nuovo_src
                            df.giri[dgi] = nuovo_dst
                            for f in fattorini:
                                f.giri = [g for g in f.giri if g.consegne]
                            improved = True


# ---------------------------------------------------------------------------
# Algoritmo principale (con ri-ottimizzazione globale)
# ---------------------------------------------------------------------------


@dataclass
class SlotDisponibileGlobale:
    """Risultato della ri-ottimizzazione: lo slot con l'assegnazione completa."""

    slot: datetime
    fattorini_risultanti: list[Fattorino]
    costo: float  # incremento costo totale rispetto allo stato attuale


def calcola_slot_disponibili(
    slot_list: list[datetime],
    nuovo_ordine_coordinate: Coordinate,
    nuovo_ordine_num_pizze: int,
    nuovo_ordine_id: str,
    fattorini: list[Fattorino],
    pizzeria: Coordinate,
    config: Config,
) -> list[SlotDisponibileGlobale]:
    """
    Per ogni slot nella lista, ricostruisce TUTTI i giri da zero includendo
    il nuovo ordine, poi applica local search (2-opt + or-opt).

    Restituisce la lista degli slot disponibili con l'assegnazione completa ottimizzata.
    """

    if nuovo_ordine_num_pizze > config.capacita_pizze:
        return []

    consegne_esistenti = estrai_tutte_consegne(fattorini)
    costo_attuale = costo_totale(fattorini, pizzeria, config)
    risultati: list[SlotDisponibileGlobale] = []

    for slot in slot_list:
        nuova_consegna = Consegna(
            id=nuovo_ordine_id,
            coordinate=nuovo_ordine_coordinate,
            num_pizze=nuovo_ordine_num_pizze,
            slot=slot,
        )
        tutte = consegne_esistenti + [nuova_consegna]

        nuovi_fattorini = ricostruisci_giri(
            tutte, config.num_fattorini, pizzeria, config
        )
        two_opt_all(nuovi_fattorini, pizzeria, config)
        or_opt(nuovi_fattorini, pizzeria, config)

        # Verifica che TUTTE le consegne (esistenti + nuova) siano state assegnate
        ids_assegnati = {
            c.id for f in nuovi_fattorini for g in f.giri for c in g.consegne
        }
        ids_richiesti = {c.id for c in tutte}
        if ids_assegnati != ids_richiesti:
            continue

        costo = costo_totale(nuovi_fattorini, pizzeria, config) - costo_attuale
        risultati.append(
            SlotDisponibileGlobale(
                slot=slot,
                fattorini_risultanti=nuovi_fattorini,
                costo=costo,
            )
        )

    return risultati


# ---------------------------------------------------------------------------
# Conferma ordine: applica l'assegnazione
# ---------------------------------------------------------------------------


def conferma_ordine(
    slot_scelto: SlotDisponibileGlobale,
) -> list[Fattorino]:
    """
    Dopo che l'operatore ha scelto uno slot, restituisce la nuova
    assegnazione completa dei fattorini (ri-ottimizzata).
    """
    return slot_scelto.fattorini_risultanti
