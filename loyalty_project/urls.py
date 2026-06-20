from django.urls import include, path

from loyalty_api.ui_views import dashboard


urlpatterns = [
    path("", dashboard),
    path("api/", include("loyalty_api.urls")),
]
