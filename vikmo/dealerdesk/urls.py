from django.contrib import admin
from django.urls import include, path
from core.views import frontend_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("", frontend_index, name="frontend"),
]
