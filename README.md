# RisqueAbi — Abidjan Sécurité

Application d'évaluation du risque d'agression à Abidjan,
construite en Python (Flask) avec une base de données SQLite.

## Structure du projet

```
risque_abidjan/
├── init_db.py              ← Charge le CSV → SQLite
├── app.py                  ← Application Flask
├── agressions.db           ← Base SQLite (générée par init_db.py)
└── README.md
```

## Installation

```bash
pip install flask
```

## Utilisation

### Étape 1 — Initialiser la base de données
```bash
python init_db.py
```
Lit `agressions_abidjan_clean.csv` et crée `agressions.db` avec les tables :
- `incidents` — tous les incidents bruts
- `stats_commune` — comptages par commune
- `stats_heure` — comptages par tranche horaire
- `stats_sexe` — comptages par sexe
- `stats_age` — comptages par catégorie d'âge
- `risk_weights` — poids de pondération par facteur

### Étape 2 — Lancer l'application
```bash
python app.py
```
Ouvrez `http://localhost:5000` dans votre navigateur.

## API REST

| Endpoint       | Méthode | Description                          |
|----------------|---------|--------------------------------------|
| `/`            | GET     | Interface utilisateur principale     |
| `/api/risk`    | POST    | Calcul du risque (JSON)              |
| `/api/stats`   | GET     | Toutes les statistiques de la BD     |

### Exemple `/api/risk`
```json
POST /api/risk
{
  "commune": "Abobo",
  "sex": "Femme",
  "age": "Adulte",
  "heure": "21:00"
}
```
Réponse :
```json
{
  "score": 78,
  "level": "ÉLEVÉ",
  "color": "#e74c3c",
  "scores": {
    "commune": 100,
    "heure": 90,
    "sexe": 80,
    "age": 50
  }
}
```

## Calcul du risque

Score pondéré (0–100) :

| Facteur  | Poids | Source BD              |
|----------|-------|------------------------|
| Commune  | 30%   | `stats_commune`        |
| Horaire  | 30%   | `stats_heure`          |
| Sexe     | 25%   | `stats_sexe`           |
| Âge      | 15%   | `stats_age`            |

- **< 40%** → Risque FAIBLE 🟢
- **40–65%** → Risque MODÉRÉ 🟠
- **> 65%** → Risque ÉLEVÉ 🔴
