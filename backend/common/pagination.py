from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class PagePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        paginator = self.page.paginator
        return Response({
            "count": paginator.count,
            "page": self.page.number,
            "page_size": paginator.per_page,
            "total_pages": paginator.num_pages,
            "results": data,
        })
