from django.urls import path

from .views import NilpointRootView, NilpointGameDispatchView, NilpointAdminPanel


app_name = "nilpoint"
urlpatterns = [
    path("", NilpointRootView.as_view(), name="root"),
    path(
        "games/<slug:nilpoint_slug>/", NilpointGameDispatchView.as_view(), name="games"
    ),
    path("admin", NilpointAdminPanel.as_view(), name="admin"),
]
