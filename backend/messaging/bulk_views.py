"""Dashboard API for bulk sending (session-authenticated, scoped to the signed-in organization).

    GET  /api/bulk              the 20 most recent bulk sends
    POST /api/bulk              review (dry_run=true) or send; multipart: numbers, file, message fields
    GET  /api/bulk/<id>         one bulk send and its progress
    GET  /api/bulk/sample       a sample contacts file (CSV)
"""
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from common.csrf import EnforceCsrfMixin
from common.errors import ApiError
from common.ratelimit import hit

from . import bulk, campaigns
from .dashboard_views import OrgRequiredMixin
from .models import Campaign, Message
from .serializers import BulkSendSerializer, CampaignSerializer

FAILED = [Message.Status.FAILED, Message.Status.EXPIRED]


def campaigns_for(org):
    """This organization's bulk sends, each with a count of its messages by status."""
    return Campaign.objects.filter(organization=org).annotate(
        n_delivered=Count("messages", filter=Q(messages__status=Message.Status.DELIVERED)),
        n_sent=Count("messages", filter=Q(messages__status=Message.Status.SENT)),
        n_queued=Count("messages", filter=Q(messages__status=Message.Status.QUEUED)),
        n_failed=Count("messages", filter=Q(messages__status__in=FAILED)),
        n_cost=Sum("messages__cost_pesewas", filter=~Q(messages__status__in=FAILED)),
    )


class BulkListCreateView(EnforceCsrfMixin, OrgRequiredMixin, APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        recent = campaigns_for(self.org()).order_by("-created_at")[:20]
        return Response({"results": CampaignSerializer(recent, many=True).data})

    def post(self, request):
        org = self.org()
        # Refuse an absurdly large body before parsing it (a file at the cap plus pasted text fit well under this).
        if int(request.META.get("CONTENT_LENGTH") or 0) > bulk.MAX_FILE_BYTES + bulk.MAX_PASTE_CHARS * 4 + 256 * 1024:
            raise ApiError("upload_too_large", "That's too much to upload at once. Keep files under 2 MB.", 413)

        serializer = BulkSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        dry_run = data["dry_run"]

        # Reviewing parses a file, sending spends money: each gets its own, separate ceiling.
        if dry_run:
            hit(f"rl:bulkreview:org:{org.id}", limit=60, window=3600, code="rate_limited",
                message="You're reviewing lists very quickly. Try again in a few minutes.")
        else:
            hit(f"rl:bulksend:org:{org.id}", limit=20, window=3600, code="rate_limited",
                message="You've started a lot of bulk sends this hour. Try again later.")

        parsed = bulk.read_recipients(text=data.get("numbers", ""), upload=data.get("file"))
        body, category = campaigns.resolve_content(
            org, category=data.get("category"), template_id=data.get("template_id"), message=data.get("message"),
        )
        if dry_run:
            return Response(campaigns.review(org, parsed, body=body))

        campaign, created = campaigns.create_campaign(
            org, request.user, parsed, body=body, category=category, sender_id=data.get("sender_id") or None,
            save_customers=data["save_customers"], token=data["client_token"],
        )
        fresh = campaigns_for(org).get(pk=campaign.pk)
        return Response(CampaignSerializer(fresh).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class BulkDetailView(OrgRequiredMixin, APIView):
    def get(self, request, pk):
        campaign = get_object_or_404(campaigns_for(self.org()), pk=pk)
        return Response(CampaignSerializer(campaign).data)


class BulkSampleView(OrgRequiredMixin, APIView):
    def get(self, request):
        response = HttpResponse(bulk.SAMPLE_CSV, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="contacts-sample.csv"'
        return response
