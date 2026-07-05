import json
import logging
from dataclasses import asdict

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .channels import get_channel
from .tasks import process_inbound

logger = logging.getLogger(__name__)


@csrf_exempt
def whatsapp_webhook(request):
    channel = get_channel("whatsapp")

    # GET: Meta verification handshake
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge)
        return HttpResponseForbidden("verification failed")

    # POST: do the minimum, enqueue, return 200 fast (Meta retries slow webhooks)
    if not channel.verify_signature(request.body, request.headers):
        logger.warning("Rejected webhook: bad signature")
        return HttpResponseForbidden("bad signature")

    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    for inbound in channel.parse_inbound(payload):
        process_inbound.delay("whatsapp", asdict(inbound))

    return JsonResponse({"status": "received"})
