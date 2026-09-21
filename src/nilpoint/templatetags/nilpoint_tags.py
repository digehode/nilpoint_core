"""
Template tags for Nilpoint HTMX patterns.

Provides tags to simplify common HTMX patterns in templates:
- nilpoint_action_url: Generate dispatch URL with action and parameters
- nilpoint_panel: Render an HTMX panel div that loads via GET
- nilpoint_action: Render an action link/button with correct HTTP method
- nilpoint_form: Render a form that GETs on load, POSTs on submit
"""

from django import template
from django.urls import NoReverseMatch

from nilpoint.decorators import _get_handler_methods

register = template.Library()


@register.filter
def dict_to_query(value):
    """Convert a dict to a query string (key=value&...)."""
    if not value:
        return ""
    return "&".join(f"{k}={v}" for k, v in value.items())


@register.simple_tag
def nilpoint_action_url(game, action, **params):
    """
    Generate a dispatch URL for the given action and parameters.

    Usage:
        {% nilpoint_action_url game "item_detail" item=item.id %}
        -> /game/slug?action=item_detail&item=123

    Args:
        game: Game instance (must have get_dispatch_url method)
        action: Action name (e.g., "item_detail", "take_item")
        **params: Additional query parameters

    Returns:
        Full URL string with action and parameters
    """
    try:
        base_url = game.get_dispatch_url()
    except (NoReverseMatch, AttributeError):
        return "#"

    url = f"{base_url}?action={action}"
    if params:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"&{param_str}"
    return url


@register.simple_tag
def nilpoint_action_method(view_class, action):
    """
    Get the allowed HTTP methods for an action.

    Usage:
        {% nilpoint_action_method view_class "take_item" %}
        -> "POST"
    """
    methods = _get_handler_methods(view_class, action)
    # Return first method if single, or "GET,POST" if both
    if len(methods) == 1:
        return methods.pop()
    return ",".join(sorted(methods))


@register.inclusion_tag("nilpoint/tags/panel.jinja2", takes_context=True)
def nilpoint_panel(
    context, panel_id, action, triggers, target="this", swap="innerHTML", **params
):
    """
    Render an HTMX panel div that loads content via GET.

    Usage:
        {% nilpoint_panel "nilpoint-scene" "get_location_graphic"
           triggers="load, player_location_changed from:body" %}

    Args:
        panel_id: HTML id for the div
        action: Action name (e.g., "get_location_graphic")
        triggers: HTMX trigger string
        target: hx-target (default "this")
        swap: hx-swap (default "innerHTML")
        **params: Additional query parameters

    Returns:
        Context for nilpoint/tags/panel.jinja2 template
    """
    game = context.get("game")
    if game:
        try:
            base_url = game.get_dispatch_url()
            url = f"{base_url}?action={action}"
            if params:
                param_str = "&".join(f"{k}={v}" for k, v in params.items())
                url += f"&{param_str}"
        except (NoReverseMatch, AttributeError):
            url = "#"
    else:
        url = "#"

    return {
        "panel_id": panel_id,
        "url": url,
        "triggers": triggers,
        "target": target,
        "swap": swap,
    }


@register.inclusion_tag("nilpoint/tags/action.jinja2", takes_context=True)
def nilpoint_action(
    context,
    text,
    action,
    method=None,
    target=None,
    swap="innerHTML",
    classes="",
    **params,
):
    """
    Render an action link/button with correct HTTP method.

    Usage:
        {% nilpoint_action "Detail" "item_detail" item=item.id
           target="#nilpoint-item-detail-panel" %}
        {% nilpoint_action "Take" "take_item" method="post" location_item=li.id %}

    Args:
        text: Link/button text
        action: Action name
        method: HTTP method ("get" or "post") - auto-detected if None
        target: hx-target selector (optional)
        swap: hx-swap (default "innerHTML")
        classes: Additional CSS classes
        **params: Parameters (query string for GET, hx-vals for POST)

    Returns:
        Context for nilpoint/tags/action.jinja2 template
    """
    game = context.get("game")
    if game:
        try:
            base_url = game.get_dispatch_url()
        except (NoReverseMatch, AttributeError):
            base_url = "#"
    else:
        base_url = "#"

    # Auto-detect method if not specified
    if method is None:
        # Default to GET for link semantics
        method = "GET"

    method = method.upper()

    # Build URL and hx-vals based on method
    if method == "GET":
        # GET: params go in query string
        url = f"{base_url}?action={action}"
        if params:
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            url += f"&{param_str}"
        hx_vals = None
    else:
        # POST: action in URL, params in hx-vals
        url = f"{base_url}?action={action}"
        # Convert params to JSON for hx-vals
        import json

        hx_vals = json.dumps(params)

    return {
        "text": text,
        "action": action,
        "method": method,
        "target": target,
        "swap": swap,
        "classes": classes,
        "url": url,
        "hx_vals": hx_vals,
    }


@register.inclusion_tag("nilpoint/tags/form.jinja2", takes_context=True)
def nilpoint_form(
    context, form_id, action, form=None, target=None, swap="innerHTML", **params
):
    """
    Render a form that POSTs on submit.

    Usage:
        {% nilpoint_form "new-pc-form" "new_player_character" form=form %}
        {% nilpoint_form "my-form" "some_action" form=form target="#target" swap="outerHTML" %}

    Args:
        form_id: HTML id for the form
        action: Action name (used in URL as ?action=...)
        form: Django Form instance (optional) - if provided, its fields are rendered
        target: hx-target selector (optional)
        swap: hx-swap (default "innerHTML")
        **params: Additional query parameters for the action URL

    Returns:
        Context for nilpoint/tags/form.jinja2 template
    """
    game = context.get("game")
    if game:
        try:
            base_url = game.get_dispatch_url()
            url = f"{base_url}?action={action}"
            if params:
                param_str = "&".join(f"{k}={v}" for k, v in params.items())
                url += f"&{param_str}"
        except (NoReverseMatch, AttributeError):
            url = "#"
    else:
        url = "#"

    return {
        "form_id": form_id,
        "action": action,
        "form": form,
        "target": target,
        "swap": swap,
        "url": url,
    }
