#!/usr/bin/python
# -*- coding: utf-8 -*-

import re
import requests
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup as BSoup
from django.shortcuts import render
from news.models import Headline, Malayalam_Headline, Search, Users

requests.packages.urllib3.disable_warnings()

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def _get_session():
    """Return a requests session with a fake User-Agent."""
    session = requests.Session()
    session.headers = {
        "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"
    }
    return session


def _clean_url(url):
    """Ensure URL is absolute and safe."""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://indianexpress.com" + url
    return url


def _clean_malayalam_url(url):
    """Ensure URL is absolute for Malayalam IE site."""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://malayalam.indianexpress.com" + url
    return url


# -------------------------------------------------------------------
# ENGLISH: Main cities scraper (home page)
# -------------------------------------------------------------------

def scrape(request):
    """
    Scrape English 'cities' news from Indian Express.

    Logic:
    - If we already have headlines for *today*, just show the list.
    - Otherwise, scrape English cities, then Malayalam (IE Malayalam),
      then the English categories (India, Tech, Sports, Movie).
    """
    date_english = date.today()

    headline_existing = Headline.objects.all()
    check_date = Headline.objects.filter(date=date_english, language=1, category=1).exists()
    print("headline_existing:", bool(headline_existing))
    print("check_date:", check_date)

    def fetch_english_news():
        session = _get_session()
        url = "https://indianexpress.com/section/cities/"
        response = session.get(url, verify=False)
        soup = BSoup(response.content, "html.parser")
        return soup.find_all("div", {"class": "articles"})

    def save_english_news(news_blocks):
        for article in news_blocks:
            links = article.find_all("a")
            if not links:
                continue

            main = links[0]
            link = _clean_url(main.get("href", ""))
            print("EN cities link:", link)

            # Robust image handling
            image_src = None
            try:
                img_tag = article.find("img")
                if img_tag is not None:
                    image_src = (
                        img_tag.get("data-lazy-src")
                        or img_tag.get("data-src")
                        or img_tag.get("data-srcset")
                        or img_tag.get("src")
                    )
                if image_src:
                    image_src = _clean_url(image_src)
                print("EN cities image_src:", image_src)
            except Exception as e:
                print("EN cities image error:", e)
                image_src = None

            title_tag = article.find("h2")
            title = title_tag.get_text(strip=True) if title_tag else ""
            print("EN cities title:", title)

            content_tag = article.find("p")
            content_text = content_tag.get_text(strip=True) if content_tag else ""

            new_headline = Headline()
            new_headline.title = title
            new_headline.url = link
            new_headline.language = 1  # English
            new_headline.category = 1  # Cities
            new_headline.image = image_src
            new_headline.content = content_text
            new_headline.date = date_english
            new_headline.save()

    # ---------------- main logic ----------------

    if headline_existing and check_date:
        # Already have today's English cities headlines
        print("DB not empty and today's EN cities data exists")
        return news_list(request)

    # Else: need fresh data
    print("Scraping fresh English cities + Malayalam + EN categories")
    news_blocks = fetch_english_news()
    save_english_news(news_blocks)

    # Now scrape Malayalam (Indian Express Malayalam) and then categories
    return scrape_malayalam(request)


# -------------------------------------------------------------------
# MALAYALAM: Indian Express Malayalam
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
    We get:
      - headline text from <h2> / <h3> tags
      - link from inner <a>
      - image using nearest previous <img> tag
    """
    session = _get_session()
    url = "https://malayalam.indianexpress.com/"
    response = session.get(url, verify=False)
    soup = BSoup(response.content, "html.parser")

    # collect headlines from h2 and h3 (IE Malayalam uses these for story cards)
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

        # Try to find a nearby image (previous in DOM)
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
        new_headline.content = ""  # IE Malayalam cards often have no short excerpt
        new_headline.save()


def scrape_malayalam(request):
    """
    Entry point to Malayalam scraping chain.
    Uses Indian Express Malayalam instead of Manorama.
    After Malayalam, continue with English India/Tech/Sports/Movie scrapers.
    """
    print("Scraping IE Malayalam frontpage...")
    _scrape_ie_malayalam_frontpage()
    return english_india_scrape(request)


# -------------------------------------------------------------------
# ENGLISH: category scrapers (India, Tech, Sports, Movie)
# -------------------------------------------------------------------

def _scrape_indianexpress_block(url, language, category):
    """
    Generic helper for Indian Express 'articles' blocks.
    Now uses robust image extraction (not only .jpg regex).
    """
    session = _get_session()
    response = session.get(url, verify=False)
    soup = BSoup(response.content, "html.parser")

    news_blocks = soup.find_all("div", {"class": "articles"})
    for article in news_blocks:
        links = article.find_all("a")
        if not links:
            continue

        main = links[0]
        link = _clean_url(main.get("href", ""))
        print("EN cat link:", link)

        # More robust image logic
        image_src = None
        img_tag = article.find("img")
        if img_tag is not None:
            image_src = (
                img_tag.get("data-lazy-src")
                or img_tag.get("data-src")
                or img_tag.get("data-srcset")
                or img_tag.get("src")
            )
        if image_src:
            image_src = _clean_url(image_src)
        print("EN cat image_src:", image_src)

        title_tag = article.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else ""
        print("EN cat title:", title)

        content_tag = article.find("p")
        content_text = content_tag.get_text(strip=True) if content_tag else ""

        new_headline = Headline()
        new_headline.title = title
        new_headline.url = link
        new_headline.language = language
        new_headline.category = category
        new_headline.image = image_src
        new_headline.content = content_text
        new_headline.save()


def english_india_scrape(request):
    _scrape_indianexpress_block(
        url="https://indianexpress.com/section/india/",
        language=1,
        category=2,
    )
    return english_tech_scrape(request)


def english_tech_scrape(request):
    _scrape_indianexpress_block(
        url="https://indianexpress.com/section/technology/",
        language=1,
        category=4,
    )
    return english_sports_scrape(request)


def english_sports_scrape(request):
    _scrape_indianexpress_block(
        url="https://indianexpress.com/section/sports/",
        language=1,
        category=5,
    )
    return english_movie_scrape(request)


def english_movie_scrape(request):
    _scrape_indianexpress_block(
        url="https://indianexpress.com/section/entertainment/bollywood/box-office-collection/",
        language=1,
        category=3,
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
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_malayalam.html", context)


def malayalam_india_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_malayalam_india.html", context)


def malayalam_movie_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_malayalam_movie.html", context)


def malayalam_tech_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_malayalam_tech.html", context)


def malayalam_sports_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_malayalam_sports.html", context)


def english_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_english.html", context)


def english_tech_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_english_tech.html", context)


def english_sports_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_english_sports.html", context)


def english_movie_login(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_english_movie.html", context)


def news_list(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/home_english.html", context)


def account(request):
    return render(request, "news/index_register.html")


# -------------------------------------------------------------------
# Search
# -------------------------------------------------------------------

def search(request):
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
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

    # Create new user
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
    headlines = Headline.objects.all()[::-1]
    date_today = date.today()
    context = {
        "object_list": headlines,
        "date_today": date_today,
    }
    return render(request, "news/english_india.html", context)
