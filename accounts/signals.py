from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.contrib import messages
from django.contrib.sites.shortcuts import get_current_site

from .models import Participation


@receiver(user_logged_in)
def on_user_logged_in(sender, request, **kwargs):
    Participation.on_site.get_or_create(user=request.user, site=get_current_site(request))
    messages.success(request, 'Welcome!', fail_silently=True)  # FIXME


@receiver(user_logged_out)
def on_user_logged_out(sender, request, **kwargs):
    messages.success(request, 'Goodbye!', fail_silently=True)  # FIXME
