from django.shortcuts import get_object_or_404, render
from django.contrib.sites.shortcuts import get_current_site

from .models import Conversation


def conversation_details(request, conversation):
    conversation = get_object_or_404(Conversation, id=conversation, speaker__site=get_current_site(request))
    return render(request, 'conversations/message.html', {
            'messages': conversation.messages,
    })