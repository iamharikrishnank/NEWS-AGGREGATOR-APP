#!/usr/bin/python
# -*- coding: utf-8 -*-

import re
import html
import logging
import requests
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup as BSoup
from django.db.models import Q
from django.shortcuts import render
from news.models import Headline, Malayalam_Headline, Search, Users

requests.packages.urllib3.disable_warnings()

logger = logging.getLogger(__name__)

THE_HINDU_BASE = "https://www.thehindu.com"


# -------------------------------------------------------------------
# Helper: HTTP session
# -------------------------------------------------------------------

def _get_session():
    """Return a requests session with a realistic User-Agent and retry."""
    session = requests.Session()
    session.headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    adapter = requests.adapters.HTTPAdapter(max_retries=2)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# -------------------------------------------------------------------
# ENGLISH via THE HINDU RSS
# language = 1 (English)
# category:
#   1 = News (main /news/)
#   2 = India / National
#   3 = Movies / Entertainment
#   4 = Technology
#   5 = Sports
# ONLY SAVE ITEMS THAT HAVE AN IMAGE
# -------------------------------------------------------------------

def _scrape_thehindu_rss(feed_url, language, category_id):
    """
    Scrape a The Hindu RSS feed and save items into Headline.
    Only save items that have an image (media:content or enclosure).
    """
    session = _get_session()
    try:
        response = session.get(feed_url, timeout=10, verify=False)
    except Exception as e:
        logger.warning("The Hindu RSS request failed for %s: %s", feed_url, e)
        return

    logger.info("The Hindu RSS status: %s  URL: %s", response.status_code, feed_url)
    if response.status_code != 200:
        return

    soup = BSoup(response.content, "xml")
    items = soup.find_all("item")
    logger.info("The Hindu RSS: %s -> %d items", feed_url, len(items))

    today = date.today()

    for item in items:
        title_tag = item.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue

        link_tag = item.find("link")
        link = link_tag.get_text(strip=True) if link_tag else ""
        if not link:
            continue

        # Description
        desc_tag = item.find("description")
        description_html = desc_tag.get_text() if desc_tag else ""
        description_html = html.unescape(description_html)
        content_text = BSoup(description_html, "html.parser").get_text(" ", strip=True)

        # Image (must exist)
        image_src = None
        media_tag = item.find("media:content")
        if media_tag and media_tag.get("url"):
            image_src = media_tag["url"]
        if not image_src:
            enclosure = item.find("enclosure")
            if enclosure and enclosure.get("url"):
                image_src = enclosure["url"]

        # STRICT: skip if no image
        if not image_src:
            logger.debug("Skipping EN (no image): %s", title)
            continue

        logger.debug("TH RSS Title: %s", title)
        logger.debug("TH RSS Link : %s", link)
        logger.debug("TH RSS Image: %s", image_src)

        exists = Headline.objects.filter(
            title=title,
            language=language,
            category=category_id,
            date=today,
        ).exists()
        if exists:
            continue

        Headline.objects.create(
            title=title,
            url=link,
            language=language,
            category=category_id,
            image=image_src,
            content=content_text,
            date=today,
        )


# -------------------------------------------------------------------
# MALAYALAM via TwentyFourNews
# language = 2 (Malayalam)
# category mapping:
#   1 = Trending (https://www.twentyfournews.com/news)
#   2 = India    (https://www.twentyfournews.com/news/national)
#   3 = Movies   (https://www.twentyfournews.com/entertainment)
#   4 = Tech     (https://www.twentyfournews.com/tech)
#   5 = Sports   (https://www.twentyfournews.com/sports)
# ONLY ARTICLES WITH IMAGES ARE SAVED
# -------------------------------------------------------------------

_MALAYALAM_CHAR_RE = re.compile(r"[\u0D00-\u0D7F]")

_TWENTYFOUR_BASE = "https://www.twentyfournews.com"


def _normalize_24news_url(href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return ""
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = _TWENTYFOUR_BASE + href
    return href


def _resolve_relative_image(img_url: str) -> str:
    """Resolve protocol-relative and path-relative image URLs."""
    if not img_url:
        return ""
    img_url = img_url.strip()
    if img_url.startswith("//"):
        return "https:" + img_url
    if img_url.startswith("/"):
        return _TWENTYFOUR_BASE + img_url
    return img_url


def _fetch_24news_article_image(url: str, session: requests.Session) -> str:
    """
    Fetch article page and try to get image from og:image / twitter:image / first <img>.
    """
    try:
        resp = session.get(url, verify=False, timeout=10)
    except Exception as e:
        logger.warning("24NEWS article image request error: %s  URL: %s", e, url)
        return None

    if resp.status_code != 200:
        logger.warning("24NEWS article status %s for image  URL: %s", resp.status_code, url)
        return None

    soup = BSoup(resp.text, "html.parser")

    # Open Graph image
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return _resolve_relative_image(og["content"])

    # Twitter image fallback
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return _resolve_relative_image(tw["content"])

    # Last resort: any img in article
    article = soup.find("article")
    img_tag = (article or soup).find("img")

    if img_tag:
        img_url = (
            img_tag.get("data-src")
            or img_tag.get("data-original")
            or img_tag.get("src")
        )
        if img_url:
            return _resolve_relative_image(img_url)

    return None


def _scrape_24news_section(section_url: str, category_id: int):
    """
    Scrape a TwentyFourNews Malayalam section page.
    For each Malayalam article link, also open the article page
    to fetch a reliable image from og:image,
    and SKIP any articles that have no image.
    """
    logger.info("SCRAPING 24NEWS → %s", section_url)

    session = _get_session()

    try:
        response = session.get(section_url, verify=False, timeout=10)
    except Exception as e:
        logger.warning("24NEWS request error: %s", e)
        return

    logger.info("24NEWS status: %s", response.status_code)
    if response.status_code != 200:
        return

    soup = BSoup(response.text, "html.parser")

    # Generic strategy: scan all <a> with Malayalam text
    all_links = soup.find_all("a", href=True)

    today = date.today()
    seen = set()
    count = 0

    for a in all_links:
        raw_href = a["href"]
        href = _normalize_24news_url(raw_href)
        if not href:
            continue

        if "twentyfournews.com" not in href:
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        # require Malayalam characters in title
        if not _MALAYALAM_CHAR_RE.search(title):
            continue

        if href in seen:
            continue
        seen.add(href)

        # fetch image from article page (og:image)
        image_src = _fetch_24news_article_image(href, session)

        # STRICT: skip if NO image
        if not image_src:
            logger.debug("Skipping ML (no image): %s", title)
            continue

        logger.debug("24N link : %s", href)
        logger.debug("24N title: %s", title)
        logger.debug("24N img  : %s", image_src)
        logger.debug("24N cat  : %s", category_id)

        exists = Headline.objects.filter(
            title=title,
            url=href,
            language=2,
            date=today,
        ).exists()
        if exists:
            continue

        Headline.objects.create(
            title=title,
            url=href,
            language=2,
            category=category_id,
            image=image_src,
            content="",
            date=today,
        )
        count += 1

    logger.info("24NEWS added WITH images only: %d", count)


# Malayalam section scrapers (thin wrappers)

_MALAYALAM_SECTIONS = {
    1: ("https://www.twentyfournews.com/news", "Trending"),
    2: ("https://www.twentyfournews.com/news/national", "India"),
    3: ("https://www.twentyfournews.com/entertainment", "Movies"),
    4: ("https://www.twentyfournews.com/tech", "Tech"),
    5: ("https://www.twentyfournews.com/sports", "Sports"),
}


def _scrape_malayalam_category(category_id: int):
    url, label = _MALAYALAM_SECTIONS[category_id]
    logger.info("Scraping Malayalam %s...", label)
    _scrape_24news_section(url, category_id)


def _scrape_all_malayalam():
    for cat_id in _MALAYALAM_SECTIONS:
        _scrape_malayalam_category(cat_id)


# -------------------------------------------------------------------
# Scraping chains (entry points)
# -------------------------------------------------------------------

def scrape_malayalam(request):
    """
    Malayalam scraping chain using TwentyFourNews sections.
    After Malayalam, continues English category scraping.
    """
    logger.info("Scraping Malayalam from TwentyFourNews...")
    _scrape_all_malayalam()
    return english_india_scrape(request)


def english_india_scrape(request):
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/news/national/?service=rss",
        language=1,
        category_id=2,
    )
    return english_tech_scrape(request)


def english_tech_scrape(request):
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/sci-tech/technology/?service=rss",
        language=1,
        category_id=4,
    )
    return english_sports_scrape(request)


def english_sports_scrape(request):
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/sport/?service=rss",
        language=1,
        category_id=5,
    )
    return english_movie_scrape(request)


def english_movie_scrape(request):
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/entertainment/movies/?service=rss",
        language=1,
        category_id=3,
    )
    return news_list(request)


def scrape(request):
    """
    Main root scraper (mapped to ""):

      - English main (The Hindu /news/)
      - Malayalam sections (TwentyFourNews)
      - English sub categories
    """
    date_english = date.today()

    headline_existing = Headline.objects.all()
    check_date = Headline.objects.filter(
        date=date_english, language=1, category=1
    ).exists()
    logger.info("headline_existing: %s", bool(headline_existing))
    logger.info("check_date: %s", check_date)

    if headline_existing and check_date:
        logger.info("DB not empty and today's EN main data exists")
        return news_list(request)

    logger.info("Scraping fresh EN main + Malayalam + EN categories")

    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/news/?service=rss",
        language=1,
        category_id=1,
    )

    return scrape_malayalam(request)


# -------------------------------------------------------------------
# Auth / simple views
# -------------------------------------------------------------------

def login(request):
    """
    Login using Users model (name/password) and show news if valid.
    """
    # If it's a GET request, just show the login/signup page
    if request.method == "GET":
        return render(request, "news/index.html")

    # POST: process the login form
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "").strip()

    if not username or not password:
        context = {"login_error": "Please enter both username and password."}
        return render(request, "news/index.html", context)

    # Only store username in session (never the password)
    request.session["username"] = username

    # Try to find a matching user
    user = Users.objects.filter(name=username, password=password).first()

    if user:
        user_language = user.language
        headlines = Headline.objects.all().order_by("-id")
        date_today = date.today()
        context = {
            "object_list": headlines,
            "user_language": user_language,
            "date_today": date_today,
        }
        return render(request, "news/user_view.html", context)

    # Login failed → show page again with error
    context = {"login_error": "Invalid username or password."}
    return render(request, "news/index.html", context)


# -------------------------------------------------------------------
# Shared category-view helpers
# -------------------------------------------------------------------

_MALAYALAM_TEMPLATES = {
    None: "news/home_malayalam.html",
    1: "news/home_malayalam.html",
    2: "news/home_malayalam_india.html",
    3: "news/home_malayalam_movie.html",
    4: "news/home_malayalam_tech.html",
    5: "news/home_malayalam_sports.html",
}

_ENGLISH_TEMPLATES = {
    None: "news/home_english.html",
    2: "news/english_india.html",
    3: "news/home_english_movie.html",
    4: "news/home_english_tech.html",
    5: "news/home_english_sports.html",
}


def _category_view(request, language, category_id, template, scraper_fn=None):
    """
    Generic category view: filter headlines by language/category/date,
    optionally trigger scraper_fn if no results exist yet.
    """
    date_today = date.today()

    filters = {"date": date_today, "language": language}
    if category_id is not None:
        filters["category"] = category_id

    if scraper_fn and not Headline.objects.filter(**filters).exists():
        logger.info("No headlines for lang=%s cat=%s → scraping...", language, category_id)
        scraper_fn()

    headlines = Headline.objects.filter(**filters).order_by("-id")
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, template, context)


# -------------------------------------------------------------------
# Malayalam views (TwentyFourNews-backed)
# -------------------------------------------------------------------

def malayalam_login(request):
    """Malayalam home (Trending/all): all Malayalam for today."""
    return _category_view(
        request, language=2, category_id=None,
        template=_MALAYALAM_TEMPLATES[None],
        scraper_fn=_scrape_all_malayalam,
    )


def malayalam_india_login(request):
    """Malayalam India page: category = 2."""
    return _category_view(
        request, language=2, category_id=2,
        template=_MALAYALAM_TEMPLATES[2],
        scraper_fn=lambda: _scrape_malayalam_category(2),
    )


def malayalam_movie_login(request):
    """Malayalam Movies page: category = 3."""
    return _category_view(
        request, language=2, category_id=3,
        template=_MALAYALAM_TEMPLATES[3],
        scraper_fn=lambda: _scrape_malayalam_category(3),
    )


def malayalam_tech_login(request):
    """Malayalam Tech page: category = 4."""
    return _category_view(
        request, language=2, category_id=4,
        template=_MALAYALAM_TEMPLATES[4],
        scraper_fn=lambda: _scrape_malayalam_category(4),
    )


def malayalam_sports_login(request):
    """Malayalam Sports page: category = 5."""
    return _category_view(
        request, language=2, category_id=5,
        template=_MALAYALAM_TEMPLATES[5],
        scraper_fn=lambda: _scrape_malayalam_category(5),
    )


# -------------------------------------------------------------------
# English views
# -------------------------------------------------------------------

def english_login(request):
    """
    English home (News/Trending).
    If no English news for today, trigger full scrape().
    """
    date_today = date.today()
    if not Headline.objects.filter(date=date_today, language=1).exists():
        return scrape(request)

    headlines = Headline.objects.filter(date=date_today, language=1).order_by("-id")
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english.html", context)


def english_tech_login(request):
    return _category_view(
        request, language=1, category_id=4,
        template=_ENGLISH_TEMPLATES[4],
    )


def english_sports_login(request):
    return _category_view(
        request, language=1, category_id=5,
        template=_ENGLISH_TEMPLATES[5],
    )


def english_movie_login(request):
    return _category_view(
        request, language=1, category_id=3,
        template=_ENGLISH_TEMPLATES[3],
    )


def news_list(request):
    headlines = Headline.objects.all().order_by("-id")
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english.html", context)


def account(request):
    return render(request, "news/index_register.html")


# -------------------------------------------------------------------
# Search (uses Django ORM filtering instead of Python loops)
# -------------------------------------------------------------------

def search(request):
    headlines = Headline.objects.all().order_by("-id")
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/search.html", context)


def search_news(request):
    """
    Filter headlines via Django ORM and bulk-create Search results.
    """
    Search.objects.all().delete()

    search_lang = request.POST.get("search_lang", "")
    search_category = request.POST.get("search_category", "")
    search_title = request.POST.get("search_title", "")
    search_date = request.POST.get("search_date", "")

    filters = {}
    if search_lang:
        filters["language"] = search_lang
    if search_category:
        filters["category"] = search_category
    if search_date:
        filters["date"] = search_date

    qs = Headline.objects.filter(**filters)

    if search_title:
        qs = qs.filter(title__icontains=search_title)

    Search.objects.bulk_create([
        Search(
            title=h.title,
            url=h.url,
            language=h.language,
            category=h.category,
            image=h.image,
            content=h.content,
        )
        for h in qs
    ])

    return search_view(request)


def search_view(request):
    headlines = Headline.objects.all().order_by("-id")
    object_search = Search.objects.all()

    context = {
        "object_list": headlines,
        "object_search": object_search,
    }
    return render(request, "news/search_news.html", context)


# -------------------------------------------------------------------
# Register / Logout / English India view
# -------------------------------------------------------------------

def register(request):
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "")
    language = request.POST.get("language")

    if not name or not email or not password:
        return render(request, "news/index_register.html")

    request.session["name"] = name
    request.session["email"] = email

    # Check for duplicate user via ORM instead of loading all users
    if Users.objects.filter(Q(name=name) | Q(email=email)).exists():
        return render(request, "news/index_register.html")

    Users.objects.create(
        name=name,
        email=email,
        password=password,
        language=language,
    )
    return render(request, "news/index.html")


def logout(request):
    request.session.flush()
    return render(request, "news/index.html")


def english_india(request):
    """
    English India/National page.
    If there is no India news for today, trigger english_india_scrape().
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=1, category=2).exists():
        return english_india_scrape(request)

    return _category_view(
        request, language=1, category_id=2,
        template=_ENGLISH_TEMPLATES[2],
    )
