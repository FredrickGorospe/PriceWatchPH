from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

from config.views import spa_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls", namespace="api-v1")),
    path(
        "auth/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            next_page="/deals",
        ),
        name="login",
    ),
    path(
        "auth/logout/",
        auth_views.LogoutView.as_view(next_page="/auth/login/"),
        name="logout",
    ),
    # Protected server namespaces cannot fall through to the React shell.
    re_path(
        r"^(?!(?:api|admin|auth|static)(?:/|$)).*$",
        spa_index,
        name="spa-index",
    ),
]
