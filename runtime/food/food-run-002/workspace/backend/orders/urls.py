from django.urls import path
from .views import order_action, order_detail, order_list

urlpatterns = [
    path("", order_list),
    path("<int:order_id>/", order_detail),
    path("<int:order_id>/actions/", order_action),
]
