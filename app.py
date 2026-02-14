import os
import re
import time
import threading
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# =========================
# CONFIG (Render Ready)
# =========================

FETCH_INTERVAL_SEC = 180        # cada 3 min
WINDOW_MINUTES = 60            # ventana de viralidad
ALERT_THRESHOLD = 35           # bajo para que te mande alertas rápido
COOLDOWN_MIN = 120             # no repetir tema por 2h

# Telegram desde Render Env Vars
TELEGRAM_BOT_TOKEN = os.getenv("8376738634:AAGc2ou5MZdYi8J7IEbG8HpvSN6A4MccsrU", "").strip()
TELEGRAM_CHAT_ID = os.getenv("1743101024", "").strip()

# =========================
# RSS FUENTES (US / MUNDIAL)
# =========================

RSS_FEEDS = [
    "https://news.google.com/rss?hl=es-419&gl=US&ceid=US:es-419",
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
]

# =========================
# KEYWORDS (Temas)
# =========================

TOPIC_KEYWORDS = {
    "politica": ["trump", "biden", "election", "president", "congress", "senado"],
    "economia": ["inflation", "fed", "markets", "petróleo", "oil", "crisis"],
    "migracion": ["border", "migrant", "immigration", "frontera", "deportación"],
    "guerra": ["war", "attack", "drone", "missile", "guerra", "bombardeo"],
    "crimen": ["shooting", "arrest", "crime", "police", "tiroteo", "asesinato"],
    "farandula": ["celebrity", "hollywood", "oscars", "famoso", "escándalo"],
}

IMPACT_TERMS = {
    "breaking": 10,
    "última hora": 12,
    "urgent": 10,
    "attack": 8,
    "explosion": 9,
    "crisis": 7,
    "war": 9,
    "tiroteo": 9,
}

# =========================
# STATE (sin DB para Render)
# =========================

seen_links = set()
last_sent_topic = {}

app = FastAPI(title="Motor Viral PRO (Render + Telegram)")


# =========================
# HELPERS
# =========================

def normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-záéíóúüñ0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def detect_topic(title: str) -> str:
    t = normalize(title)
    for topic, kws in TOPIC_KEYWORDS.items():
        for kw in kws:
            if kw in t:
                return topic
    return "otros"


def impact_score(title: str) -> int:
    t = normalize(title)
    score = 0
    for term, pts in IMPACT_TERMS.items():
        if term in t:
            score += pts
    return min(score, 40)


def telegram_send(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram no configurado")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    requests.post(url, json=payload, timeout=15)


def format_alert(score, topic, title, link):
    return (
        f"🚨 ALERTA VIRAL ({topic.upper()})\n"
        f"Score: {score}/100\n\n"
        f"TITULAR:\n{title}\n\n"
        f"LINK:\n{link}\n\n"
        f"HOOK VALERIA:\nATENCIÓN EE.UU., esto se está viralizando ahora mismo…"
    )


# =========================
# ENGINE
# =========================

def fetch_news():
    alerts = []

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)

        for e in feed.entries[:25]:
            title = e.get("title", "").strip()
            link = e.get("link", "").strip()

            if not title or not link:
                continue

            if link in seen_links:
                continue

            seen_links.add(link)

            topic = detect_topic(title)
            score = impact_score(title)

            if score >= ALERT_THRESHOLD:
                alerts.append((score, topic, title, link))

    alerts.sort(reverse=True, key=lambda x: x[0])
    return alerts[:5]


def engine_loop():
    while True:
        try:
            alerts = fetch_news()
            now = time.time()

            for score, topic, title, link in alerts:
                last = last_sent_topic.get(topic, 0)

                # cooldown por tema
                if now - last < COOLDOWN_MIN * 60:
                    continue

                telegram_send(format_alert(score, topic, title, link))
                last_sent_topic[topic] = now

        except Exception as e:
            print("Engine error:", e)

        time.sleep(FETCH_INTERVAL_SEC)


@app.on_event("startup")
def startup():
    t = threading.Thread(target=engine_loop, daemon=True)
    t.start()


# =========================
# ROUTES
# =========================

@app.get("/")
def home():
    return {
        "status": "Motor Viral activo",
        "interval_sec": FETCH_INTERVAL_SEC,
        "threshold": ALERT_THRESHOLD,
        "routes": ["/", "/force_check"]
    }


@app.get("/force_check")
def force_check():
    alerts = fetch_news()
    sent = 0

    for score, topic, title, link in alerts:
        telegram_send(format_alert(score, topic, title, link))
        sent += 1

    return {"ok": True, "found": len(alerts), "sent": sent}
