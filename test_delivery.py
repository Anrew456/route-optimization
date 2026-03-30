"""
Test dello scenario di assegnazione slot e rider con ri-ottimizzazione globale.

Scenario: pizzeria a Padova centro, 3 fattorini, alcuni ordini già prenotati.
Un nuovo ordine arriva e l'algoritmo ri-ottimizza tutti i giri.
"""

from datetime import datetime, timedelta

from delivery_slots import (
    Config,
    Consegna,
    Coordinate,
    Fattorino,
    SlotDisponibileGlobale,
    calcola_slot_disponibili,
    conferma_ordine,
    estrai_tutte_consegne,
    haversine_km,
    ricostruisci_giri,
    tempo_percorrenza,
    two_opt_all,
    or_opt,
)


def crea_slot(
    ora_inizio: int, minuto_inizio: int, ora_fine: int, intervallo_minuti: int
) -> list[datetime]:
    """Genera una lista di slot a intervalli regolari per la giornata odierna."""
    oggi = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    slot = []
    t = oggi.replace(hour=ora_inizio, minute=minuto_inizio)
    fine = oggi.replace(hour=ora_fine, minute=0)
    while t <= fine:
        slot.append(t)
        t += timedelta(minutes=intervallo_minuti)
    return slot


def stampa_risultati(risultati: list[SlotDisponibileGlobale]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  SLOT DISPONIBILI: {len(risultati)}")
    print(f"{'=' * 60}")
    for r in risultati:
        n_giri = sum(len(f.giri) for f in r.fattorini_risultanti)
        n_cons = sum(
            len(g.consegne) for f in r.fattorini_risultanti for g in f.giri
        )
        print(
            f"  Slot {r.slot.strftime('%H:%M')} | "
            f"Costo: {r.costo:>7.0f}s | "
            f"{n_giri} giri, {n_cons} consegne"
        )
    print()


def stampa_stato_fattorini(fattorini: list[Fattorino]) -> None:
    print(f"\n{'=' * 60}")
    print("  STATO FATTORINI")
    print(f"{'=' * 60}")
    for f in fattorini:
        print(f"\n  Fattorino #{f.id} — {len(f.giri)} giri pianificati:")
        for g in f.giri_ordinati():
            consegne_str = ", ".join(
                f"{c.id}@{c.slot.strftime('%H:%M')}" for c in g.consegne
            )
            partenza = g.orario_partenza.strftime("%H:%M") if g.orario_partenza else "?"
            durata = (
                f"{g.tempo_ritorno.total_seconds() / 60:.1f}min"
                if g.tempo_ritorno
                else "?"
            )
            print(
                f"    Giro: partenza {partenza}, durata {durata}, "
                f"pizze: {g.pizze_totali}, consegne: [{consegne_str}]"
            )
    print()


def main():
    # --- Configurazione ---
    config = Config(
        num_fattorini=3,
        capacita_pizze=8,
        t_max_minuti=30,
        tolleranza_anticipo_minuti=5,
        tolleranza_ritardo_minuti=10,
        fattore_detour=1.3,
        velocita_media_kmh=25,
        tempo_sosta_minuti=3,
        penalita_nuovo_giro=1.5,
        max_consegne_per_giro=3,
    )

    # Pizzeria in centro a Padova (Piazza delle Erbe)
    pizzeria = Coordinate(lat=45.4075, lon=11.8768)

    # --- Slot: dalle 18:00 alle 21:00 ogni 15 minuti ---
    slot_list = crea_slot(18, 0, 21, 15)
    print(
        f"Slot configurati: {len(slot_list)} "
        f"(da {slot_list[0].strftime('%H:%M')} a {slot_list[-1].strftime('%H:%M')})"
    )

    # --- Ordini esistenti ---
    oggi = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    ordini_esistenti = [
        # Zona Arcella (nord)
        Consegna(
            "ord-1", Coordinate(45.4180, 11.8810), 3, oggi.replace(hour=18, minute=30)
        ),
        # Zona Stanga (est)
        Consegna(
            "ord-2", Coordinate(45.4100, 11.8950), 2, oggi.replace(hour=18, minute=30)
        ),
        # Zona Forcellini (sud-est)
        Consegna(
            "ord-3", Coordinate(45.3950, 11.9050), 4, oggi.replace(hour=19, minute=0)
        ),
        # Zona Mandria (ovest)
        Consegna(
            "ord-4", Coordinate(45.4050, 11.8600), 2, oggi.replace(hour=19, minute=0)
        ),
        # Zona Sacra Famiglia (nord-ovest)
        Consegna(
            "ord-5", Coordinate(45.4150, 11.8650), 3, oggi.replace(hour=19, minute=0)
        ),
    ]

    # Costruisci assegnazione iniziale con ri-ottimizzazione globale
    fattorini = ricostruisci_giri(ordini_esistenti, config.num_fattorini, pizzeria, config)
    two_opt_all(fattorini, pizzeria, config)
    or_opt(fattorini, pizzeria, config)

    stampa_stato_fattorini(fattorini)

    # Verifica che tutti gli ordini siano stati assegnati
    tutte = estrai_tutte_consegne(fattorini)
    ids_assegnati = {c.id for c in tutte}
    ids_attesi = {c.id for c in ordini_esistenti}
    assert ids_assegnati == ids_attesi, (
        f"Non tutti gli ordini assegnati: mancano {ids_attesi - ids_assegnati}"
    )
    print("  ✓ Tutti i 5 ordini esistenti correttamente assegnati")

    # Verifica vincolo max consegne per giro
    for f in fattorini:
        for g in f.giri:
            assert len(g.consegne) <= config.max_consegne_per_giro, (
                f"Giro di fattorino #{f.id} ha {len(g.consegne)} consegne, "
                f"max ammesso: {config.max_consegne_per_giro}"
            )
    print(f"  ✓ Nessun giro supera {config.max_consegne_per_giro} consegne")

    # === TEST 1: Nuovo ordine zona Arcella (vicino a ord-1) ===
    print("\n" + "=" * 60)
    print("  TEST 1: Nuovo ordine zona Arcella (ri-ottimizzazione globale)")
    print("=" * 60)

    risultati = calcola_slot_disponibili(
        slot_list=slot_list,
        nuovo_ordine_coordinate=Coordinate(45.4190, 11.8830),
        nuovo_ordine_num_pizze=2,
        nuovo_ordine_id="nuovo-1",
        fattorini=fattorini,
        pizzeria=pizzeria,
        config=config,
    )
    stampa_risultati(risultati)

    # Verifica che lo slot 18:30 sia disponibile e il nuovo ordine sia assegnato
    slot_1830 = [r for r in risultati if r.slot.hour == 18 and r.slot.minute == 30]
    assert len(slot_1830) > 0, "Slot 18:30 non disponibile"
    r = slot_1830[0]

    # Verifica che "nuovo-1" sia presente nell'assegnazione
    nuovo1_presente = any(
        c.id == "nuovo-1"
        for f in r.fattorini_risultanti
        for g in f.giri
        for c in g.consegne
    )
    assert nuovo1_presente, "nuovo-1 non trovato nell'assegnazione"
    print("  ✓ Slot 18:30 disponibile, nuovo-1 correttamente assegnato")

    # Verifica che tutti gli ordini esistenti siano ancora presenti
    ids_dopo = {
        c.id for f in r.fattorini_risultanti for g in f.giri for c in g.consegne
    }
    assert ids_attesi.issubset(ids_dopo), (
        f"Ordini persi dopo ri-ottimizzazione: {ids_attesi - ids_dopo}"
    )
    print("  ✓ Tutti gli ordini esistenti mantenuti dopo ri-ottimizzazione")

    # === TEST 2: Conferma ordine e verifica stato ===
    print("\n" + "=" * 60)
    print("  TEST 2: Conferma ordine e verifica ri-ottimizzazione")
    print("=" * 60)

    fattorini = conferma_ordine(slot_1830[0])
    stampa_stato_fattorini(fattorini)

    tutte_dopo = estrai_tutte_consegne(fattorini)
    assert len(tutte_dopo) == 6, f"Attese 6 consegne, trovate {len(tutte_dopo)}"
    print("  ✓ 6 consegne totali dopo conferma")

    # Verifica vincolo max consegne
    for f in fattorini:
        for g in f.giri:
            assert len(g.consegne) <= config.max_consegne_per_giro, (
                f"Giro di fattorino #{f.id} ha {len(g.consegne)} consegne (max {config.max_consegne_per_giro})"
            )
    print(f"  ✓ Vincolo max {config.max_consegne_per_giro} consegne/giro rispettato")

    # === TEST 3: Ordine che eccede capacità ===
    print("\n" + "=" * 60)
    print("  TEST 3: Ordine con 9 pizze (eccede capacità)")
    print("  Deve restituire lista vuota")
    print("=" * 60)

    risultati3 = calcola_slot_disponibili(
        slot_list=slot_list,
        nuovo_ordine_coordinate=Coordinate(45.4100, 11.8900),
        nuovo_ordine_num_pizze=9,
        nuovo_ordine_id="nuovo-3",
        fattorini=fattorini,
        pizzeria=pizzeria,
        config=config,
    )
    assert len(risultati3) == 0, f"Attesi 0 slot, trovati {len(risultati3)}"
    print("  ✓ Correttamente restituiti 0 slot disponibili")

    # === TEST 4: Vincolo max consegne per giro ===
    print("\n" + "=" * 60)
    print("  TEST 4: Vincolo max consegne per giro (max=2)")
    print("  Con max=2, giri esistenti con 2 consegne non accettano inserimenti")
    print("=" * 60)

    config_limitato = Config(
        num_fattorini=3,
        capacita_pizze=8,
        t_max_minuti=30,
        tolleranza_anticipo_minuti=5,
        tolleranza_ritardo_minuti=10,
        fattore_detour=1.3,
        velocita_media_kmh=25,
        tempo_sosta_minuti=3,
        penalita_nuovo_giro=1.5,
        max_consegne_per_giro=2,
    )

    # Ricostruisci con limite di 2
    fattorini_t4 = ricostruisci_giri(
        ordini_esistenti, config_limitato.num_fattorini, pizzeria, config_limitato
    )
    two_opt_all(fattorini_t4, pizzeria, config_limitato)
    or_opt(fattorini_t4, pizzeria, config_limitato)

    for f in fattorini_t4:
        for g in f.giri:
            assert len(g.consegne) <= 2, (
                f"Giro di fattorino #{f.id} ha {len(g.consegne)} consegne (max 2)"
            )
    print("  ✓ Con max_consegne_per_giro=2, nessun giro supera 2 consegne")

    n_giri = sum(len(f.giri) for f in fattorini_t4)
    print(f"    {n_giri} giri totali (vs. prima con max=3)")
    stampa_stato_fattorini(fattorini_t4)

    # === TEST 5: Verifica distanze Haversine ===
    print("\n" + "=" * 60)
    print("  TEST 5: Verifica calcolo distanze")
    print("=" * 60)

    dist = haversine_km(pizzeria, Coordinate(45.4180, 11.8810))
    print(f"  Pizzeria → Arcella: {dist:.2f} km (linea d'aria)")
    print(f"  Stimata reale:      {dist * config.fattore_detour:.2f} km")
    tempo = tempo_percorrenza(pizzeria, Coordinate(45.4180, 11.8810), config)
    print(f"  Tempo stimato:      {tempo.total_seconds() / 60:.1f} minuti")

    dist2 = haversine_km(pizzeria, Coordinate(45.3950, 11.9050))
    print(f"\n  Pizzeria → Forcellini: {dist2:.2f} km (linea d'aria)")
    print(f"  Stimata reale:         {dist2 * config.fattore_detour:.2f} km")
    tempo2 = tempo_percorrenza(pizzeria, Coordinate(45.3950, 11.9050), config)
    print(f"  Tempo stimato:         {tempo2.total_seconds() / 60:.1f} minuti")

    # === TEST 6: Coerenza geografica ===
    print("\n" + "=" * 60)
    print("  TEST 6: Verifica coerenza geografica dei giri")
    print("=" * 60)

    # Costruisci scenario con consegne in direzioni opposte
    consegne_geo = [
        Consegna("nord-1", Coordinate(45.4300, 11.8768), 2, oggi.replace(hour=19, minute=0)),
        Consegna("nord-2", Coordinate(45.4250, 11.8800), 2, oggi.replace(hour=19, minute=0)),
        Consegna("sud-1", Coordinate(45.3850, 11.8768), 2, oggi.replace(hour=19, minute=0)),
        Consegna("sud-2", Coordinate(45.3900, 11.8800), 2, oggi.replace(hour=19, minute=0)),
    ]
    fattorini_geo = ricostruisci_giri(consegne_geo, 2, pizzeria, config)
    two_opt_all(fattorini_geo, pizzeria, config)

    # Verifica che nord e sud siano in giri diversi
    for f in fattorini_geo:
        for g in f.giri:
            ids = [c.id for c in g.consegne]
            has_nord = any("nord" in i for i in ids)
            has_sud = any("sud" in i for i in ids)
            assert not (has_nord and has_sud), (
                f"Giro mescola nord e sud: {ids}"
            )
    print("  ✓ Consegne nord e sud correttamente separate in giri diversi")
    stampa_stato_fattorini(fattorini_geo)

    # === TEST 7: Bilanciamento carico fattorini ===
    print("\n" + "=" * 60)
    print("  TEST 7: Bilanciamento carico — 3 consegne lontane, 3 fattorini")
    print("  Devono essere distribuite su fattorini diversi")
    print("=" * 60)

    consegne_bilanciate = [
        # Arcella (nord)
        Consegna("bil-1", Coordinate(45.4300, 11.8768), 2, oggi.replace(hour=18, minute=30)),
        # Forcellini (sud-est)
        Consegna("bil-2", Coordinate(45.3850, 11.9100), 2, oggi.replace(hour=18, minute=30)),
        # Mandria (ovest)
        Consegna("bil-3", Coordinate(45.4050, 11.8500), 2, oggi.replace(hour=18, minute=30)),
    ]
    fattorini_bil = ricostruisci_giri(consegne_bilanciate, 3, pizzeria, config)
    two_opt_all(fattorini_bil, pizzeria, config)
    or_opt(fattorini_bil, pizzeria, config)

    # Ogni fattorino deve avere al massimo 1 consegna
    fattorini_con_giri = [f for f in fattorini_bil if f.giri]
    assert len(fattorini_con_giri) == 3, (
        f"Attesi 3 fattorini con giri, trovati {len(fattorini_con_giri)}"
    )
    for f in fattorini_bil:
        n_consegne = sum(len(g.consegne) for g in f.giri)
        assert n_consegne <= 1, (
            f"Fattorino #{f.id} ha {n_consegne} consegne, attesa max 1"
        )
    print("  ✓ 3 consegne lontane distribuite su 3 fattorini diversi")
    stampa_stato_fattorini(fattorini_bil)

    print("\n" + "=" * 60)
    print("  TUTTI I TEST SUPERATI ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
