from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from catalogue.views import health

urlpatterns = [path('admin/', admin.site.urls), path('api/', include('catalogue.urls'))]
urlpatterns += [path('console/', include('console.urls'))]
urlpatterns += [
    path('healthz', health, name='healthz'),
    # Shared by the console and admin menus. Logs out via POST only, then
    # sends the user back to the console login.
    path(
        'logout/',
        auth_views.LogoutView.as_view(next_page='/admin/login/?next=/console/'),
        name='logout',
    ),
]

if settings.DEBUG:
    # nginx serves uploaded product photos in production.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
