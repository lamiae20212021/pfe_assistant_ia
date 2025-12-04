# ============================================================
# BLOC 1 — IMPORTS, CONFIG, DB, NORMALISATION, CLASSIFICATION
# ============================================================

import asyncio
import aiohttp
import traceback
import json
import re
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# ------------------------------------------------------------
# DATES (24 derniers mois)
# ------------------------------------------------------------
TODAY = datetime.utcnow().date()
SINCE_DATE = TODAY - timedelta(days=730)
SINCE_STR = SINCE_DATE.strftime("%Y-%m-%d")

print(f"📅 Fenêtre temporelle utilisée : {SINCE_DATE} → {TODAY}")

# ------------------------------------------------------------
# CONFIG PostgreSQL (même base que ton ancien script)
# ------------------------------------------------------------
DB_USER = "user"
DB_PASSWORD = "password"
DB_HOST = "localhost"   # ✔ pour exécution locale en dehors Docker
DB_PORT = 5432
DB_NAME = "articles_db"

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# ------------------------------------------------------------
# Création des tables (async, 1 requête = 1 table)
# ------------------------------------------------------------
CREATE_AI_SQL = """
CREATE TABLE IF NOT EXISTS ai_articles (
    id SERIAL PRIMARY KEY,
    title TEXT UNIQUE,
    description TEXT,
    url TEXT,
    published_at TIMESTAMP,
    authors TEXT,
    source TEXT
);
"""

CREATE_HEALTH_SQL = """
CREATE TABLE IF NOT EXISTS health_articles (
    id SERIAL PRIMARY KEY,
    title TEXT UNIQUE,
    description TEXT,
    url TEXT,
    published_at TIMESTAMP,
    authors TEXT,
    source TEXT
);
"""

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text(CREATE_AI_SQL))
        await conn.execute(text(CREATE_HEALTH_SQL))

    print("🗄 Tables IA & Santé initialisées.")


# ------------------------------------------------------------
# Normalisation de titre
# ------------------------------------------------------------
def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r"\s+", " ", t)
    return t.lower().strip()


# ------------------------------------------------------------
# Classification AI / Health
# ------------------------------------------------------------
AI_KEYWORDS = [
    "artificial intelligence", " ai ", "machine learning", "deep learning",
    "neural", "dataset", "algorithm", "model", "transformer",
    "gpt", "llm", "chatgpt", "computer vision"
]

HEALTH_KEYWORDS = [
    "health", "medical", "clinic", "patient", "disease", "cancer",
    "tumor", "therapy", "diagnosis", "infection", "virus",
    "covid", "pharma", "genetic", "immunology", "cardiology"
]

def classify_article(title, description):
    txt = f"{title or ''} {description or ''}".lower()
    has_ai = any(k in txt for k in AI_KEYWORDS)
    has_health = any(k in txt for k in HEALTH_KEYWORDS)

    if has_ai and not has_health:
        return "IA"
    if has_health and not has_ai:
        return "HEALTH"
    if has_ai and has_health:
        return "IA"  # priorité IA
    return None

# ------------------------------------------------------------
# Normalisation de titre
# ------------------------------------------------------------
def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r"\s+", " ", t)
    return t.lower().strip()

# ------------------------------------------------------------
# Classification AI / Health
# ------------------------------------------------------------
AI_KEYWORDS = [
    "artificial intelligence", " ai ", "machine learning", "deep learning",
    "neural", "dataset", "algorithm", "model", "transformer",
    "gpt", "llm", "chatgpt", "computer vision"
]

HEALTH_KEYWORDS = [
    "health", "medical", "clinic", "patient", "disease", "cancer",
    "tumor", "therapy", "diagnosis", "infection", "virus",
    "covid", "pharma", "genetic", "immunology", "cardiology"
]

def classify_article(title, description):
    txt = f"{title or ''} {description or ''}".lower()
    has_ai = any(k in txt for k in AI_KEYWORDS)
    has_health = any(k in txt for k in HEALTH_KEYWORDS)

    if has_ai and not has_health:
        return "IA"
    if has_health and not has_ai:
        return "HEALTH"
    if has_ai and has_health:
        return "IA"
    return None

# ------------------------------------------------------------
# Retry helper (anti 429 / anti timeouts)
# ------------------------------------------------------------
async def fetch_json(session, url, params=None, headers=None, timeout=20, retries=3, source_label=""):
    """
    Requête GET JSON sécurisée avec retry + timeout intégré.
    Compatible Python 3.11 (sans async_timeout).
    """
    for attempt in range(1, retries + 1):
        try:
            # Timeout natif de aiohttp
            req_timeout = aiohttp.ClientTimeout(total=timeout)

            async with session.get(url, params=params, headers=headers, timeout=req_timeout) as resp:

                # Gestion 429 rate-limit
                if resp.status == 429:
                    wait = attempt * 2
                    print(f"⚠️ {source_label} 429 → retry dans {wait}s (tentative {attempt}/{retries})")
                    await asyncio.sleep(wait)
                    continue

                # Erreur HTTP mais pas rate-limit
                if resp.status >= 400:
                    print(f"⚠️ {source_label} HTTP {resp.status} → abandon requête")
                    return None

                text = await resp.text()

                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    print(f"⚠️ {source_label} JSON invalide")
                    return None

        except asyncio.TimeoutError:
            print(f"⏳ Timeout {source_label} (tentative {attempt})")
        except Exception as e:
            print(f"⚠️ Exception {source_label}: {e}")

        await asyncio.sleep(1)

    return None

# ============================================================
# BLOC 2 — SOURCES : NEWS, SEMANTIC SCHOLAR, PUBMED,
#                    ARXIV, CROSSREF, MEDRXIV, BASE, EUROPE PMC
# ============================================================

HEADERS = {"User-Agent": "Mozilla/5.0"}


# ------------------------------------------------------------
# NewsData.io (IA uniquement)
# ------------------------------------------------------------
async def fetch_newsdata(session):
    API_KEY = "pub_3050d515960b4d77aaea99e3f731393a"
    base_url = "https://newsdata.io/api/1/news"

    params = {
        "apikey": API_KEY,
        "q": "artificial intelligence OR machine learning OR deep learning OR AI",
        "language": "en,fr"
    }

    while True:
        data = await fetch_json(session, base_url, params=params, headers=HEADERS)
        if not data:
            break

        for item in data.get("results", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue

            pub = item.get("pubDate")
            published = None
            if pub:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        published = datetime.strptime(pub, fmt)
                        break
                    except:
                        pass

            yield {
                "title": title,
                "url": item.get("link", ""),
                "description": item.get("description") or "",
                "published_at": published,
                "authors": ", ".join(item.get("creator") or []) or "Unknown",
                "source": "newsdata.io"
            }

        next_page = data.get("nextPage")
        if not next_page:
            break
        params["page"] = next_page


# ------------------------------------------------------------
# Semantic Scholar (IA)
# ------------------------------------------------------------
async def fetch_semantic_ai(session, max_results=1500):
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    query = "(artificial intelligence) OR (machine learning) OR (deep learning)"

    offset = 0
    page_size = 100
    total = 0

    while total < max_results:
        params = {
            "query": query,
            "fields": "title,authors,abstract,url,year",
            "limit": page_size,
            "offset": offset
        }

        data = await fetch_json(session, url, params=params, headers=HEADERS)
        if not data:
            break

        for p in data.get("data", []):
            title = (p.get("title") or "").strip()
            if not title:
                continue

            year = p.get("year")
            published = datetime(year, 1, 1) if isinstance(year, int) else None

            yield {
                "title": title,
                "url": p.get("url", ""),
                "description": p.get("abstract") or "",
                "published_at": published,
                "authors": ", ".join(a["name"] for a in p.get("authors", []) if a.get("name")),
                "source": "semantic_ai"
            }

            total += 1
            if total >= max_results:
                return

        offset += page_size


# ------------------------------------------------------------
# Semantic Scholar (Santé)
# ------------------------------------------------------------
async def fetch_semantic_health(session, max_results=2000):
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    query = "(medical) OR (health) OR (disease) OR (therapy)"

    offset = 0
    page_size = 100
    total = 0

    while total < max_results:
        params = {
            "query": query,
            "fields": "title,authors,abstract,url,year",
            "limit": page_size,
            "offset": offset
        }

        data = await fetch_json(session, url, params=params, headers=HEADERS)
        if not data:
            break

        for p in data.get("data", []):
            title = (p.get("title") or "").strip()
            if not title:
                continue

            year = p.get("year")
            published = datetime(year, 1, 1) if isinstance(year, int) else None

            yield {
                "title": title,
                "url": p.get("url", ""),
                "description": p.get("abstract") or "",
                "published_at": published,
                "authors": ", ".join(a["name"] for a in p.get("authors", []) if a.get("name")),
                "source": "semantic_health"
            }

            total += 1
            if total >= max_results:
                return

        offset += page_size


# ------------------------------------------------------------
# PubMed (via eFetch/eSearch)
# ------------------------------------------------------------
async def pubmed_esearch(session):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    params = {
        "db": "pubmed",
        "term": "medical OR health OR disease OR therapy",
        "retmax": 5000,
        "retmode": "json",
        "mindate": SINCE_STR,
        "maxdate": TODAY.strftime("%Y-%m-%d"),
        "datetype": "pdat",
    }

    data = await fetch_json(session, url, params=params)
    if not data:
        return []

    ids = data.get("esearchresult", {}).get("idlist", [])
    return ids


async def fetch_pubmed(session):
    ids = await pubmed_esearch(session)
    if not ids:
        return

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    # batch
    for i in range(0, len(ids), 200):
        batch = ids[i:i+200]
        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "abstract",
            "retmode": "xml"
        }

        async with session.get(fetch_url, params=params) as resp:
            if resp.status >= 400:
                continue
            xml = await resp.text()

        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)

        for art in root.findall(".//PubmedArticle"):
            title_el = art.find(".//ArticleTitle")
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()

            abstract = "\n".join(
                a.text.strip() for a in art.findall(".//AbstractText") if a.text
            )

            # date
            pub_date_el = art.find(".//PubDate")
            published = None
            if pub_date_el is not None:
                year = pub_date_el.findtext("Year")
                month = pub_date_el.findtext("Month") or "1"
                day = pub_date_el.findtext("Day") or "1"
                try:
                    published = datetime(int(year), int(month), int(day))
                except:
                    pass

            # authors
            authors = []
            for a in art.findall(".//Author"):
                n = f"{a.findtext('ForeName','')} {a.findtext('LastName','')}".strip()
                if n:
                    authors.append(n)

            yield {
                "title": title,
                "url": "",
                "description": abstract,
                "published_at": published,
                "authors": ", ".join(authors),
                "source": "pubmed"
            }


# ------------------------------------------------------------
# arXiv (IA)
# ------------------------------------------------------------
async def fetch_arxiv_ai(session, max_results=2000):
    base_url = "http://export.arxiv.org/api/query"
    start = 0
    size = 200
    query = "cat:cs.AI OR cat:cs.LG OR cat:cs.CV"

    while start < max_results:
        params = {
            "search_query": query,
            "start": start,
            "max_results": size,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        }

        async with session.get(base_url, params=params) as resp:
            if resp.status >= 400:
                break
            xml = await resp.text()

        import xml.etree.ElementTree as ET
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml)

        entries = root.findall("atom:entry", ns)
        if not entries:
            break

        for entry in entries:
            title = entry.find("atom:title", ns).text.strip()
            summary = entry.find("atom:summary", ns).text.strip()
            date_str = entry.find("atom:published", ns).text.strip()

            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except:
                published = None

            if published and published.date() < SINCE_DATE:
                return

            authors = [
                a.find("atom:name", ns).text.strip()
                for a in entry.findall("atom:author", ns)
            ]

            yield {
                "title": title,
                "url": entry.find("atom:id", ns).text.strip(),
                "description": summary,
                "published_at": published,
                "authors": ", ".join(authors),
                "source": "arxiv_ai"
            }

        start += size


# ------------------------------------------------------------
# arXiv (Santé / Bio)
# ------------------------------------------------------------
async def fetch_arxiv_health(session, max_results=2000):
    base_url = "http://export.arxiv.org/api/query"
    start = 0
    size = 200
    query = "cat:q-bio OR health OR bioinformatics"

    while start < max_results:
        params = {
            "search_query": query,
            "start": start,
            "max_results": size,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        }

        async with session.get(base_url, params=params) as resp:
            if resp.status >= 400:
                break
            xml = await resp.text()

        import xml.etree.ElementTree as ET
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml)

        entries = root.findall("atom:entry", ns)
        if not entries:
            break

        for entry in entries:
            title = entry.find("atom:title", ns).text.strip()
            summary = entry.find("atom:summary", ns).text.strip()
            date_str = entry.find("atom:published", ns).text.strip()

            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except:
                published = None

            if published and published.date() < SINCE_DATE:
                return

            authors = [
                a.find("atom:name", ns).text.strip()
                for a in entry.findall("atom:author", ns)
            ]

            yield {
                "title": title,
                "url": entry.find("atom:id", ns).text.strip(),
                "description": summary,
                "published_at": published,
                "authors": ", ".join(authors),
                "source": "arxiv_health"
            }

        start += size


# ------------------------------------------------------------
# CrossRef
# ------------------------------------------------------------
async def fetch_crossref(session, max_results=4000):
    url = "https://api.crossref.org/works"
    cursor = "*"
    count = 0

    date_filter = f"from-pub-date:{SINCE_DATE},until-pub-date:{TODAY}"

    while count < max_results:
        params = {
            "filter": date_filter,
            "cursor": cursor,
            "rows": 200,
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        items = data.get("message", {}).get("items", [])
        for it in items:
            title_list = it.get("title", [])
            if not title_list:
                continue
            title = title_list[0]

            # date
            pub = it.get("published-print") or it.get("published-online") or {}
            date = None
            if "date-parts" in pub:
                dp = pub["date-parts"][0]
                y = dp[0]
                m = dp[1] if len(dp) > 1 else 1
                d = dp[2] if len(dp) > 2 else 1
                try:
                    date = datetime(y, m, d)
                except:
                    pass

            authors = ", ".join(
                f"{a.get('given','')} {a.get('family','')}".strip()
                for a in it.get("author", [])
            )

            yield {
                "title": title,
                "url": it.get("URL", ""),
                "description": it.get("abstract", ""),
                "published_at": date,
                "authors": authors,
                "source": "crossref"
            }

            count += 1
            if count >= max_results:
                return

        cursor = data.get("message", {}).get("next-cursor")
        if not cursor:
            break


# ------------------------------------------------------------
# medRxiv (Santé)
# ------------------------------------------------------------
async def fetch_medrxiv(session, max_results=2000):
    start_date = SINCE_DATE
    end_date = TODAY
    total = 0

    while start_date <= end_date and total < max_results:
        chunk_end = min(start_date + timedelta(days=30), end_date)
        url = f"https://api.biorxiv.org/details/medrxiv/{start_date}/{chunk_end}"

        data = await fetch_json(session, url)
        if not data:
            start_date = chunk_end + timedelta(days=1)
            continue

        for it in data.get("collection", []):
            title = it.get("title")
            if not title:
                continue

            date_str = it.get("date")
            try:
                published = datetime.strptime(date_str, "%Y-%m-%d")
            except:
                published = None

            yield {
                "title": title,
                "url": it.get("link", ""),
                "description": it.get("abstract", "") or "",
                "published_at": published,
                "authors": it.get("authors", ""),
                "source": "medrxiv"
            }

            total += 1
            if total >= max_results:
                return

        start_date = chunk_end + timedelta(days=1)


# ------------------------------------------------------------
# BASE Search (IA)
# ------------------------------------------------------------
async def fetch_base(session, max_results=2000):
    url = "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi"
    offset = 0
    size = 100
    total = 0

    query = "artificial intelligence OR machine learning"

    while total < max_results:
        params = {
            "func": "Search",
            "query": query,
            "hits": size,
            "offset": offset,
            "format": "json"
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            break

        for d in docs:
            title = d.get("title")
            if not title:
                continue

            ds = d.get("date", "")
            try:
                published = datetime.strptime(ds[:10], "%Y-%m-%d")
            except:
                published = None

            yield {
                "title": title,
                "url": d.get("url", ""),
                "description": d.get("abstract", ""),
                "published_at": published,
                "authors": ", ".join(d.get("authors", [])),
                "source": "base"
            }

            total += 1
            if total >= max_results:
                return

        offset += size


# ------------------------------------------------------------
# Europe PMC
# ------------------------------------------------------------
async def fetch_europe_pmc(session, max_results=4000):
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    page = 1
    total = 0
    query = f"FIRST_PDATE:[{SINCE_DATE} TO {TODAY}]"

    while total < max_results:
        params = {
            "query": query,
            "format": "json",
            "page": page,
            "pageSize": 1000
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        hits = data.get("resultList", {}).get("result", [])
        if not hits:
            break

        for it in hits:
            title = it.get("title")
            if not title:
                continue

            pub = it.get("firstPublicationDate")
            try:
                published = datetime.strptime(pub, "%Y-%m-%d")
            except:
                published = None

            url_ = ""
            full_list = it.get("fullTextUrlList", {}).get("fullTextUrl", [])
            if full_list and isinstance(full_list, list):
                url_ = full_list[0].get("url", "")

            yield {
                "title": title,
                "url": url_,
                "description": it.get("abstractText", ""),
                "published_at": published,
                "authors": it.get("authorString", ""),
                "source": "europe_pmc"
            }

            total += 1
            if total >= max_results:
                return

        page += 1



# ============================================================
# BLOC 3 — SOURCES : DOAJ, OPENALEX, PMC OA, CLINICALTRIALS,
#                   WHO IRIS, PLOS, ELIFE, CORE, OPENAIRE
# ============================================================

# ------------------------------------------------------------
# DOAJ (Open Access Journals)
# ------------------------------------------------------------
async def fetch_doaj(session, max_results=3000):
    base_url = "https://doaj.org/api/v2/search/articles/"
    page = 1
    total = 0

    query = f"created_date:[{SINCE_DATE} TO {TODAY}]"

    while total < max_results:
        params = {
            "page": page,
            "pageSize": 100,
            "q": query
        }

        data = await fetch_json(session, base_url, params=params)
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        for it in results:
            bib = it.get("bibjson", {})
            title = bib.get("title")
            if not title:
                continue

            date_str = bib.get("year")
            try:
                published = datetime(int(date_str), 1, 1) if date_str else None
            except:
                published = None

            links = bib.get("link", [])
            url_ = links[0].get("url", "") if links else ""

            yield {
                "title": title,
                "url": url_,
                "description": bib.get("abstract", "") or "",
                "published_at": published,
                "authors": ", ".join(a.get("name", "") for a in bib.get("author", [])),
                "source": "doaj"
            }

            total += 1
            if total >= max_results:
                return

        page += 1


# ------------------------------------------------------------
# OpenAlex
# ------------------------------------------------------------
async def fetch_openalex(session, max_results=3000):
    url = "https://api.openalex.org/works"
    cursor = "*"
    total = 0

    filt = f"from_publication_date:{SINCE_DATE},to_publication_date:{TODAY}"

    while total < max_results:
        params = {
            "filter": filt,
            "cursor": cursor,
            "per_page": 200
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        for it in results:
            title = it.get("title")
            if not title:
                continue

            date_str = it.get("publication_date")
            try:
                published = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None
            except:
                published = None

            authors = []
            for a in it.get("authorships", []):
                disp = a.get("author", {}).get("display_name") or ""
                if disp:
                    authors.append(disp)

            yield {
                "title": title,
                "url": it.get("id", ""),
                "description": it.get("abstract", "") or "",
                "published_at": published,
                "authors": ", ".join(authors),
                "source": "openalex"
            }

            total += 1
            if total >= max_results:
                return

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break


# ------------------------------------------------------------
# Europe PMC OA subset only (PMC Open Access)
# ------------------------------------------------------------
async def fetch_pmc(session, max_results=3000):
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    page = 1
    total = 0

    query = f"(OPEN_ACCESS:Y) AND (SRC:PMC) AND FIRST_PDATE:[{SINCE_DATE} TO {TODAY}]"

    while total < max_results:
        params = {
            "query": query,
            "format": "json",
            "page": page,
            "pageSize": 1000
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        hits = data.get("resultList", {}).get("result", [])
        if not hits:
            break

        for it in hits:
            title = it.get("title")
            if not title:
                continue

            pubdate = it.get("firstPublicationDate")
            try:
                published = datetime.strptime(pubdate, "%Y-%m-%d") if pubdate else None
            except:
                published = None

            yield {
                "title": title,
                "url": it.get("pmcid", ""),
                "description": it.get("abstractText", ""),
                "published_at": published,
                "authors": it.get("authorString", ""),
                "source": "pmc"
            }

            total += 1
            if total >= max_results:
                return

        page += 1


# ------------------------------------------------------------
# ClinicalTrials.gov
# ------------------------------------------------------------
async def fetch_clinical_trials(session, max_results=2000):
    url = "https://clinicaltrials.gov/api/v2/studies"
    page_token = None
    total = 0

    while total < max_results:
        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        studies = data.get("studies", [])
        if not studies:
            break

        for st in studies:
            ident = st.get("protocolSection", {}).get("identificationModule", {})
            status = st.get("protocolSection", {}).get("statusModule", {})
            desc = st.get("protocolSection", {}).get("descriptionModule", {})

            title = ident.get("officialTitle")
            if not title:
                continue

            date_str = status.get("lastUpdatePostedDate")
            try:
                published = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None
            except:
                published = None

            yield {
                "title": title,
                "url": ident.get("nctId", ""),
                "description": desc.get("briefSummary", ""),
                "published_at": published,
                "authors": "ClinicalTrial.gov",
                "source": "clinical_trials"
            }

            total += 1
            if total >= max_results:
                return

        page_token = data.get("nextPageToken")
        if not page_token:
            break


# ------------------------------------------------------------
# WHO IRIS (attention : contenu non-standard → extraction JSON safe)
# ------------------------------------------------------------
async def fetch_who_iris(session, max_results=2000):
    url = "https://iris.who.int/discover-search"
    page = 0
    total = 0

    while total < max_results:
        params = {"query": "", "page": page}

        # On récupère le texte brut et on tente JSON
        async with session.get(url, params=params) as resp:
            if resp.status >= 400:
                break
            raw = await resp.text()

        try:
            data = json.loads(raw)
        except:
            print("⚠️ WHO IRIS : contenu non JSON → on arrête cette source.")
            return

        results = data.get("results", [])
        if not results:
            break

        for it in results:
            title = it.get("dc.title")
            if not title:
                continue

            date_str = it.get("dc.date.issued")
            try:
                published = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None
            except:
                published = None

            yield {
                "title": title,
                "url": it.get("isShownAt", ""),
                "description": it.get("dc.description", ""),
                "published_at": published,
                "authors": it.get("dc.contributor.author", ""),
                "source": "who_iris"
            }

            total += 1
            if total >= max_results:
                return

        page += 1


# ------------------------------------------------------------
# PLOS API
# ------------------------------------------------------------
async def fetch_plos(session, max_results=2000):
    url = "https://api.plos.org/search"
    start = 0
    size = 100
    total = 0

    query = f"publication_date:[{SINCE_DATE} TO {TODAY}]"

    while total < max_results:
        params = {
            "q": query,
            "start": start,
            "rows": size
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        docs = data.get("response", {}).get("docs", [])
        if not docs:
            break

        for d in docs:
            title = d.get("title_display")
            if not title:
                continue

            date_str = d.get("publication_date")
            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d") if date_str else None
            except:
                published = None

            abstract = ""
            if isinstance(d.get("abstract"), list) and d.get("abstract"):
                abstract = d.get("abstract")[0]

            yield {
                "title": title,
                "url": d.get("id", ""),
                "description": abstract,
                "published_at": published,
                "authors": ", ".join(d.get("author_display", [])),
                "source": "plos"
            }

            total += 1
            if total >= max_results:
                return

        start += size


# ------------------------------------------------------------
# eLife
# ------------------------------------------------------------
async def fetch_elife(session, max_results=2000):
    url = "https://api.elifesciences.org/v2/articles"
    cursor = None
    total = 0

    while total < max_results:
        params = {"per-page": 100}
        if cursor:
            params["cursor"] = cursor

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        items = data.get("items", [])
        if not items:
            break

        for it in items:
            title = it.get("title")
            if not title:
                continue

            date_str = it.get("published")
            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d") if date_str else None
            except:
                published = None

            authors = ", ".join(a.get("name") for a in it.get("authors", []))

            yield {
                "title": title,
                "url": it.get("id"),
                "description": it.get("impactStatement", ""),
                "published_at": published,
                "authors": authors,
                "source": "elife"
            }

            total += 1
            if total >= max_results:
                return

        cursor = data.get("nextCursor")
        if not cursor:
            break


# ------------------------------------------------------------
# CORE.ac.uk
# ------------------------------------------------------------
async def fetch_core(session, max_results=2000):
    url = "https://core.ac.uk/api-v2/articles/search"
    offset = 0
    size = 100
    total = 0

    query = f"datePublished:[{SINCE_DATE} TO {TODAY}] AND (health OR medical)"

    while total < max_results:
        params = {
            "q": query,
            "offset": offset,
            "limit": size
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        docs = data.get("results", [])
        if not docs:
            break

        for d in docs:
            title = d.get("title")
            if not title:
                continue

            date_str = d.get("publishedDate")
            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d") if date_str else None
            except:
                published = None

            yield {
                "title": title,
                "url": d.get("fullTextLink", ""),
                "description": d.get("description", ""),
                "published_at": published,
                "authors": "",
                "source": "core"
            }

            total += 1
            if total >= max_results:
                return

        offset += size


# ------------------------------------------------------------
# OpenAIRE
# ------------------------------------------------------------
async def fetch_openaire(session, max_results=3000):
    url = "https://api.openaire.eu/search/publications"
    page = 1
    size = 100
    total = 0

    query = f"(health OR medical OR disease) AND publicationDate:[{SINCE_DATE} TO {TODAY}]"

    while total < max_results:
        params = {
            "query": query,
            "page": page,
            "size": size,
            "format": "json"
        }

        data = await fetch_json(session, url, params=params)
        if not data:
            break

        results = data.get("response", {}).get("results", {}).get("result", [])
        if not results:
            break

        for it in results:
            md = it.get("metadata", {}).get("oaf:result", {})
            title = md.get("title", {}).get("content", "")
            if not title:
                continue

            date_str = md.get("dateofacceptance", {}).get("content", "")
            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d") if date_str else None
            except:
                published = None

            pid_list = md.get("pid", [])
            url_ = pid_list[0].get("content", "") if pid_list else ""

            yield {
                "title": title,
                "url": url_,
                "description": md.get("description", ""),
                "published_at": published,
                "authors": "",
                "source": "openaire"
            }

            total += 1
            if total >= max_results:
                return

        page += 1

#########################

# -------------------- BASE (IA) --------------------

import aiohttp
import asyncio
import json

async def safe_get_json(session, url, params=None, headers=None, timeout=20, retries=3, source_label=""):
    """
    Wrapper JSON robuste pour aiohttp.
    - Timeout natif aiohttp
    - Gestion des erreurs HTTP
    - Gestion du 429 rate-limit
    - Retry intelligent
    """
    for attempt in range(1, retries + 1):
        try:
            req_timeout = aiohttp.ClientTimeout(total=timeout)

            async with session.get(url, params=params, headers=headers, timeout=req_timeout) as resp:

                # Gestion du rate-limit
                if resp.status == 429:
                    wait = attempt * 2
                    print(f"⚠️ {source_label} 429 → retry dans {wait}s")
                    await asyncio.sleep(wait)
                    continue

                # Erreurs HTTP classiques
                if resp.status >= 400:
                    print(f"⚠️ {source_label} HTTP {resp.status} → abandon")
                    return None

                text = await resp.text()

                # Parsing JSON
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    print(f"⚠️ {source_label} JSON invalide")
                    return None

        except asyncio.TimeoutError:
            print(f"⏳ Timeout {source_label} (tentative {attempt})")

        except Exception as e:
            print(f"⚠️ Exception {source_label}: {e}")

        # attendre avant retry
        await asyncio.sleep(1)

    return None


async def fetch_base_ai(session, max_results=2000, size=100):
    """
    BASE.org (IA) – Recherche IA générale
    API : https://api.base-search.net/
    Fonctionne en JSON.
    """
    url = "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi"
    offset = 0
    total = 0

    query = "artificial intelligence OR machine learning OR deep learning"

    while total < max_results:
        params = {
            "func": "Search",
            "query": query,
            "hits": size,
            "offset": offset,
            "format": "json"
        }

        data = await safe_get_json(session, url, params=params, source_label="BASE")
        if not data:
            break

        items = data.get("response", {}).get("docs", [])
        if not items:
            break

        for item in items:
            title = item.get("title", "")
            if not title:
                continue

            # date parsing
            date_str = item.get("date", "")
            published = None
            try:
                if date_str:
                    published = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except:
                published = None

            # filtrage 24 mois
            if published and published.date() < SINCE_DATE:
                continue

            yield {
                "title": title,
                "url": item.get("url", ""),
                "description": item.get("abstract", "") or "",
                "published_at": published,
                "authors": ", ".join(item.get("authors", [])),
                "source": "base_ai"
            }

            total += 1
            if total >= max_results:
                break

        offset += size
        await asyncio.sleep(1)

# ============================================================
# BLOC 4 — PIPELINE FINAL, BATCH INSERT, CLASSIF, MAIN()
# ============================================================

# ------------------------------------------------------------
# INSERT ASYNC EN BATCH (plusieurs lignes d'un coup)
# ------------------------------------------------------------
async def insert_batch(table: str, rows: list):
    if not rows:
        return

    async with engine.begin() as conn:
        await conn.execute(
            text(f"""
                INSERT INTO {table} (title, url, description, published_at, authors, source)
                VALUES (:title, :url, :description, :published_at, :authors, :source)
                ON CONFLICT (title) DO NOTHING
            """),
            rows
        )


# ------------------------------------------------------------
# PIPELINE : on appelle chaque fetcher et on renvoie une liste globale
# ------------------------------------------------------------
async def collect_all(session):
    print("\n🚀 Début collecte de toutes les sources...")

    # Liste des sources
    sources = [
        fetch_newsdata(session),
        fetch_semantic_ai(session),
        fetch_semantic_health(session),
        fetch_pubmed(session),
        fetch_arxiv_ai(session),
        fetch_arxiv_health(session),
        fetch_crossref(session),
        fetch_medrxiv(session),
        fetch_base_ai(session),
        fetch_europe_pmc(session),
        fetch_doaj(session),
        fetch_openalex(session),
        fetch_pmc(session),
        fetch_clinical_trials(session),
        fetch_who_iris(session),
        fetch_plos(session),
        fetch_elife(session),
        fetch_core(session),
        fetch_openaire(session)
    ]

    buffer = []

    # Exécution séquentielle mais asynchrone, pour limiter les erreurs API
    for src in sources:
        try:
            async for article in src:
                buffer.append(article)
        except Exception as e:
            print(f"⚠️ Erreur source : {e}")
            traceback.print_exc()

    print(f"📦 Total articles collectés (brut) : {len(buffer)}")
    return buffer


# ------------------------------------------------------------
# CHARGER LES TITRES EXISTANTS EN BD POUR ÉVITER LES DOUBLONS
# ------------------------------------------------------------
async def load_existing_titles():
    async with engine.begin() as conn:
        ai_rows = (await conn.execute(text("SELECT title FROM ai_articles"))).fetchall()
        health_rows = (await conn.execute(text("SELECT title FROM health_articles"))).fetchall()

    existing_ai = {normalize_title(r[0]) for r in ai_rows}
    existing_health = {normalize_title(r[0]) for r in health_rows}

    print(f"📌 Déjà en BD : {len(existing_ai)} IA | {len(existing_health)} Santé")
    return existing_ai, existing_health


# ------------------------------------------------------------
# MAIN PROCESS
# ------------------------------------------------------------
async def main():
    await init_db()

    existing_ai, existing_health = await load_existing_titles()

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
    connector = aiohttp.TCPConnector(limit=20)  # limite 20 connexions simultanées

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:

        # COLLECTE
        buffer = await collect_all(session)

        # Classification & préparation batch
        ai_batch = []
        health_batch = []

        count_ai = 0
        count_health = 0

        MAX_AI = 30000
        MAX_HEALTH = 30000

        for art in buffer:
            title = art.get("title") or ""
            desc = art.get("description") or ""
            date = art.get("published_at")

            # Filtring date
            if isinstance(date, datetime) and date.date() < SINCE_DATE:
                continue

            # Classifier
            domain = classify_article(title, desc)
            if not domain:
                continue

            # Titre normalisé
            norm = normalize_title(title)

            # IA
            if domain == "IA" and count_ai < MAX_AI:
                if norm not in existing_ai:
                    existing_ai.add(norm)
                    ai_batch.append(art)
                    count_ai += 1

                    # Si batch > 500 → insert en BDD
                    if len(ai_batch) >= 500:
                        await insert_batch("ai_articles", ai_batch)
                        print(f"[IA] ▶ Batch 500 inséré ({count_ai})")
                        ai_batch = []

            # SANTÉ
            elif domain == "HEALTH" and count_health < MAX_HEALTH:
                if norm not in existing_health:
                    existing_health.add(norm)
                    health_batch.append(art)
                    count_health += 1

                    if len(health_batch) >= 500:
                        await insert_batch("health_articles", health_batch)
                        print(f"[HEALTH] ▶ Batch 500 inséré ({count_health})")
                        health_batch = []

        # INSÉRER LES BATCHE RESTANTS
        if ai_batch:
            await insert_batch("ai_articles", ai_batch)
        if health_batch:
            await insert_batch("health_articles", health_batch)

        print("\n🎉 RÉSULTAT FINAL")
        print("   → IA insérés     :", count_ai)
        print("   → Santé insérés  :", count_health)
        print("   → TOTAL insérés  :", count_ai + count_health)
        print("✅ Collecte terminée !")


# ------------------------------------------------------------
# EXECUTION SCRIPT
# ------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
