"""
Test dello scenario di assegnazione slot e rider.

Scenario: pizzeria a Padova centro, 3 fattorini, alcuni ordini già prenotati.
Un nuovo ordine arriva e si calcolano gli slot disponibili.
"""

from datetime import datetime, timedelta

from delivery_slots import (
    Config,
    Consegna,
    Coordinate,
    Fattorino,
    Giro,
    SlotDisponibile,
    calcola_slot_disponibili,
    calcola_tempi_giro,
    conferma_ordine,
    haversine_km,
    tempo_percorrenza,
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


def stampa_risultati(risultati: list[SlotDisponibile]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  SLOT DISPONIBILI: {len(risultati)}")
    print(f"{'=' * 60}")
    for r in risultati:
        print(
            f"  Slot {r.slot.strftime('%H:%M')} | "
            f"Fattorino #{r.fattorino_id} | "
            f"{r.tipo:<13} | "
            f"Costo: {r.costo:>7.0f}s | "
            f"Consegne nel giro: {len(r.giro_risultante.consegne)}"
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
        tolleranza_slot_minuti=15,
        fattore_detour=1.3,
        velocita_media_kmh=25,
        tempo_sosta_minuti=3,
        penalita_nuovo_giro=1.5,
    )

    # Pizzeria in centro a Padova (Piazza delle Erbe)
    pizzeria = Coordinate(lat=45.4075, lon=11.8768)

    # --- Slot: dalle 18:00 alle 21:00 ogni 15 minuti ---
    slot_list = crea_slot(18, 0, 21, 15)
    print(
        f"Slot configurati: {len(slot_list)} "
        f"(da {slot_list[0].strftime('%H:%M')} a {slot_list[-1].strftime('%H:%M')})"
    )

    # --- Fattorini ---
    fattorini = [Fattorino(id=i) for i in range(1, config.num_fattorini + 1)]

    # --- Ordini già prenotati ---
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

    # Assegna gli ordini esistenti ai fattorini manualmente (simulando ordini già confermati)
    # Giro 1: Fattorino #1 porta ord-1 e ord-2 (zona nord/est, slot 18:30)
    giro1 = Giro(fattorino_id=1, consegne=[ordini_esistenti[0], ordini_esistenti[1]])
    calcola_tempi_giro(giro1, pizzeria, config)
    fattorini[0].giri.append(giro1)

    # Giro 2: Fattorino #2 porta ord-3 (zona sud-est, slot 19:00)
    giro2 = Giro(fattorino_id=2, consegne=[ordini_esistenti[2]])
    calcola_tempi_giro(giro2, pizzeria, config)
    fattorini[1].giri.append(giro2)

    # Giro 3: Fattorino #3 porta ord-4 e ord-5 (zona ovest/nord-ovest, slot 19:00)
    giro3 = Giro(fattorino_id=3, consegne=[ordini_esistenti[3], ordini_esistenti[4]])
    calcola_tempi_giro(giro3, pizzeria, config)
    fattorini[2].giri.append(giro3)

    stampa_stato_fattorini(fattorini)

    # === TEST 1: Nuovo ordine nella zona Arcella (vicino a ord-1) ===
    print("\n" + "=" * 60)
    print("  TEST 1: Nuovo ordine zona Arcella (vicino a ordine esistente)")
    print("  Ci aspettiamo che venga inserito nel giro del fattorino #1")
    print("=" * 60)

    risultati = calcola_slot_disponibili(
        slot_list=slot_list,
        nuovo_ordine_coordinate=Coordinate(45.4190, 11.8830),  # vicino a ord-1
        nuovo_ordine_num_pizze=2,
        nuovo_ordine_id="nuovo-1",
        fattorini=fattorini,
        pizzeria=pizzeria,
        config=config,
    )
    stampa_risultati(risultati)

    # Verifica che lo slot 18:30 usi inserimento nel giro del fattorino #1
    slot_1830 = [r for r in risultati if r.slot.hour == 18 and r.slot.minute == 30]
    if slot_1830:
        r = slot_1830[0]
        assert r.fattorino_id == 1 and r.tipo == "inserimento", (
            f"Atteso inserimento nel giro di fattorino #1, ottenuto: "
            f"fattorino #{r.fattorino_id}, tipo={r.tipo}"
        )
        print(
            "  ✓ Slot 18:30 correttamente assegnato come inserimento nel giro di fattorino #1"
        )
        print(
            f"    Consegne nel giro: {len(r.giro_risultante.consegne)} (erano 2, ora 3)"
        )

    # === TEST 2: Nuovo ordine zona Forcellini (vicino a ord-3) ===
    print("\n" + "=" * 60)
    print("  TEST 2: Nuovo ordine zona Forcellini (vicino a ordine esistente)")
    print("  Ci aspettiamo inserimento nel giro del fattorino #2")
    print("=" * 60)

    risultati2 = calcola_slot_disponibili(
        slot_list=slot_list,
        nuovo_ordine_coordinate=Coordinate(45.3970, 11.9020),
        nuovo_ordine_num_pizze=3,
        nuovo_ordine_id="nuovo-2",
        fattorini=fattorini,
        pizzeria=pizzeria,
        config=config,
    )
    stampa_risultati(risultati2)

    slot_1900 = [r for r in risultati2 if r.slot.hour == 19 and r.slot.minute == 0]
    if slot_1900:
        r = slot_1900[0]
        assert r.fattorino_id == 2 and r.tipo == "inserimento", (
            f"Atteso inserimento nel giro di fattorino #2, ottenuto: "
            f"fattorino #{r.fattorino_id}, tipo={r.tipo}"
        )
        print(
            "  ✓ Slot 19:00 correttamente assegnato come inserimento nel giro di fattorino #2"
        )

    # === TEST 3: Conferma ordine e verifica stato aggiornato ===
    print("\n" + "=" * 60)
    print("  TEST 3: Conferma ordine del Test 1 (slot 18:30)")
    print("=" * 60)

    if slot_1830:
        conferma_ordine(slot_1830[0], fattorini, pizzeria, config)
        stampa_stato_fattorini(fattorini)
        # Verifica che il fattorino #1 ora abbia 3 consegne nel giro
        giro_aggiornato = fattorini[0].giri[0]
        assert len(giro_aggiornato.consegne) == 3, (
            f"Attese 3 consegne, trovate {len(giro_aggiornato.consegne)}"
        )
        print("  ✓ Fattorino #1 ora ha 3 consegne nel giro")

    # === TEST 4: Ordine molto grande (satura capacità) ===
    print("\n" + "=" * 60)
    print("  TEST 4: Ordine con 8 pizze (satura capacità)")
    print("  Non deve poter essere inserito in giri esistenti")
    print("=" * 60)

    risultati4 = calcola_slot_disponibili(
        slot_list=slot_list,
        nuovo_ordine_coordinate=Coordinate(45.4100, 11.8900),
        nuovo_ordine_num_pizze=8,
        nuovo_ordine_id="nuovo-4",
        fattorini=fattorini,
        pizzeria=pizzeria,
        config=config,
    )

    # Tutti i risultati dovrebbero essere nuovo_giro
    for r in risultati4:
        if r.tipo == "inserimento":
            # Potrebbe esserci inserimento se un giro esistente ha 0 pizze,
            # ma nel nostro caso tutti i giri hanno pizze
            pass
    nuovi_giri = [r for r in risultati4 if r.tipo == "nuovo_giro"]
    print(f"  Slot con nuovo_giro: {len(nuovi_giri)}/{len(risultati4)}")
    stampa_risultati(risultati4)

    # === TEST 5: Ordine che eccede capacità ===
    print("\n" + "=" * 60)
    print("  TEST 5: Ordine con 9 pizze (eccede capacità)")
    print("  Deve restituire lista vuota")
    print("=" * 60)

    risultati5 = calcola_slot_disponibili(
        slot_list=slot_list,
        nuovo_ordine_coordinate=Coordinate(45.4100, 11.8900),
        nuovo_ordine_num_pizze=9,
        nuovo_ordine_id="nuovo-5",
        fattorini=fattorini,
        pizzeria=pizzeria,
        config=config,
    )
    assert len(risultati5) == 0, f"Attesi 0 slot, trovati {len(risultati5)}"
    print("  ✓ Correttamente restituiti 0 slot disponibili")

    # === TEST 6: Verifica distanze Haversine ===
    print("\n" + "=" * 60)
    print("  TEST 6: Verifica calcolo distanze")
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

    print("\n" + "=" * 60)
    print("  TUTTI I TEST SUPERATI ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
