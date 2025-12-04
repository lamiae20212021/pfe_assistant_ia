import requests
import time
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import re
import unicodedata

# -------------------- CONFIG DATES (12 DERNIERS MOIS) --------------------
TODAY = datetime.utcnow().date()
SINCE_DATE = TODAY - timedelta(days=365)   # 🔥 12 mois
SINCE_STR_PUBMED = SINCE_DATE.strftime("%Y/%m/%d")
TODAY_STR_PUBMED = TODAY.strftime("%Y/%m/%d")

print(f"📅 Fenêtre temporelle utilisée : du {SINCE_DATE} au {TODAY}")

# -------------------- DB --------------------
engine = create_engine("postgresql+psycopg2://user:password@localhost:5432/articles_db")

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

# -------------------- Normalisation avancée --------------------
def normalize_title(title):
    if not title:
        return ""
    text_norm = unicodedata.normalize("NFKC", title)
    text_norm = re.sub(r"\s+", " ", text_norm)
    return text_norm.lower().strip()


# -------------------- LOAD EXISTING TITLES --------------------
with engine.connect() as conn:
    existing_ai_titles = {
        normalize_title(row[0])
        for row in conn.execute(text("SELECT title FROM ai_articles")).fetchall()
    }

with engine.connect() as conn:
    existing_health_titles = {
        normalize_title(row[0])
        for row in conn.execute(text("SELECT title FROM health_articles")).fetchall()
    }

print(f"📌 Déjà en BD → {len(existing_ai_titles)} IA | {len(existing_health_titles)} Santé")


# -------------------- CLASSIFICATION --------------------
def classify_article(title, description):
    text_ = f"{title or ''} {description or ''}".lower()

    ai_keywords = [
        "artificial intelligence"," ai ","machine learning","deep learning",
        "neural","dataset","training","algorithm","model","transformer",
        "llm","gpt","openai","chatgpt","inference","computer vision"
    ]

    health_keywords = [
        "health","medical","clinic","patient","disease","cancer","tumor",
        "diagnosis","treatment","therapy","infection","virus","covid",
        "pharma","genetic","immunology","neurology","cardiology"
    ]

    has_ai = any(k in text_ for k in ai_keywords)
    has_health = any(k in text_ for k in health_keywords)

    if has_ai and not has_health:
        return "IA"
    if has_health and not has_ai:
        return "HEALTH"
    if has_ai and has_health:
        return "IA"   # 🔥 priorité IA comme tu veux

    return None


# -------------------- UPSERT --------------------
def upsert_ai_article(article):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ai_articles (title, url, description, published_at, authors, source)
            VALUES (:title, :url, :description, :published_at, :authors, :source)
            ON CONFLICT (title) DO NOTHING
        """), article)
    return True


def upsert_health_article(article):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO health_articles (title, url, description, published_at, authors, source)
            VALUES (:title, :url, :description, :published_at, :authors, :source)
            ON CONFLICT (title) DO NOTHING
        """), article)
    return True


# -------------------- NEWS DATA (SANS DATES !) --------------------
def fetch_newsdata():
    #API_KEY = "pub_3050d515960b4d77aaea99e3f731393a"   #  clé loubna
    #API_KEY = "pub_e663dc237a1942ce98cbebe4d9aaec4b"  # clé mohammed
    API_KEY = "pub_4f08086a9b344946852dfff10c85ceed"  #clé lamiae
    url = "https://newsdata.io/api/1/news"

    params = {
        "apikey": API_KEY,
        "q": "artificial intelligence OR machine learning OR deep learning OR AI",
        "language": "en,fr"
        # ❌ pas de from_date / to_date → évite l’erreur 422
    }

    while True:
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print("⚠️ Erreur NewsData :", e)
            break

        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue

            published = None
            if item.get("pubDate"):
                try:
                    published = datetime.strptime(item["pubDate"], "%Y-%m-%d %H:%M:%S")
                except:
                    published = None

            yield {
                "title": (item.get("title") or "").strip(),
                "url": item.get("link", ""),
                "description": item.get("description") or "",
                "published_at": published,
                "authors": ", ".join(item.get("creator") or []) or "Unknown",
                "source": "newsdata.io"
            }

        if not data.get("nextPage"):
            break

        params["page"] = data["nextPage"]
        time.sleep(1)


# -------------------- SEMANTIC SCHOLAR --------------------
HEADERS = {"User-Agent": "Mozilla/5.0"}  # pour éviter 429

def fetch_semantic_ai(max_results=2000, page_size=100):
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    offset = 0
    total = 0

    query = "artificial intelligence OR machine learning OR deep learning OR neural network"

    while total < max_results:
        try:
            resp = requests.get(
                url,
                params={
                    "query": query,
                    "fields": "title,authors,abstract,url,year",
                    "limit": page_size,
                    "offset": offset
                },
                headers=HEADERS,
                timeout=30
            )
            resp.raise_for_status()
        except Exception as e:
            print("⚠️ Erreur Semantic Scholar IA :", e)
            break

        data = resp.json()

        for p in data.get("data", []):
            title = (p.get("title") or "").strip()
            if not title:
                continue

            year = p.get("year")
            published = datetime(year,1,1) if isinstance(year,int) else None

            yield {
                "title": title,
                "url": p.get("url") or "",
                "description": p.get("abstract") or "",
                "published_at": published,
                "authors": ", ".join(a["name"] for a in p.get("authors", []) if a.get("name")),
                "source": "semantic_scholar_ai"
            }

            total += 1
            if total >= max_results:
                break

        offset += page_size
        time.sleep(1)   # 🔥 éviter 429


def fetch_semantic_health(max_results=3000, page_size=100):
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    offset = 0
    total = 0

    query = "medical OR health OR disease OR cancer OR clinic OR therapy OR diagnosis"

    while total < max_results:
        try:
            resp = requests.get(
                url,
                params={
                    "query": query,
                    "fields": "title,authors,abstract,url,year",
                    "limit": page_size,
                    "offset": offset
                },
                headers=HEADERS,
                timeout=30
            )
            resp.raise_for_status()
        except Exception as e:
            print("⚠️ Erreur Semantic Scholar Santé :", e)
            break

        data = resp.json()

        for p in data.get("data", []):
            title = (p.get("title") or "").strip()
            if not title:
                continue

            year = p.get("year")
            published = datetime(year,1,1) if isinstance(year,int) else None

            yield {
                "title": title,
                "url": p.get("url") or "",
                "description": p.get("abstract") or "",
                "published_at": published,
                "authors": ", ".join(a["name"] for a in p.get("authors", []) if a.get("name")),
                "source": "semantic_scholar_health"
            }

            total += 1
            if total >= max_results:
                break

        offset += page_size
        time.sleep(1)   # 🔥 éviter 429


# -------------------- PUBMED (12 mois) --------------------
def fetch_pubmed(max_results=10000):
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    query = (
        "medical OR health OR disease OR therapy OR diagnosis OR infection OR oncology"
    )

    try:
        r = requests.get(search_url, params={
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "xml",
            "mindate": SINCE_STR_PUBMED,
            "maxdate": TODAY_STR_PUBMED,
            "datetype": "pdat"
        }, timeout=30)
        r.raise_for_status()
        ids_xml = ET.fromstring(r.text)
    except Exception as e:
        print("⚠️ Erreur PubMed esearch:", e)
        return

    pmids = [i.text for i in ids_xml.findall(".//Id")]

    batch = 200
    for i in range(0, len(pmids), batch):
        ids = pmids[i:i+batch]

        try:
            fr = requests.get(fetch_url, params={
                "db": "pubmed",
                "id": ",".join(ids),
                "rettype": "abstract",
                "retmode": "xml"
            }, timeout=60)
            fr.raise_for_status()
            root = ET.fromstring(fr.text)
        except Exception as e:
            print(f"⚠️ Erreur PubMed efetch batch {i//batch}:", e)
            continue

        for article in root.findall(".//PubmedArticle"):

            title_el = article.find(".//ArticleTitle")
            if title_el is None or not title_el.text:
                continue

            title = title_el.text.strip()

            abstract = "\n".join(
                a.text.strip() for a in article.findall(".//AbstractText") if a.text
            )

            authors = []
            for a in article.findall(".//Author"):
                name = f"{a.findtext('ForeName','')} {a.findtext('LastName','')}".strip()
                if name:
                    authors.append(name)

            published_at = None
            pub_date_el = article.find(".//PubDate")
            if pub_date_el is not None:
                year = pub_date_el.findtext("Year")
                month = pub_date_el.findtext("Month")
                day = pub_date_el.findtext("Day")
                try:
                    month_map = {
                        "Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                        "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12
                    }
                    if year:
                        y = int(year)
                        m = int(month) if month and month.isdigit() else month_map.get(month, 1)
                        d = int(day) if day and day.isdigit() else 1
                        published_at = datetime(y,m,d)
                except:
                    published_at = None

            yield {
                "title": title,
                "url": None,
                "description": abstract,
                "published_at": published_at,
                "authors": ", ".join(authors) or "Unknown",
                "source": "pubmed"
            }

        time.sleep(0.2)


# -------------------- COLLECTE & INSERT --------------------
sources = [
    fetch_newsdata(),
    fetch_semantic_ai(),
    fetch_semantic_health(),
    fetch_pubmed()
]

MAX_AI = 10000
MAX_HEALTH = 10000
count_ai = 0
count_health = 0

buffer = []
for generator in sources:
    for article in generator:
        buffer.append(article)

print(f"📦 Articles collectés avant classification : {len(buffer)}")

for article in buffer:
    title = article.get("title") or ""
    desc = article.get("description") or ""

    domain = classify_article(title, desc)
    if domain is None:
        continue

    norm = normalize_title(title)
    if not norm:
        continue

    # IA
    if domain == "IA" and count_ai < MAX_AI:
        if norm not in existing_ai_titles:
            existing_ai_titles.add(norm)
            upsert_ai_article(article)
            count_ai += 1
            print(f"[IA] ✔ {count_ai}/{MAX_AI} → {title[:80]}")

    # SANTÉ
    elif domain == "HEALTH" and count_health < MAX_HEALTH:
        if norm not in existing_health_titles:
            existing_health_titles.add(norm)
            upsert_health_article(article)
            count_health += 1
            print(f"[HEALTH] ✔ {count_health}/{MAX_HEALTH} → {title[:80]}")

    if count_ai >= MAX_AI and count_health >= MAX_HEALTH:
        break

print("\n🎉 IA insérés      :", count_ai)
print("🎉 Santé insérés   :", count_health)
print("🎉 Total insérés   :", count_ai + count_health)
