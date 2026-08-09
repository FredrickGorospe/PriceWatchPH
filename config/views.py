from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_safe


@require_safe
def spa_index(request):
    index_path = settings.FRONTEND_DIST_DIR / "index.html"
    if not index_path.is_file():
        return HttpResponse(
            "The PriceWatch PH frontend bundle is unavailable.",
            status=503,
            content_type="text/plain",
        )

    return HttpResponse(index_path.read_bytes(), content_type="text/html")
