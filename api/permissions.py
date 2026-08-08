from rest_framework.permissions import BasePermission


class StaffModelViewPermissions(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        required_permissions = getattr(view, "required_model_permissions", None)
        if not required_permissions:
            return False
        return (
            user.is_authenticated
            and user.is_active
            and user.is_staff
            and user.has_perms(required_permissions)
        )
