from django.urls import path
from .views import query_view

urlpatterns = [
    path('query/', query_view, name='query'),  # Define the endpoint
]
