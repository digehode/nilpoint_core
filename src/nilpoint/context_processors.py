from .models import Game, Player


class NilpointContext:
    """A custom, non-ORM class built dynamically per-request."""

    def __init__(self, request):
        self.games = [game.get_real_instance() for game in Game.objects.all()]
        if request.user.id:
            try:
                self.player = Player.objects.get(user=request.user)
            except Player.DoesNotExist:
                self.player = None
        else:
            self.player = None


def nilpoint_context(request):
    """Adds a NilpointContext object to each template being rendered,
    for access to key information and objects
    """

    return {"nilpoint": NilpointContext(request)}
