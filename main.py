import os, sqlite3, time, logging, json, asyncio, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from deep_translator import GoogleTranslator
from dotenv import load_dotenv  # ← добавили импорт

# 🔥 Загружаем .env ПЕРЕД использованием os.getenv()
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = FastAPI()

BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "news.db"
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")  # ← теперь сработает

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE, source TEXT, pub_date TEXT,
                orig_title TEXT, orig_summary TEXT,
                translations TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON news(pub_date DESC)")
        conn.commit()

def fetch_newsapi():
    if not NEWSAPI_KEY:
        logging.warning("⚠️ NEWSAPI_KEY не найден. Загрузка пропущена.")
        return
        
    logging.info("📰 Загрузка из NewsAPI (последние 7 дней)...")
    url = "https://newsapi.org/v2/everything"
    count = 0
    today = datetime.now()  

    for i in range(7):
        day = today - timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        params = {
            "q": "technology",
            "from": date_str,
            "to": date_str,
            "sortBy": "publishedAt",
            "pageSize": 50,
            "apiKey": NEWSAPI_KEY
        }
        try:
            res = requests.get(url, params=params, timeout=10)
            data = res.json()
            if data.get("status") != "ok":
                logging.warning(f"⚠️ Ошибка NewsAPI ({date_str}): {data.get('message')}")
                continue

            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                for art in data.get("articles", []):
                    link = art.get("url", "")
                    if not link or art.get("title") == "[Removed]": 
                        continue
                        
                    cursor.execute("SELECT id FROM news WHERE link=?", (link,))
                    if cursor.fetchone(): continue

                    pub_dt = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
                    pub_date = pub_dt.strftime("%Y-%m-%d")

                    cursor.execute("""
                        INSERT OR IGNORE INTO news (link, source, pub_date, orig_title, orig_summary, translations)
                        VALUES (?, ?, ?, ?, ?, '{}')
                    """, (link, art["source"]["name"], pub_date, art.get("title",""), art.get("description","") or ""))
                    count += 1
                conn.commit()
            time.sleep(1.1)  # Лимит бесплатного тарифа: ~1 запрос/сек
        except Exception as e:
            logging.error(f"❌ Ошибка запроса ({date_str}): {e}")
            
    logging.info(f"✅ NewsAPI: добавлено {count} статей.")

def translate_and_cache(lang, date):
    if lang == "en": return
    logging.info(f"🌐 Перевод на {lang} за {date}...")
    tr = GoogleTranslator(source='auto', target=lang)
    
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, orig_title, orig_summary, translations FROM news WHERE pub_date=?", (date,)).fetchall()
        
        # Собираем только те, что ещё не переведены
        uncached = []
        for r in rows:
            cache = json.loads(r["translations"] or "{}")
            if lang not in cache:
                uncached.append((r["id"], r["orig_title"], r["orig_summary"], cache))
        
        if not uncached: return

        # Переводим с минимальной задержкой и пачками
        for i, (nid, title, summary, cache) in enumerate(uncached):
            try:
                t_title = tr.translate(title)
                t_sum = tr.translate(summary) if summary.strip() else t_title
                cache[lang] = f"{t_title}|||{t_sum}"
                conn.execute("UPDATE news SET translations=? WHERE id=?", (json.dumps(cache), nid))
                
                # Фиксируем каждые 5 статей (меньше блокировок БД)
                if i % 5 == 0: conn.commit()
                time.sleep(0.1)  # Уменьшили задержку: безопасно для Google
            except Exception as e:
                logging.warning(f"⚠️ Пропуск перевода: {e}")
                cache[lang] = f"{title}|||{summary}"  # Fallback: оставляем оригинал
                conn.execute("UPDATE news SET translations=? WHERE id=?", (json.dumps(cache), nid))
                
        conn.commit()
        logging.info(f"✅ Переведено {len(uncached)} статей.")

@app.on_event("startup")
async def startup():
    init_db()
    # Загружаем новости при старте
    await asyncio.to_thread(fetch_newsapi)
    # Фоновое обновление каждые 30 минут
    async def periodic_fetch():
        while True:
            await asyncio.sleep(1800)
            await asyncio.to_thread(fetch_newsapi)
    asyncio.create_task(periodic_fetch())

@app.get("/")
def index(): return FileResponse(STATIC_DIR / "index.html")

@app.get("/refresh")
def refresh():
    fetch_newsapi()
    return {"status": "updated"}

@app.get("/api/dates")
def get_dates():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT DISTINCT pub_date FROM news ORDER BY pub_date DESC LIMIT 7").fetchall()
        return [r[0] for r in rows]

@app.get("/api/news")
def get_news(lang: str = "ru", date: str = Query("latest"), offset: int = 0, limit: int = 10):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if date == "latest":
            rows = conn.execute("""
                SELECT link, source, pub_date, orig_title, orig_summary, translations
                FROM news ORDER BY pub_date DESC, id DESC LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
        else:
            rows = conn.execute("""
                SELECT link, source, pub_date, orig_title, orig_summary, translations
                FROM news WHERE pub_date=? ORDER BY id DESC LIMIT ? OFFSET ?
            """, (date, limit, offset)).fetchall()

        # Кэшируем переводы только для конкретных дат
        if date != "latest":
            translate_and_cache(lang, date)

        result = []
        for r in rows:
            cache = json.loads(r["translations"] or "{}")
            if lang in cache:
                t, s = cache[lang].split("|||", 1)
            else:
                # Перевод на лету (для latest или если нет в кэше)
                if lang != "en":
                    try:
                        tr = GoogleTranslator(source='auto', target=lang)
                        t = tr.translate(r["orig_title"])
                        s = tr.translate(r["orig_summary"]) if r["orig_summary"] else t
                    except:
                        t, s = r["orig_title"], r["orig_summary"]
                else:
                    t, s = r["orig_title"], r["orig_summary"]
            result.append({"title": t, "summary": s, "link": r["link"], "source": r["source"], "date": r["pub_date"]})
        return result

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Конец файла — больше ничего не пишем