import requests
import time
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from datetime import datetime

# --- Connexion PostgreSQL ---
engine = create_engine("postgresql+psycopg2://user:password@db:5432/articles_db")

# --- Création de la table si elle n'existe pas ---
with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS ai_articles (
            id SERIAL PRIMARY KEY,
            title TEXT UNIQUE,
            description TEXT,
            url TEXT,
            published_at TIMESTAMP,
            authors TEXT,
            source TEXT
        );
    """))

# --- Configuration de l’API NewsData.io ---
API_KEY = "pub_debb7bc829234a19bff47cdcc32554eb"
BASE_URL = "https://newsdata.io/api/1/news"
params = {
    "apikey": API_KEY,
    "q": "artificial intelligence",
    "language": "en,fr"
}

# --- Extraction auteur ---
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

# --- Vérification pertinence IA ---
def is_ai_related(article):
    text_content = f"{article.get('title','')} {article.get('description','')}".lower()
    keywords = [
        "artificial intelligence", " ai ", "machine learning", "deep learning",
        "neural network", "generative ai", "chatgpt", "openai", "llm"
    ]
    return any(kw in text_content for kw in keywords)

# --- Normalisation du titre ---
def normalize_title(title):
    return "".join(ch.lower() for ch in (title or "") if ch.isalnum() or ch.isspace()).strip()

# --- Insertion / mise à jour intelligente ---
def upsert_article(article):
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT published_at FROM ai_articles WHERE title = :title"),
            {"title": article["title"]}
        ).fetchone()

        if existing:
            old_date = existing[0]
            new_date = article["published_at"]
            if new_date and (old_date is None or new_date > old_date):
                conn.execute(text("""
                    UPDATE ai_articles
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
                INSERT INTO ai_articles (title, url, description, published_at, authors, source)
                VALUES (:title, :url, :description, :published_at, :authors, :source);
            """), article)
            return True

# --- Récupération et insertion ---
seen_titles = set()
count_new = 0
MAX_NEW = 500  # Nombre maximum d'articles à ajouter par exécution

while count_new < MAX_NEW:
    for attempt in range(3):  # Jusqu'à 3 tentatives par page
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)

            # Trop de requêtes → pause et retry
            if resp.status_code == 429:
                print("⚠️ Trop de requêtes, pause de 120 secondes (limite atteinte)...")
                time.sleep(120)
                continue

            resp.raise_for_status()
            data = resp.json()
            break  # Succès → on sort de la boucle de retry

        except requests.exceptions.ReadTimeout:
            print(f"⏳ Délai dépassé (tentative {attempt+1}/3), nouvelle tentative dans 30s...")
            time.sleep(30)
        except requests.exceptions.RequestException as e:
            print(f"🌐 Erreur réseau : {e}. Nouvelle tentative dans 45s...")
            time.sleep(45)
    else:
        print("❌ Impossible de contacter l’API après 3 tentatives. Arrêt du script.")
        break

    results = data.get("results", [])
    if not results:
        print("🚫 Aucun résultat trouvé, arrêt.")
        break

    for item in results:
        if not is_ai_related(item):
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
            print(f"✅ Nouveau article ({count_new}/{MAX_NEW}): {title[:80]}")

        if count_new >= MAX_NEW:
            break

    next_page = data.get("nextPage")
    if next_page:
        params["page"] = next_page
        print("➡️ Passage à la page suivante...")
        time.sleep(10)  # Pause plus longue pour éviter les limites
    else:
        print("🏁 Plus de pages disponibles.")
        break

print(f"🎉 {count_new} nouveaux articles ajoutés à la base PostgreSQL.")
