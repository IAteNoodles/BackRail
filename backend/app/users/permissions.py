from rest_framework.permissions import BasePermission


class IsAcceptedUser(BasePermission):
    """
    Allows access only to authenticated users whose account status is 'accepted'.
    """
    message = "Your account is not active. Contact an administrator."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.user_status == 'accepted'
        )
