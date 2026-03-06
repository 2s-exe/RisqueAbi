"""
init_db.py — Charge le CSV agressions_abidjan_clean.csv dans une base SQLite
et crée les tables de statistiques agrégées utilisées par l'application.
"""

import sqlite3
import csv
import os

CSV_PATH = "agressions_abidjan_clean.csv"
DB_PATH  = os.path.join(os.path.dirname(__file__), "agressions.db")


def create_tables(conn):
    conn.executescript("""
        -- Table brute : tous les incidents du CSV
        CREATE TABLE IF NOT EXISTS incidents (
            id        INTEGER PRIMARY KEY,
            heure     TEXT,
            commune   TEXT,
            sex       TEXT,
            categorie TEXT
        );

        -- Statistiques par commune
        CREATE TABLE IF NOT EXISTS stats_commune (
            commune TEXT PRIMARY KEY,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        -- Statistiques par tranche horaire
        CREATE TABLE IF NOT EXISTS stats_heure (
            tranche   TEXT PRIMARY KEY,   -- "nuit","matin","journee","soiree"
            label     TEXT,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        -- Statistiques par sexe
        CREATE TABLE IF NOT EXISTS stats_sexe (
            sex       TEXT PRIMARY KEY,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        -- Statistiques par catégorie d'âge
        CREATE TABLE IF NOT EXISTS stats_age (
            categorie TEXT PRIMARY KEY,
            nb_incidents INTEGER,
            pct_total    REAL
        );

        -- Poids de risque par facteur (calibrés sur les données)
        CREATE TABLE IF NOT EXISTS risk_weights (
            facteur TEXT PRIMARY KEY,
            poids   REAL
        );
    """)
    conn.commit()


def classify_hour(heure_str):
    """Retourne la tranche horaire à partir d'une chaîne HH:MM."""
    if not heure_str or heure_str.strip().lower() in ("non précisée", ""):
        return None
    try:
        h = int(heure_str.strip().split(":")[0])
    except ValueError:
        return None
    if h >= 20 or h < 6:
        return "nuit"
    if 6 <= h < 9:
        return "matin"
    if 9 <= h < 17:
        return "journee"
    return "soiree"  # 17–20


def load_csv(conn):
    conn.execute("DELETE FROM incidents")
    rows_inserted = 0
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute(
                "INSERT INTO incidents (id, heure, commune, sex, categorie) VALUES (?,?,?,?,?)",
                (
                    int(row["id"]),
                    row["heure"].strip(),
                    row["commune"].strip(),
                    row["sex"].strip(),
                    row["categorie"].strip(),
                ),
            )
            rows_inserted += 1
    conn.commit()
    print(f"  ✔ {rows_inserted} incidents insérés dans la table `incidents`")
    return rows_inserted


def build_stats(conn, total):
    # ── Stats par commune ──────────────────────────────────────────────────
    conn.execute("DELETE FROM stats_commune")
    conn.executescript("""
        INSERT INTO stats_commune (commune, nb_incidents, pct_total)
        SELECT commune,
               COUNT(*) AS nb,
               ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM incidents), 2)
        FROM incidents
        WHERE commune != '' AND commune != 'Non précisée'
        GROUP BY commune
        ORDER BY nb DESC;
    """)

    # ── Stats par tranche horaire ──────────────────────────────────────────
    conn.execute("DELETE FROM stats_heure")
    # On insère tranche par tranche en Python car SQLite n'a pas de parse HH:MM natif
    tranches = {"nuit": 0, "matin": 0, "journee": 0, "soiree": 0}
    labels   = {
        "nuit":    "Nuit (20h–6h)",
        "matin":   "Matin (6h–9h)",
        "journee": "Journée (9h–17h)",
        "soiree":  "Soirée (17h–20h)",
    }
    for (heure,) in conn.execute("SELECT heure FROM incidents").fetchall():
        t = classify_hour(heure)
        if t:
            tranches[t] += 1
    for t, nb in tranches.items():
        conn.execute(
            "INSERT OR REPLACE INTO stats_heure VALUES (?,?,?,?)",
            (t, labels[t], nb, round(nb * 100.0 / total, 2)),
        )

    # ── Stats par sexe (on exclut "Non précisé" et "Multiple") ────────────
    conn.execute("DELETE FROM stats_sexe")
    conn.executescript("""
        INSERT INTO stats_sexe (sex, nb_incidents, pct_total)
        SELECT sex,
               COUNT(*) AS nb,
               ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM incidents), 2)
        FROM incidents
        WHERE sex NOT IN ('Non précisé','')
        GROUP BY sex;
    """)

    # ── Stats par âge ──────────────────────────────────────────────────────
    conn.execute("DELETE FROM stats_age")
    conn.executescript("""
        INSERT INTO stats_age (categorie, nb_incidents, pct_total)
        SELECT categorie,
               COUNT(*) AS nb,
               ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM incidents), 2)
        FROM incidents
        WHERE categorie NOT IN ('Non précisé','')
        GROUP BY categorie;
    """)

    conn.commit()
    print("  ✔ Tables de statistiques construites")


def set_risk_weights(conn):
    """Poids par facteur dans le calcul du score de risque (somme = 1.0)."""
    conn.execute("DELETE FROM risk_weights")
    weights = [
        ("commune", 0.30),
        ("heure",   0.30),
        ("sexe",    0.25),
        ("age",     0.15),
    ]
    conn.executemany("INSERT INTO risk_weights VALUES (?,?)", weights)
    conn.commit()
    print("  ✔ Poids de risque enregistrés")


def main():
    print(f"\n{'='*55}")
    print("  Initialisation de la base SQLite — Abidjan Sécurité")
    print(f"{'='*55}")
    print(f"  CSV  : {CSV_PATH}")
    print(f"  DB   : {DB_PATH}\n")

    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    total = load_csv(conn)
    build_stats(conn, total)
    set_risk_weights(conn)
    conn.close()

    print(f"\n  Base de données prête : {DB_PATH}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
