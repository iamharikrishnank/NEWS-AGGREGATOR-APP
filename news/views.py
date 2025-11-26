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
# Helper functions
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


def _clean_malayalam_url(url):
    """Ensure URL is absolute for Malayalam IE site."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://malayalam.indianexpress.com" + url
    return url


# -------------------------------------------------------------------
# ENGLISH via THE HINDU RSS
# -------------------------------------------------------------------
# Category mapping in Headline:
#   language = 1 (English)
#   category:
#       1 = News (main /news/)
#       2 = India / National
#       3 = Movies / Entertainment
#       4 = Technology
#       5 = Sports
# -------------------------------------------------------------------

def _scrape_thehindu_rss(feed_url, language, category_id):
    """
    Scrape a The Hindu RSS feed and save items into Headline.

    feed_url: The Hindu RSS URL (e.g. https://www.thehindu.com/news/national/?service=rss)
    language: 1 = English
    category_id: internal numeric category in Headline model
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

    # Parse RSS XML
    soup = BSoup(response.content, "xml")
    items = soup.find_all("item")
    print(f"The Hindu RSS: {feed_url} -> {len(items)} items")

    today = date.today()

    for item in items:
        # ----- Title -----
        title_tag = item.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue

        # ----- Link -----
        link_tag = item.find("link")
        link = link_tag.get_text(strip=True) if link_tag else ""
        if not link:
            continue

        # ----- Description / Summary -----
        desc_tag = item.find("description")
        description_html = desc_tag.get_text() if desc_tag else ""
        # Decode HTML entities and strip tags to plain text
        description_html = html.unescape(description_html)
        content_text = BSoup(description_html, "html.parser").get_text(" ", strip=True)

        # ----- Image (media:content or enclosure) -----
        image_src = None

        media_tag = item.find("media:content")
        if media_tag and media_tag.get("url"):
            image_src = media_tag["url"]

        if not image_src:
            enclosure = item.find("enclosure")
            if enclosure and enclosure.get("url"):
                image_src = enclosure["url"]

        print("TH RSS Title:", title)
        print("TH RSS Link :", link)
        print("TH RSS Image:", image_src)

        # Avoid duplicates for today
        exists = Headline.objects.filter(
            title=title,
            language=language,
            category=category_id,
            date=today,
        ).exists()
        if exists:
            continue

        new_headline = Headline()
        new_headline.title = title
        new_headline.url = link
        new_headline.language = language
        new_headline.category = category_id
        new_headline.image = image_src
        new_headline.content = content_text
        new_headline.date = today
        new_headline.save()


# -------------------------------------------------------------------
# ENGLISH: Main scraper (Home/News) using The Hindu News RSS
# -------------------------------------------------------------------

def scrape(request):
    """
    Scrape English 'main/home' news using The Hindu News RSS as category 1.

    Logic:
    - If we already have headlines for *today* with language=1 and category=1,
      just show the list.
    - Otherwise:
        - Scrape The Hindu News RSS as category 1 (News/Trending)
        - Then scrape Malayalam IE front page
        - Then chain English categories (India, Tech, Sports, Movies).
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

    print("Scraping fresh EN The Hindu RSS + Malayalam + EN categories")

    # Category 1: main /news/ (you can label this 'News' or 'Trending' in templates)
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/news/?service=rss",
        language=1,
        category_id=1,
    )

    return scrape_malayalam(request)


# -------------------------------------------------------------------
# MALAYALAM: Indian Express Malayalam (unchanged)
# -------------------------------------------------------------------

def _infer_malayalam_category_from_url(url):
    """
    Map IE Malayalam URL path to our category numbers:
      1 = General news
      2 = India / Kerala / national
      3 = Movies / Entertainment
      4 = Tech
      5 = Sports
    """
    try:
        path = urlparse(url).path.lower()
    except Exception:
        path = ""

    if "/sports" in path:
        return 5
    if "/entertainment" in path:
        return 3
    if "/tech" in path:
        return 4
    if "/kerala-news" in path:
        return 2
    if "/news" in path:
        return 2
    return 1


def _scrape_ie_malayalam_frontpage():
    """
    Scrape Malayalam headlines from https://malayalam.indianexpress.com/
    """
    session = _get_session()
    url = "https://malayalam.indianexpress.com/"
    response = session.get(url, verify=False)
    soup = BSoup(response.content, "html.parser")

    headline_tags = soup.find_all(["h2", "h3"])
    seen_urls = set()

    for h_tag in headline_tags:
        a_tag = h_tag.find("a", href=True)
        if not a_tag:
            continue

        link = _clean_malayalam_url(a_tag["href"])
        if not link or link in seen_urls:
            continue
        seen_urls.add(link)

        title = a_tag.get_text(strip=True)
        if not title:
            continue

        img_tag = h_tag.find_previous("img")
        image_src = None
        if img_tag is not None:
            image_src = (
                img_tag.get("data-lazy-src")
                or img_tag.get("data-src")
                or img_tag.get("src")
            )
            if image_src:
                image_src = _clean_malayalam_url(image_src)

        print("ML link:", link)
        print("ML title:", title)
        print("ML image_src:", image_src)

        category = _infer_malayalam_category_from_url(link)

        new_headline = Headline()
        new_headline.title = title
        new_headline.url = link
        new_headline.language = 2  # Malayalam
        new_headline.category = category
        new_headline.image = image_src
        new_headline.content = ""
        new_headline.date = date.today()
        new_headline.save()


def scrape_malayalam(request):
    """
    Entry point to Malayalam scraping chain (IE Malayalam),
    then continue to English sub-categories from The Hindu.
    """
    print("Scraping IE Malayalam frontpage...")
    _scrape_ie_malayalam_frontpage()
    return english_india_scrape(request)


# -------------------------------------------------------------------
# ENGLISH: category scrapers via THE HINDU RSS
# -------------------------------------------------------------------

def english_india_scrape(request):
    """
    English India/National using The Hindu RSS.
    category=2 in DB.
    """
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/news/national/?service=rss",
        language=1,
        category_id=2,
    )
    return english_tech_scrape(request)


def english_tech_scrape(request):
    """
    English Tech using The Hindu Tech RSS.
    category=4 in DB.
    """
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/sci-tech/technology/?service=rss",
        language=1,
        category_id=4,
    )
    return english_sports_scrape(request)


def english_sports_scrape(request):
    """
    English Sports using The Hindu Sports RSS.
    category=5 in DB.
    """
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/sport/?service=rss",
        language=1,
        category_id=5,
    )
    return english_movie_scrape(request)


def english_movie_scrape(request):
    """
    English Movies using The Hindu Movies RSS.
    category=3 in DB.
    """
    _scrape_thehindu_rss(
        feed_url="https://www.thehindu.com/entertainment/movies/?service=rss",
        language=1,
        category_id=3,
    )
    return news_list(request)


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
            headlines = Headline.objects.all()[::-1]
            date_today = date.today()
            context = {
                "object_list": headlines,
                "user_language": user_language,
                "date_today": date_today,
            }
            return render(request, "news/user_view.html", context)

    # Login failed
    return render(request, "news/index.html")


def malayalam_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam.html", context)


def malayalam_india_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_india.html", context)


def malayalam_movie_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_movie.html", context)


def malayalam_tech_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    print(context)
    return render(request, "news/home_malayalam_tech.html", context)


def malayalam_sports_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_malayalam_sports.html", context)


def english_login(request):
    """
    English home (News/Trending).
    If no English news for today, trigger full scrape().
    """
    date_today = date.today()

    if not Headline.objects.filter(date=date_today, language=1).exists():
        # Trigger full scraping chain
        return scrape(request)

    headlines = Headline.objects.all()[::-1]
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english.html", context)


def english_tech_login(request):
    date_today = date.today()
    headlines = Headline.objects.all()[::-1]
    context = {"object_list": headlines, "date_today": date_today}
    print(context)
    return render(request, "news/home_english_tech.html", context)


def english_sports_login(request):
    date_today = date.today()
    headlines = Headline.objects.all()[::-1]
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english_sports.html", context)


def english_movie_login(request):
    date_today = date.today()
    headlines = Headline.objects.all()[::-1]
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english_movie.html", context)


def news_list(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/home_english.html", context)


def account(request):
    return render(request, "news/index_register.html")


# -------------------------------------------------------------------
# Search
# -------------------------------------------------------------------

def search(request):
    headlines = Headline.objects.all()[::-1]
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
                        new_search = Search()
                        new_search.title = headline.title
                        new_search.url = headline.url
                        new_search.language = headline.language
                        new_search.category = headline.category
                        new_search.image = headline.image
                        new_search.content = headline.content
                        new_search.save()

    return search_view(request)


def search_view(request):
    headlines = Headline.objects.all()[::-1]
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

    dr = Users(
        name=name,
        email=email,
        password=password,
        language=language,
    )
    dr.save()
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

    headlines = Headline.objects.all()[::-1]
    context = {"object_list": headlines, "date_today": date_today}
    return render(request, "news/english_india.html", context)
