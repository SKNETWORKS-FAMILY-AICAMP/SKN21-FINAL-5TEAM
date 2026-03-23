from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from backend.chat_auth import chat_auth_token

urlpatterns = [
    path("api/chat/auth-token", chat_auth_token),
    path("api/products/", include("products.urls")),
    path("api/orders/", include("orders.urls")),
    path("api/users/", include("users.urls")),]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
