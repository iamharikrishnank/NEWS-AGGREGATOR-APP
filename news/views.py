#!/usr/bin/python
# -*- coding: utf-8 -*-

import re
import html
import requests
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup as BSoup
from django.shortcuts import render
from news.models import Headline, Malayalam_Headline, Search, Users

requests.packages.urllib3.disable_warnings()

THE_HINDU_BASE = "https://www.thehindu.com"


# -------------------------------------------------------------------
# Helper: HTTP session
# -------------------------------------------------------------------

def _get_session():
    """Return a requests session with a realistic User-Agent."""
    session = requests.Session()
    session.headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
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
        print(f"The Hindu RSS request failed for {feed_url}: {e}")
        return

    print("The Hindu RSS status:", response.status_code, "URL:", feed_url)
    if response.status_code != 200:
        return

    soup = BSoup(response.content, "xml")
    items = soup.find_all("item")
    print(f"The Hindu RSS: {feed_url} -> {len(items)} items")

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
            print("Skipping EN (no image):", title)
            continue

        print("TH RSS Title:", title)
        print("TH RSS Link :", link)
        print("TH RSS Image:", image_src)

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


def _normalize_24news_url(href: str) -> str:
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return ""
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://www.twentyfournews.com" + href
    return href


def _fetch_24news_article_image(url: str, session: requests.Session) -> str:
    """
    Fetch article page and try to get image from og:image / twitter:image / first <img>.
    """
    try:
        resp = session.get(url, verify=False, timeout=10)
    except Exception as e:
        print("24NEWS article image request error:", e, "URL:", url)
        return None

    if resp.status_code != 200:
        print("24NEWS article status not 200 for image:", resp.status_code, "URL:", url)
        return None

    soup = BSoup(resp.text, "html.parser")

    # Open Graph image
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        img = og["content"].strip()
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("/"):
            img = "https://www.twentyfournews.com" + img
        return img

    # Twitter image fallback
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        img = tw["content"].strip()
        if img.startswith("//"):
            img = "https:" + img
        elif img.startswith("/"):
            img = "https://www.twentyfournews.com" + img
        return img

    # Last resort: any img in article
    article = soup.find("article")
    if article:
        img_tag = article.find("img")
    else:
        img_tag = soup.find("img")

    if img_tag:
        img = (
            img_tag.get("data-src")
            or img.get("data-original")
            or img_tag.get("src")
        )
        if img:
            img = img.strip()
            if img.startswith("//"):
                img = "https:" + img
            elif img.startswith("/"):
                img = "https://www.twentyfournews.com" + img
            return img

    return None


def _scrape_24news_section(section_url: str, category_id: int):
    """
    Scrape a TwentyFourNews Malayalam section page.
    For each Malayalam article link, also open the article page
    to fetch a reliable image from og:image,
    and SKIP any articles that have no image.
    """
    print(f"SCRAPING 24NEWS → {section_url}")

    session = _get_session()

    try:
        response = session.get(section_url, verify=False, timeout=10)
    except Exception as e:
        print("24NEWS request error:", e)
        return

    print("24NEWS status:", response.status_code)
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
            print("Skipping ML (no image):", title)
            continue

        print("24N link :", href)
        print("24N title:", title)
        print("24N img  :", image_src)
        print("24N cat  :", category_id)

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

    print("✔ 24NEWS added WITH images only:", count)


def _scrape_malayalam_trending():
    _scrape_24news_section("https://www.twentyfournews.com/news", 1)


def _scrape_malayalam_india():
    _scrape_24news_section("https://www.twentyfournews.com/news/national", 2)


def _scrape_malayalam_movies():
    _scrape_24news_section("https://www.twentyfournews.com/entertainment", 3)


def _scrape_malayalam_tech():
    _scrape_24news_section("https://www.twentyfournews.com/tech", 4)


def _scrape_malayalam_sports():
    _scrape_24news_section("https://www.twentyfournews.com/sports", 5)


# -------------------------------------------------------------------
# Scraping chains (entry points)
# -------------------------------------------------------------------

def scrape_malayalam(request):
    """
    Malayalam scraping chain using TwentyFourNews sections.
    After Malayalam, continues English category scraping.
    """
    print("Scraping Malayalam from TwentyFourNews...")
    _scrape_malayalam_trending()
    _scrape_malayalam_india()
    _scrape_malayalam_movies()
    _scrape_malayalam_tech()
    _scrape_malayalam_sports()

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
    print("headline_existing:", bool(headline_existing))
    print("check_date:", check_date)

    if headline_existing and check_date:
        print("DB not empty and today's EN main data exists")
        return news_list(request)

    print("Scraping fresh EN main + Malayalam + EN categories")

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
    Very basic login using Users model (name/password).
    """
    username = request.POST.get("username", "")
    password = request.POST.get("password", "")

    if not username or not password:
        return render(request, "news/index.html")

    request.session["username"] = username
    request.session["password"] = password

    users = Users.objects.all()
    for user in users:
        if user.name == username and user.password == password:
            user_language = user.language
            headlines = Headline.objects.all().order_by("-id")
            date_today = date.today()
            context = {
                "object_list": headlines,
                "user_language": user_language,
                "date_today": date_today,
            }
            return render(request, "news/user_view.html", context)

    # Login failed
    return render(request, "news/index.html")


# -------------------------------------------------------------------
# Malayalam views (TwentyFourNews-backed)
# -------------------------------------------------------------------

def malayalam_login(request):
    """
    Malayalam home (Trending/all): all Malayalam for today.
    If empty, trigger all Malayalam scrapers once.
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=2).exists():
        print("No ML headlines for today → scraping all Malayalam sections...")
        _scrape_malayalam_trending()
        _scrape_malayalam_india()
        _scrape_malayalam_movies()
        _scrape_malayalam_tech()
        _scrape_malayalam_sports()

    headlines = Headline.objects.filter(
        date=date_today,
        language=2,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam.html", context)


def malayalam_india_login(request):
    """
    Malayalam India page: category = 2.
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=2, category=2).exists():
        print("No ML India for today → scraping ML India...")
        _scrape_malayalam_india()

    headlines = Headline.objects.filter(
        date=date_today,
        language=2,
        category=2,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_india.html", context)


def malayalam_movie_login(request):
    """
    Malayalam Movies page: category = 3.
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=2, category=3).exists():
        print("No ML Movies for today → scraping ML Movies...")
        _scrape_malayalam_movies()

    headlines = Headline.objects.filter(
        date=date_today,
        language=2,
        category=3,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_movie.html", context)


def malayalam_tech_login(request):
    """
    Malayalam Tech page: category = 4.
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=2, category=4).exists():
        print("No ML Tech for today → scraping ML Tech...")
        _scrape_malayalam_tech()

    headlines = Headline.objects.filter(
        date=date_today,
        language=2,
        category=4,
    ).order_by("-id")

    print("ML TECH count:", headlines.count())

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_tech.html", context)


def malayalam_sports_login(request):
    """
    Malayalam Sports page: category = 5.
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=2, category=5).exists():
        print("No ML Sports for today → scraping ML Sports...")
        _scrape_malayalam_sports()

    headlines = Headline.objects.filter(
        date=date_today,
        language=2,
        category=5,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_sports.html", context)


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
        # Trigger full scraping chain
        return scrape(request)

    headlines = Headline.objects.filter(
        date=date_today,
        language=1,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english.html", context)


def english_tech_login(request):
    date_today = date.today()

    headlines = Headline.objects.filter(
        date=date_today,
        language=1,
        category=4,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english_tech.html", context)


def english_sports_login(request):
    date_today = date.today()

    headlines = Headline.objects.filter(
        date=date_today,
        language=1,
        category=5,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english_sports.html", context)


def english_movie_login(request):
    date_today = date.today()

    headlines = Headline.objects.filter(
        date=date_today,
        language=1,
        category=3,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english_movie.html", context)


def news_list(request):
    headlines = Headline.objects.all().order_by("-id")
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english.html", context)


def account(request):
    return render(request, "news/index_register.html")


# -------------------------------------------------------------------
# Search
# -------------------------------------------------------------------

def search(request):
    headlines = Headline.objects.all().order_by("-id")
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/search.html", context)


def search_news(request):
    headlines = Headline.objects.all()

    # Clear previous search results
    Search.objects.all().delete()

    search_category = request.POST.get("search_category")
    search_lang = request.POST.get("search_lang")
    search_title = request.POST.get("search_title", "")
    search_date = request.POST.get("search_date")

    for headline in headlines:
        if str(headline.language) == str(search_lang):
            if str(headline.category) == str(search_category):
                if str(headline.date) == str(search_date):
                    if search_title in headline.title:
                        Search.objects.create(
                            title=headline.title,
                            url=headline.url,
                            language=headline.language,
                            category=headline.category,
                            image=headline.image,
                            content=headline.content,
                        )

    return search_view(request)


def search_view(request):
    headlines = Headline.objects.all().order_by("-id")
    object_search = Search.objects.all()
    for a in object_search:
        print("Search result:", a.title)

    context = {
        "object_list": headlines,
        "object_search": object_search,
    }
    return render(request, "news/search_news.html", context)


# -------------------------------------------------------------------
# Register / Logout / English India view
# -------------------------------------------------------------------

def register(request):
    name = request.POST.get("name", "")
    email = request.POST.get("email", "")
    password = request.POST.get("password", "")
    language = request.POST.get("language")

    request.session["name"] = name
    request.session["email"] = email
    request.session["password"] = password
    request.session["language"] = language

    users = Users.objects.all()
    for user in users:
        if user.name == name or user.email == email:
            # Already exists
            return render(request, "news/index_register.html")

    Users.objects.create(
        name=name,
        email=email,
        password=password,
        language=language,
    )
    return render(request, "news/index.html")


def logout(request):
    # Simple logout: just show login page
    return render(request, "news/index.html")


def english_india(request):
    """
    English India/National page.
    If there is no India news for today, trigger english_india_scrape().
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=1, category=2).exists():
        return english_india_scrape(request)

    headlines = Headline.objects.filter(
        date=date_today,
        language=1,
        category=2,
    ).order_by("-id")

    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/english_india.html", context)
