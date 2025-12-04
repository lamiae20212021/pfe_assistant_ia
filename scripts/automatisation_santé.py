import requests
import time
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from datetime import datetime

# ===============================
# 🔗 Connexion PostgreSQL
# ===============================
engine = create_engine("postgresql+psycopg2://user:password@db:5432/articles_db")

# ===============================
# 🗃️ Création de la table si besoin
# ===============================
with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS health_articles (
            id SERIAL PRIMARY KEY,
            title TEXT UNIQUE,
            description TEXT,
            url TEXT,
            published_at TIMESTAMP,
            authors TEXT,
            source TEXT
        );
    """))

# ===============================
# 🌐 Configuration API NewsData.io
# ===============================
API_KEY = "pub_4f08086a9b344946852dfff10c85ceed"
BASE_URL = "https://newsdata.io/api/1/news"

# On sépare les langues : une requête pour l'anglais, une pour le français
queries = [
    {
        "apikey": API_KEY,
        "q": "health OR medicine OR healthcare OR hospital OR disease OR nutrition OR wellness OR mental health",
        "language": "en"
    },
    {
        "apikey": API_KEY,
        "q": "sante OR medecine OR hopital OR maladie OR bien-etre OR vaccination OR docteur",
        "language": "fr"
    }
]

# ===============================
# 👤 Extraction de l’auteur
# ===============================
def extract_author(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            return meta_author["content"].strip()
    except Exception:
        return None
    return None

# ===============================
# 🧠 Vérification pertinence santé
# ===============================
def is_health_related(article):
    text_content = f"{article.get('title','')} {article.get('description','')}".lower()
    keywords = [
        "health", "medicine", "medical", "doctor", "hospital",
        "patient", "disease", "virus", "nutrition", "mental health",
        "public health", "therapy", "vaccine", "covid", "cancer",
        "sante", "medecine", "hopital", "maladie", "bien-etre", "docteur"
    ]
    return any(kw in text_content for kw in keywords)

# ===============================
# 🧹 Normalisation du titre
# ===============================
def normalize_title(title):
    return "".join(ch.lower() for ch in (title or "") if ch.isalnum() or ch.isspace()).strip()

# ===============================
# 💾 Insertion / mise à jour
# ===============================
def upsert_article(article):
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT published_at FROM health_articles WHERE title = :title"),
            {"title": article["title"]}
        ).fetchone()

        if existing:
            old_date = existing[0]
            new_date = article["published_at"]
            if new_date and (old_date is None or new_date > old_date):
                conn.execute(text("""
                    UPDATE health_articles
                    SET url = :url,
                        description = :description,
                        published_at = :published_at,
                        authors = :authors,
                        source = :source
                    WHERE title = :title;
                """), article)
            return False
        else:
            conn.execute(text("""
                INSERT INTO health_articles (title, url, description, published_at, authors, source)
                VALUES (:title, :url, :description, :published_at, :authors, :source);
            """), article)
            return True

# ===============================
# 🚀 Récupération et insertion
# ===============================
seen_titles = set()
count_new = 0
MAX_NEW = 500
PAGE_DELAY = 20   # pause entre les pages
REQUEST_DELAY = 5  # pause entre chaque requête API
RETRY_DELAY = 120  # pause si trop de requêtes (429)

for query in queries:  # on boucle sur les deux langues séparément
    while count_new < MAX_NEW:
        for attempt in range(3):
            try:
                resp = requests.get(BASE_URL, params=query, timeout=30)

                if resp.status_code == 429:
                    print("⚠️ Trop de requêtes, pause de 2 minutes...")
                    time.sleep(RETRY_DELAY)
                    continue

                resp.raise_for_status()
                data = resp.json()
                break

            except requests.exceptions.ReadTimeout:
                print(f"⏳ Timeout (tentative {attempt+1}/3). Nouvelle tentative dans 30s...")
                time.sleep(30)
            except requests.exceptions.RequestException as e:
                print(f"🌐 Erreur réseau : {e}. Pause de 60s avant retry...")
                time.sleep(60)
        else:
            print("❌ Impossible de contacter l’API après 3 tentatives. Arrêt.")
            break

        # Petite pause après chaque requête pour éviter de spammer l’API
        time.sleep(REQUEST_DELAY)

        results = data.get("results", [])
        if not results:
            print("🚫 Aucun résultat trouvé. Fin du script pour cette langue.")
            break

        for item in results:
            if not is_health_related(item):
                continue

            title = item.get("title", "")
            norm_title = normalize_title(title)
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)

            authors = ", ".join(item.get("creator", [])) if item.get("creator") else None
            if not authors:
                authors = extract_author(item.get("link")) or "Inconnu"

            try:
                published_at = datetime.strptime(item.get("pubDate", ""), "%Y-%m-%d %H:%M:%S")
            except Exception:
                published_at = None

            article_data = {
                "title": title,
                "url": item.get("link", ""),
                "description": item.get("description", ""),
                "published_at": published_at,
                "authors": authors,
                "source": item.get("source_id", "newsdata.io"),
            }

            if upsert_article(article_data):
                count_new += 1
                print(f"✅ Nouvel article ({count_new}/{MAX_NEW}): {title[:80]}")

            if count_new >= MAX_NEW:
                break

        next_page = data.get("nextPage")
        if next_page:
            query["page"] = next_page
            print(f"➡️ Page suivante... (pause {PAGE_DELAY}s pour éviter la surcharge)")
            time.sleep(PAGE_DELAY)
        else:
            print("🏁 Fin : plus de pages disponibles pour cette langue.")
            break

print(f"🎉 {count_new} nouveaux articles santé ajoutés à la base PostgreSQL.")
