from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [path('admin/', admin.site.urls), path('api/', include('catalogue.urls'))]
urlpatterns += [path('console/', include('console.urls'))]
urlpatterns += [
    # Shared by the console and admin menus. Logs out via POST only, then
    # sends the user back to the console login.
    path(
        'logout/',
        auth_views.LogoutView.as_view(next_page='/admin/login/?next=/console/'),
        name='logout',
    ),
]
