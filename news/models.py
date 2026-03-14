from django.db import models

# Create your models here.
from django.db import models
from django.utils import timezone
class Headline(models.Model):
  title = models.TextField()
  image = models.URLField(null=True, blank=True)
  url = models.TextField()
  date = models.DateField(auto_now_add=True)
  language = models.CharField(max_length=200)
  category = models.CharField(max_length=200)
  content = models.TextField()
  # check = models.TextField()


  def __str__(self):
    return self.title
class Malayalam_Headline(models.Model):
  title = models.CharField(max_length=200)
  image = models.URLField(null=True, blank=True)
  url = models.TextField()
  def __str__(self):
    return self.title

class Users(models.Model):
   name = models.CharField(max_length=5500)
   email = models.CharField(max_length=5500)
   password = models.CharField(max_length=5500)
   language = models.CharField(max_length=200)
   categories = models.CharField(max_length=200, null=True, blank=True)
   class Meta:
     db_table = "users"
class Search(models.Model):
  title = models.TextField()
  image = models.URLField(null=True, blank=True)
  url = models.TextField()
  date = models.DateField(auto_now_add=True)
  language = models.CharField(max_length=200)
  category = models.CharField(max_length=200)
  content = models.TextField()
  # check = models.TextField()


  def __str__(self):
    return self.title