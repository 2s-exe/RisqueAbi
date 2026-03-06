"""
app.py — Application Flask : Évaluation du risque d'agression à Abidjan
Toutes les données proviennent de la base SQLite agressions.db
"""

import sqlite3
import json
import os
from flask import Flask, render_template_string, request, jsonify

DB_PATH = os.path.join(os.path.dirname(__file__), "agressions.db")

app = Flask(__name__)


# ── Helpers BD ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql, params=()):
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_one(sql, params=()):
    conn = get_db()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Calcul du risque depuis la BD ─────────────────────────────────────────────

def get_commune_score(commune):
    """Score 0–100 basé sur nb_incidents relatif au maximum dans la BD."""
    row = query_one("SELECT nb_incidents FROM stats_commune WHERE commune = ?", (commune,))
    if not row:
        return 50
    max_row = query_one("SELECT MAX(nb_incidents) AS m FROM stats_commune")
    max_val = max_row["m"] or 1
    return round(row["nb_incidents"] / max_val * 100)


def get_hour_score(heure_str):
    """Score basé sur la tranche horaire lue dans stats_heure."""
    try:
        h = int(heure_str.split(":")[0])
    except (ValueError, AttributeError):
        return 50

    if h >= 20 or h < 6:
        tranche = "nuit"
    elif 6 <= h < 9:
        tranche = "matin"
    elif 9 <= h < 17:
        tranche = "journee"
    else:
        tranche = "soiree"

    row = query_one("SELECT nb_incidents FROM stats_heure WHERE tranche = ?", (tranche,))
    max_row = query_one("SELECT MAX(nb_incidents) AS m FROM stats_heure")
    if not row or not max_row:
        return 50
    # Score brut sur les données + amplificateur nuit
    base = round(row["nb_incidents"] / max_row["m"] * 100)
    boost = {"nuit": 40, "soiree": 15, "matin": 5, "journee": 0}
    return min(100, base + boost.get(tranche, 0))


def get_sex_score(sex):
    """Femme = plus ciblée (55% des cas identifiés dans la BD)."""
    f_row = query_one("SELECT nb_incidents FROM stats_sexe WHERE sex = 'Femme'")
    h_row = query_one("SELECT nb_incidents FROM stats_sexe WHERE sex = 'Homme'")
    if not f_row or not h_row:
        return 60
    f_nb, h_nb = f_row["nb_incidents"], h_row["nb_incidents"]
    total_sh = f_nb + h_nb
    if sex == "Femme":
        return round(f_nb / total_sh * 100 + 25)   # amplification vulnérabilité
    elif sex == "Homme":
        return round(h_nb / total_sh * 100 + 10)
    return 60


def get_age_score(categorie):
    """Score basé sur la proportion d'incidents par catégorie d'âge."""
    row = query_one("SELECT nb_incidents FROM stats_age WHERE categorie = ?", (categorie,))
    max_row = query_one("SELECT MAX(nb_incidents) AS m FROM stats_age")
    if not row or not max_row:
        return 55
    base = round(row["nb_incidents"] / max_row["m"] * 100)
    # Enfants et adolescents = vulnérabilité supplémentaire
    vuln = {"Enfant": 20, "Adolescent": 15, "Adulte": 0}
    return min(100, base + vuln.get(categorie, 0))


def compute_risk(commune, sex, categorie, heure):
    """Calcule le score global pondéré à partir de la BD."""
    weights = {r["facteur"]: r["poids"] for r in query("SELECT * FROM risk_weights")}

    scores = {
        "commune": get_commune_score(commune),
        "heure":   get_hour_score(heure),
        "sexe":    get_sex_score(sex),
        "age":     get_age_score(categorie),
    }

    total = sum(weights.get(k, 0.25) * v for k, v in scores.items())
    total = round(min(100, total))

    if total < 40:
        level, color = "FAIBLE", "#2ecc71"
    elif total < 65:
        level, color = "MODÉRÉ", "#f39c12"
    else:
        level, color = "ÉLEVÉ", "#e74c3c"

    return {"score": total, "level": level, "color": color, "scores": scores}


# ── Recommandations ───────────────────────────────────────────────────────────

RECOMMENDATIONS = {
    "FAIBLE": [
        {"icon": "✅", "text": "Restez vigilant·e, même dans les zones et horaires à faible risque."},
        {"icon": "📱", "text": "Gardez votre téléphone chargé et partagez votre position avec un proche."},
        {"icon": "🚶", "text": "Privilégiez les rues animées et bien éclairées pour vos déplacements."},
        {"icon": "👀", "text": "Évitez les distractions (écouteurs, téléphone en main) dans la rue."},
    ],
    "MODÉRÉ": [
        {"icon": "⚠️", "text": "Évitez de vous déplacer seul·e dans des zones peu fréquentées."},
        {"icon": "🚕", "text": "Privilégiez les transports organisés (taxi, woro-woro de confiance)."},
        {"icon": "🤝", "text": "Déplacez-vous en groupe, surtout en soirée."},
        {"icon": "🌙", "text": "Limitez vos sorties nocturnes dans les zones à risque."},
        {"icon": "💼", "text": "Évitez d'afficher des objets de valeur (bijoux, téléphone, sac de marque)."},
    ],
    "ÉLEVÉ": [
        {"icon": "🚨", "text": "Risque élevé : limitez vos déplacements au strict nécessaire dans cette zone/créneau."},
        {"icon": "📞", "text": "Informez toujours un proche de votre destination et de votre heure de retour prévue."},
        {"icon": "🚗", "text": "Utilisez uniquement des véhicules de confiance. Évitez les déplacements à pied la nuit."},
        {"icon": "🌙", "text": "Évitez impérativement tout déplacement nocturne dans cette commune."},
        {"icon": "🔔", "text": "Mémorisez les numéros d'urgence : Police 110 / Gendarmerie 111."},
        {"icon": "👥", "text": "Ne vous déplacez jamais seul·e — accompagnez-vous de plusieurs personnes de confiance."},
    ],
}


# ── HTML Template ─────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RisqueAbi — Abidjan Sécurité</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#0a0c10; --surface:#12151c; --surface2:#1a1e28;
  --border:#252a38; --accent:#f0b429; --accent2:#e05c2a;
  --text:#e8eaf0; --muted:#6b7280;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh}
body::before{content:'';position:fixed;inset:0;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 512 512' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");pointer-events:none;z-index:9999;opacity:.4}

header{padding:1.5rem 2rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:1rem}
.logo{width:40px;height:40px;background:var(--accent);border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:'Syne',sans-serif;font-weight:800;font-size:1.2rem;color:#000;flex-shrink:0}
.htext h1{font-family:'Syne',sans-serif;font-size:1rem;font-weight:700}
.htext p{font-size:.72rem;color:var(--muted)}
.dbadge{margin-left:auto;background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:.3rem .9rem;font-size:.72rem;color:var(--muted)}
.dbadge span{color:var(--accent);font-weight:600}

.main{max-width:1000px;margin:0 auto;padding:2rem 1.5rem 4rem}
.hero{text-align:center;padding:2rem 0 1.5rem}
.hero h2{font-family:'Syne',sans-serif;font-size:clamp(1.5rem,4vw,2.4rem);font-weight:800;line-height:1.15;letter-spacing:-.02em}
.hero h2 em{font-style:normal;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{margin-top:.7rem;color:var(--muted);font-size:.85rem;max-width:480px;margin-inline:auto}

.grid{display:grid;grid-template-columns:1fr 1fr;gap:1.4rem;margin-top:1.5rem}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:1.4rem}
.card.full{grid-column:1/-1}
.ctitle{font-family:'Syne',sans-serif;font-size:.75rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:1.1rem;display:flex;align-items:center;gap:.5rem}
.ctitle::before{content:'';display:block;width:7px;height:7px;background:var(--accent);border-radius:50%}

.field{margin-bottom:1rem}
label{display:block;font-size:.78rem;font-weight:500;color:var(--muted);margin-bottom:.45rem;letter-spacing:.03em}
select,input[type=time]{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:.7rem .95rem;font-size:.88rem;font-family:'DM Sans',sans-serif;appearance:none;outline:none;transition:border-color .2s;cursor:pointer}
select:focus,input[type=time]:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(240,180,41,.1)}
select option{background:#1a1e28}
.btn{width:100%;padding:.85rem;background:var(--accent);color:#000;border:none;border-radius:12px;font-family:'Syne',sans-serif;font-size:.95rem;font-weight:700;letter-spacing:.03em;cursor:pointer;transition:transform .15s,box-shadow .15s;margin-top:.4rem}
.btn:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(240,180,41,.3)}
.btn:active{transform:translateY(0)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}

/* Gauge */
.risk-meter{display:flex;flex-direction:column;align-items:center;gap:1.2rem}
.gauge-wrap{position:relative;width:170px;height:170px}
.gauge-wrap svg{transform:rotate(-90deg)}
.gauge-bg{fill:none;stroke:var(--border);stroke-width:12}
.gauge-fill{fill:none;stroke-width:12;stroke-linecap:round;transition:stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1),stroke .4s}
.gauge-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.gauge-pct{font-family:'Syne',sans-serif;font-size:2rem;font-weight:800;line-height:1}
.gauge-lbl{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-top:.15rem}

.rbadge{display:inline-flex;align-items:center;gap:.5rem;padding:.45rem 1.1rem;border-radius:30px;font-family:'Syne',sans-serif;font-size:.8rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.rdot{width:8px;height:8px;border-radius:50%}

/* Factor bars */
.frow{display:flex;align-items:center;gap:.7rem;margin-bottom:.7rem}
.fname{font-size:.75rem;color:var(--muted);width:110px;flex-shrink:0}
.ftrack{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.fbar{height:100%;border-radius:3px;background:var(--accent);transition:width 1s cubic-bezier(.4,0,.2,1)}
.fval{font-size:.7rem;font-weight:500;width:34px;text-align:right}

/* Bar chart */
.bitem{display:flex;align-items:center;gap:.7rem;margin-bottom:.65rem}
.bname{font-size:.75rem;color:var(--muted);width:85px;flex-shrink:0}
.btrack{flex:1;height:18px;background:var(--surface2);border-radius:4px;overflow:hidden}
.bfill{height:100%;border-radius:4px;transition:width 1s cubic-bezier(.4,0,.2,1)}
.bfill.you{outline:2px solid var(--accent)}
.bcnt{font-size:.72rem;color:var(--muted);width:55px;text-align:right}
.youtag{font-size:.6rem;font-weight:700;background:var(--accent);color:#000;border-radius:3px;padding:.1rem .3rem;margin-left:.3rem;vertical-align:middle}

/* Recos */
.rlist{list-style:none}
.rlist li{display:flex;align-items:flex-start;gap:.75rem;padding:.7rem 0;border-bottom:1px solid var(--border);font-size:.82rem;line-height:1.5}
.rlist li:last-child{border-bottom:none}
.rico{width:28px;height:28px;flex-shrink:0;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:.85rem}

/* Placeholder */
.placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;height:210px;gap:.8rem}
.placeholder .icon{width:60px;height:60px;border-radius:50%;border:2px dashed var(--border);display:flex;align-items:center;justify-content:center;font-size:1.6rem}
.placeholder p{color:var(--muted);font-size:.82rem;text-align:center;line-height:1.5}

.divider{height:1px;background:var(--border);margin:.4rem 0 1rem}

/* Source note */
.srcnote{text-align:center;margin-top:2rem;font-size:.72rem;color:var(--muted)}

@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.animate{animation:fadeUp .5s ease both}
</style>
</head>
<body>
<header>
  <div class="logo">⚠</div>
  <div class="htext">
    <h1>RisqueAbi — Abidjan Sécurité</h1>
    <p>Analyse basée sur les données réelles · Base SQLite locale</p>
  </div>
  <div class="dbadge">Base : <span>{{ total_incidents }}</span> incidents</div>
</header>

<div class="main">
  <div class="hero">
    <h2>Évaluez votre <em>risque d'agression</em><br>à Abidjan</h2>
    <p>Renseignez votre profil et situation. Le score est calculé à partir de la base de données SQLite construite sur {{ total_incidents }} incidents réels.</p>
  </div>

  <div class="grid">
    <!-- Formulaire -->
    <div class="card animate">
      <div class="ctitle">Votre profil</div>
      <div class="field">
        <label>Sexe</label>
        <select id="sex">
          <option value="">— Sélectionner —</option>
          <option value="Femme">Femme</option>
          <option value="Homme">Homme</option>
        </select>
      </div>
      <div class="field">
        <label>Catégorie d'âge</label>
        <select id="age">
          <option value="">— Sélectionner —</option>
          <option value="Enfant">Enfant (moins de 12 ans)</option>
          <option value="Adolescent">Adolescent (12–17 ans)</option>
          <option value="Adulte">Adulte (18 ans et plus)</option>
        </select>
      </div>
      <div class="field">
        <label>Commune</label>
        <select id="commune">
          <option value="">— Sélectionner —</option>
          {% for row in communes %}
          <option value="{{ row.commune }}">{{ row.commune }} — {{ row.nb_incidents }} incidents</option>
          {% endfor %}
        </select>
      </div>
      <div class="field">
        <label>Heure de déplacement</label>
        <input type="time" id="heure" value="12:00">
      </div>
      <button class="btn" id="btn" onclick="calculate()">Analyser mon risque →</button>
    </div>

    <!-- Résultat -->
    <div class="card animate" id="result-card">
      <div class="ctitle">Niveau de risque</div>
      <div id="result-placeholder" class="placeholder">
        <div class="icon">📊</div>
        <p>Remplissez le formulaire<br>pour voir votre analyse</p>
      </div>
      <div id="result-content" style="display:none">
        <div class="risk-meter">
          <div class="gauge-wrap">
            <svg width="170" height="170" viewBox="0 0 170 170">
              <circle class="gauge-bg" cx="85" cy="85" r="70"/>
              <circle class="gauge-fill" id="gauge-fill" cx="85" cy="85" r="70"
                stroke-dasharray="439.82" stroke-dashoffset="439.82"/>
            </svg>
            <div class="gauge-center">
              <div class="gauge-pct" id="gauge-pct">0%</div>
              <div class="gauge-lbl">Risque</div>
            </div>
          </div>
          <div class="rbadge" id="rbadge">
            <div class="rdot" id="rdot"></div>
            <span id="rlabel">–</span>
          </div>
          <div style="width:100%">
            <div class="divider"></div>
            <div id="factors"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Graphique communes -->
    <div class="card animate" id="commune-chart-card">
      <div class="ctitle">Incidents par commune</div>
      <div id="commune-chart">
        {% set max_inc = communes[0].nb_incidents %}
        {% for row in communes %}
        <div class="bitem">
          <div class="bname" id="bname-{{ row.commune }}">{{ row.commune }}</div>
          <div class="btrack">
            <div class="bfill" id="bfill-{{ row.commune }}"
              style="width:{{ (row.nb_incidents / max_inc * 100)|int }}%;
                     background:linear-gradient(90deg,#2a2e3a,#353a4a)">
            </div>
          </div>
          <div class="bcnt">{{ row.nb_incidents }} cas</div>
        </div>
        {% endfor %}
      </div>
    </div>

    <!-- Recommandations -->
    <div class="card animate" id="reco-card" style="display:none">
      <div class="ctitle">Recommandations</div>
      <ul class="rlist" id="reco-list"></ul>
    </div>
  </div>

  <p class="srcnote">
    Données issues du fichier <code>agressions_abidjan_clean.csv</code> · 
    Stockées dans <code>agressions.db</code> (SQLite) · 
    Calcul de risque pondéré par commune (30%), heure (30%), sexe (25%), âge (15%)
  </p>
</div>

<script>
const RECOS = {{ recos | tojson }};
const CIRC  = 439.82;

async function calculate() {
  const commune = document.getElementById('commune').value;
  const sex     = document.getElementById('sex').value;
  const age     = document.getElementById('age').value;
  const heure   = document.getElementById('heure').value || '12:00';

  if (!commune || !sex || !age) {
    alert('Veuillez renseigner tous les champs.');
    return;
  }

  const btn = document.getElementById('btn');
  btn.disabled = true;
  btn.textContent = 'Calcul en cours…';

  const res  = await fetch('/api/risk', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ commune, sex, age: age, heure })
  });
  const data = await res.json();
  btn.disabled = false;
  btn.textContent = 'Analyser mon risque →';

  showResult(data, commune);
}

function showResult(data, commune) {
  document.getElementById('result-placeholder').style.display = 'none';
  const content = document.getElementById('result-content');
  content.style.display = 'block';
  content.style.animation = 'none';
  void content.offsetWidth;
  content.style.animation = 'fadeUp .5s ease both';

  // Gauge
  const offset = CIRC - (data.score / 100) * CIRC;
  const fill   = document.getElementById('gauge-fill');
  fill.style.strokeDashoffset = CIRC;
  setTimeout(() => { fill.style.strokeDashoffset = offset; }, 50);
  fill.style.stroke = data.color;

  // Counter
  const pctEl = document.getElementById('gauge-pct');
  pctEl.style.color = data.color;
  let c = 0, step = Math.ceil(data.score / 40);
  const t = setInterval(() => {
    c = Math.min(c + step, data.score);
    pctEl.textContent = c + '%';
    if (c >= data.score) clearInterval(t);
  }, 25);

  // Badge
  const badge = document.getElementById('rbadge');
  document.getElementById('rdot').style.background  = data.color;
  document.getElementById('rlabel').textContent      = 'RISQUE ' + data.level;
  badge.style.background = data.color + '22';
  badge.style.border     = `1px solid ${data.color}55`;
  badge.style.color      = data.color;

  // Factor bars
  const labels = { commune:'Commune', heure:'Horaire', sexe:'Sexe', age:'Âge' };
  const fEl    = document.getElementById('factors');
  fEl.innerHTML = '';
  for (const [k, v] of Object.entries(data.scores)) {
    const fc = v >= 70 ? '#e74c3c' : v >= 45 ? '#f39c12' : '#2ecc71';
    fEl.innerHTML += `
      <div class="frow">
        <div class="fname">${labels[k]}</div>
        <div class="ftrack"><div class="fbar" style="width:0%;background:${fc}" data-w="${v}"></div></div>
        <div class="fval" style="color:${fc}">${v}%</div>
      </div>`;
  }
  setTimeout(() => {
    document.querySelectorAll('.fbar').forEach(b => { b.style.width = b.dataset.w + '%'; });
  }, 80);

  // Highlight commune in chart
  document.querySelectorAll('.bfill').forEach(b => {
    b.style.background = 'linear-gradient(90deg,#2a2e3a,#353a4a)';
    b.classList.remove('you');
  });
  document.querySelectorAll('.bname').forEach(n => {
    const tag = n.querySelector('.youtag');
    if (tag) tag.remove();
  });
  const selFill = document.getElementById('bfill-' + commune);
  const selName = document.getElementById('bname-' + commune);
  if (selFill) {
    selFill.style.background = 'linear-gradient(90deg,var(--accent2),var(--accent))';
    selFill.classList.add('you');
  }
  if (selName) {
    selName.innerHTML += '<span class="youtag">VOUS</span>';
  }

  // Recommendations
  const recoCard = document.getElementById('reco-card');
  recoCard.style.display = 'block';
  recoCard.style.animation = 'none';
  void recoCard.offsetWidth;
  recoCard.style.animation = 'fadeUp .5s ease both';

  const list = document.getElementById('reco-list');
  const recoColor = { FAIBLE:'#1a3a2a', 'MODÉRÉ':'#3a2d1a', 'ÉLEVÉ':'#3a1a1a' };
  list.innerHTML = (RECOS[data.level] || []).map(r => `
    <li>
      <div class="rico" style="background:${recoColor[data.level]}">${r.icon}</div>
      <span>${r.text}</span>
    </li>`).join('');
}
</script>
</body>
</html>
"""


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    communes = query("SELECT commune, nb_incidents FROM stats_commune ORDER BY nb_incidents DESC")
    total    = query_one("SELECT COUNT(*) AS n FROM incidents")["n"]
    return render_template_string(
        HTML,
        communes=communes,
        total_incidents=total,
        recos=RECOMMENDATIONS,
    )


@app.route("/api/risk", methods=["POST"])
def api_risk():
    data = request.get_json()
    result = compute_risk(
        commune=data.get("commune", ""),
        sex=data.get("sex", ""),
        categorie=data.get("age", ""),
        heure=data.get("heure", "12:00"),
    )
    return jsonify(result)


@app.route("/api/stats")
def api_stats():
    """Endpoint bonus : retourne toutes les stats de la BD en JSON."""
    return jsonify({
        "total_incidents": query_one("SELECT COUNT(*) AS n FROM incidents")["n"],
        "communes":  query("SELECT * FROM stats_commune ORDER BY nb_incidents DESC"),
        "heures":    query("SELECT * FROM stats_heure ORDER BY nb_incidents DESC"),
        "sexes":     query("SELECT * FROM stats_sexe ORDER BY nb_incidents DESC"),
        "ages":      query("SELECT * FROM stats_age ORDER BY nb_incidents DESC"),
        "weights":   query("SELECT * FROM risk_weights"),
    })


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("⚠  Base de données introuvable. Lancez d'abord : python init_db.py")
    else:
        print("\n✔  Base SQLite trouvée :", DB_PATH)
        print("✔  Lancement du serveur Flask…")
        print("   → Ouvrez http://localhost:5000 dans votre navigateur\n")
    app.run(debug=True, port=5000)
