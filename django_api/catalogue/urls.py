from django.urls import path
from .views import catalogue, create_order
urlpatterns=[path('catalogue',catalogue),path('orders',create_order)]
