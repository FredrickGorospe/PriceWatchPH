from django.contrib import admin

from pricing.models import DealFlag, PricePoint

admin.site.register(PricePoint)
admin.site.register(DealFlag)
