import logging

from rest_framework.pagination import PageNumberPagination


logger = logging.getLogger('users')


class StandardPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 200