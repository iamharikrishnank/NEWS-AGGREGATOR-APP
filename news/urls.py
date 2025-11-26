from django.urls import path
from . import views

urlpatterns = [
    path("", views.scrape, name="scrape"),
    path("newslist", views.news_list, name="home"),

    path("login", views.login, name="login"),
    path("account/", views.account, name="account"),
    path("register/", views.register, name="register"),
    path("logout/", views.logout, name="logout"),

    path("malayalam_login", views.malayalam_login, name="malayalam_login"),
    path("malayalam_india_login", views.malayalam_india_login, name="malayalam_india_login"),
    path("malayalam_movie_login", views.malayalam_movie_login, name="malayalam_movie_login"),
    path("malayalam_tech_login", views.malayalam_tech_login, name="malayalam_tech_login"),
    path("malayalam_sports_login", views.malayalam_sports_login, name="malayalam_sports_login"),

    path("english_login", views.english_login, name="english_login"),
    path("english_india", views.english_india, name="english_india"),
    path("english_tech_login", views.english_tech_login, name="english_tech_login"),
    path("english_sports_login", views.english_sports_login, name="english_sports_login"),
    path("english_movie_login", views.english_movie_login, name="english_movie_login"),

    path("search", views.search, name="search"),
    path("search_news", views.search_news, name="search_news"),
    path("search_view", views.search_view, name="search_view"),
]
