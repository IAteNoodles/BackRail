from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..metrics import record_dump
from ..permissions import IsAcceptedUser
from ..sync import build_dump_payload


class DumpView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        last_synced = request.query_params.get('last_synced')
        diff_value = request.query_params.get('diff')

        try:
            payload = build_dump_payload(last_synced=last_synced, diff_value=diff_value)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        record_dump(payload['mode'], payload['document_count'])
        return Response(payload, status=status.HTTP_200_OK)