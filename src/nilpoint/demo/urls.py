from django.urls import path

from .views import DemoGameView

# `app_name` must be the lowercased Game class name: nilpoint's dispatch
# view redirects /games/<slug>/ by reversing "<game_type>:dispatch".
app_name = "demogame"

urlpatterns = [
    path("", DemoGameView.as_view(), name="dispatch"),
]
