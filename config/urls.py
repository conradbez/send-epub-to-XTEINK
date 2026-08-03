from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("opds/", include("opds.urls")),
    path("", include("web.urls")),
]
