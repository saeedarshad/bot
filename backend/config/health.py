from django.db import connection
from django.http import JsonResponse
from redis import Redis
from redis.exceptions import RedisError

from django.conf import settings


def healthz(request):
    checks = {"db": False, "redis": False}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["db"] = True
    except Exception:
        pass

    try:
        client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        checks["redis"] = client.ping()
    except (RedisError, OSError):
        pass

    ok = all(checks.values())
    return JsonResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status=200 if ok else 503,
    )
