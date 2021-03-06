from functools import reduce

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.utils.translation import ugettext as _
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse

from ponyconf.mixins import OnSiteFormMixin

from accounts.models import Participation
from accounts.mixins import OrgaRequiredMixin, StaffRequiredMixin
from accounts.decorators import orga_required, staff_required
from accounts.utils import is_staff, is_orga

from conversations.models import ConversationWithParticipant, ConversationAboutTalk, Message

from planning.models import Room

from .forms import TalkForm, TopicForm, TrackForm, ConferenceForm, TalkFilterForm, STATUS_VALUES, SpeakerFilterForm, TalkActionForm
from .models import Talk, Track, Topic, Vote, Conference
from .signals import talk_added, talk_edited
from .utils import allowed_talks, markdown_to_html


@login_required
@require_http_methods(["POST"])
def markdown_preview(request):
    content = request.POST.get('data', '')
    return HttpResponse(markdown_to_html(content))


def home(request):
    return render(request, 'proposals/home.html')


@orga_required
def conference(request):
    conference = Conference.objects.get(site=get_current_site(request))
    form = ConferenceForm(request.POST or None, instance=conference)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Conference updated!')
        return redirect(reverse('conference'))
    return render(request, 'proposals/conference.html', {
        'conference': conference,
        'form': form,
    })

@login_required
def participate(request):
    site = get_current_site(request)
    conf = Conference.objects.get(site=site)
    talks = Talk.objects.filter(site=site)
    my_talks = talks.filter(speakers=request.user)
    proposed_talks = talks.exclude(speakers=request.user).filter(proposer=request.user)
    return render(request, 'proposals/participate.html', {
        'my_talks': my_talks,
        'proposed_talks': proposed_talks,
        'conf': conf,
    })

@staff_required
def talk_list(request):
    show_filters = False
    talks = Talk.objects.filter(site=get_current_site(request))
    filter_form = TalkFilterForm(request.GET or None, site=get_current_site(request))
    # Filtering
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if len(data['kind']):
            show_filters = True
            talks = talks.filter(reduce(lambda x, y: x | y, [Q(event__pk=pk) for pk in data['kind']]))
        if len(data['status']):
            show_filters = True
            talks = talks.filter(reduce(lambda x, y: x | y, [Q(accepted=dict(STATUS_VALUES)[status]) for status in data['status']]))
        if len(data['topic']):
            show_filters = True
            talks = talks.filter(reduce(lambda x, y: x | y, [Q(topics__slug=topic) for topic in data['topic']]))
        if len(data['track']):
            show_filters = True
            q = Q()
            if 'none' in data['track']:
                data['track'].remove('none')
                q |= Q(track__isnull=True)
            if len(data['track']):
                q |= Q(track__slug__in=data['track'])
            talks = talks.filter(q)
        if data['vote'] != None:
            if data['vote']:
                talks = talks.filter(vote__user=request.user)
            else:
                talks = talks.exclude(vote__user=request.user)
        if data['room'] != None:
            talks = talks.filter(room__isnull=not data['room'])
        if data['scheduled'] != None:
            talks = talks.filter(start_date__isnull=not data['scheduled'])
    # Action
    action_form = TalkActionForm(request.POST or None, talks=talks, site=get_current_site(request))
    if not is_orga(request, request.user):
        action_form.fields.pop('track')
        action_form.fields.pop('room')
    if request.method == 'POST':
        if action_form.is_valid():
            data = action_form.cleaned_data
            permission_error = False
            for talk in data['talks']:
                talk = Talk.objects.get(site=get_current_site(request), slug=talk)
                if data['decision'] != None:
                    if not talk.is_moderable_by(request.user):
                        permission_error = True
                        continue
                    # TODO: merge with talk_decide code
                    conversation = ConversationAboutTalk.objects.get(talk=talk)
                    if data['decision']:
                        note = "The talk has been accepted."
                    else:
                        note = "The talk has been declined."
                    Message.objects.create(conversation=conversation, author=request.user, content=note)
                    talk.accepted = data['decision']
                if data['track']:
                    talk.track = Track.objects.get(site=get_current_site(request), slug=data['track'])
                if data['room']:
                    talk.room = Room.objects.get(site=get_current_site(request), slug=data['room'])
                talk.save()
            if permission_error:
                messages.warning(request, 'Some actions were ignored due to missing permissions.')
            return redirect(request.get_full_path())
    # Sorting
    if request.GET.get('order') == 'desc':
        reverse = True
    else:
        reverse = False
    SORT_MAPPING = {
        'title': 'title',
        'kind': 'event',
        'status': 'accepted',
    }
    sort = request.GET.get('sort')
    if sort in SORT_MAPPING.keys():
        if reverse:
            talks = talks.order_by('-' + SORT_MAPPING[sort])
        else:
            talks = talks.order_by(SORT_MAPPING[sort])
    # Sorting URLs
    sort_urls = dict()
    sort_glyphicons = dict()
    for c in SORT_MAPPING.keys():
        url = request.GET.copy()
        url['sort'] = c
        if c == sort:
            if reverse:
                del url['order']
                glyphicon = 'sort-by-attributes-alt'
            else:
                url['order'] = 'desc'
                glyphicon = 'sort-by-attributes'
        else:
            glyphicon = 'sort'
        sort_urls[c] = url.urlencode()
        sort_glyphicons[c] = glyphicon
    return render(request, 'proposals/talk_list.html', {
        'show_filters': show_filters,
        'talk_list': talks,
        'filter_form': filter_form,
        'action_form': action_form,
        'sort_urls': sort_urls,
        'sort_glyphicons': sort_glyphicons,
    })

@login_required
def talk_edit(request, talk=None):
    site = get_current_site(request)
    if talk: # edit existing talk
        talk = get_object_or_404(Talk, slug=talk, site=site)
        if not talk.is_editable_by(request.user):
            raise PermissionDenied()
    else: # add new talk
        conf = Conference.objects.get(site=site)
        if not is_orga(request, request.user) and not conf.cfp_is_open():
            raise PermissionDenied()
    form = TalkForm(request.POST or None, instance=talk, site=site)
    if talk:
        form.fields['topics'].disabled = True
        if talk.event.duration:
            form.fields['duration'].help_text = 'Default value if zero: %d min' % talk.duration
        if not talk.is_editable_by(request.user):
            form.fields.pop('track')
            form.fields.pop('duration')
            form.fields.pop('start_date')
            form.fields.pop('room')
        if not talk.is_moderable_by(request.user):
            form.fields['title'].disabled = True
    else:
        form.fields['speakers'].initial = [request.user]
        if not is_orga(request, request.user):
            form.fields.pop('track')
            form.fields.pop('duration')
            form.fields.pop('start_date')
            form.fields.pop('room')
    if request.method == 'POST' and form.is_valid():
        if hasattr(talk, 'id'):
            talk = form.save()
            if request.user == talk.proposer or request.user in talk.speakers.all():
                talk_edited.send(talk.__class__, instance=talk, author=request.user)
            messages.success(request, _('Talk modified successfully!'))
        else:
            form.instance.site = get_current_site(request)
            form.instance.proposer = request.user
            talk = form.save()
            talk_added.send(talk.__class__, instance=talk, author=request.user)
            messages.success(request, _('Talk proposed successfully!'))
        return redirect(talk.get_absolute_url())
    return render(request, 'proposals/talk_edit.html', {
        'form': form,
    })


@login_required
def talk_assign_to_track(request, talk, track):
    talk = get_object_or_404(Talk, slug=talk, site=get_current_site(request))
    if not talk.is_moderable_by(request.user):
        raise PermissionDenied()
    track = get_object_or_404(Track, slug=track, site=get_current_site(request))
    talk.track = track
    talk.save()
    messages.success(request, _('Talk assigned to track successfully!'))
    next_url = request.GET.get('next') or reverse('show-talk', kwargs={'slug': talk.slug})
    return redirect(next_url)


class TalkDetail(LoginRequiredMixin, DetailView):
    def get_queryset(self):
        return Talk.objects.filter(site=get_current_site(self.request)).all()

    def get_context_data(self, **ctx):
        if self.object.is_moderable_by(self.request.user):
            vote = Vote.objects.filter(talk=self.object, user=self.request.user).first()
            ctx.update(edit_perm=True, moderate_perm=True, vote=vote,
                       form_url=reverse('talk-conversation', kwargs={'talk': self.object.slug}))
        else:
            ctx['edit_perm'] = self.object.is_editable_by(self.request.user)
        return super().get_context_data(**ctx)


class TopicMixin(object):
    def get_queryset(self):
        return Topic.objects.filter(site=get_current_site(self.request)).all()


class TopicFormMixin(OnSiteFormMixin):
    form_class = TopicForm


class TopicList(LoginRequiredMixin, TopicMixin, ListView):
    pass


class TopicCreate(OrgaRequiredMixin, TopicMixin, TopicFormMixin, CreateView):
    model = Topic


class TopicUpdate(OrgaRequiredMixin, TopicMixin, TopicFormMixin, UpdateView):
    pass


class TrackFormMixin(OnSiteFormMixin):
    form_class = TrackForm


class TrackMixin(object):
    def get_queryset(self):
        return Track.objects.filter(site=get_current_site(self.request)).all()


class TrackList(LoginRequiredMixin, TrackMixin, ListView):
    pass


class TrackCreate(OrgaRequiredMixin, TrackMixin, TrackFormMixin, CreateView):
    model = Track


class TrackUpdate(OrgaRequiredMixin, TrackMixin, TrackFormMixin, UpdateView):
    pass


@login_required
def vote(request, talk, score):
    talk = get_object_or_404(Talk, site=get_current_site(request), slug=talk)
    if not talk.is_moderable_by(request.user):
        raise PermissionDenied()
    vote, created = Vote.objects.get_or_create(talk=talk, user=request.user)
    vote.vote = int(score)
    vote.save()
    messages.success(request, _('Vote successfully created') if created else _('Vote successfully updated'))
    return redirect(talk.get_absolute_url())


@login_required
def talk_decide(request, talk, accepted):
    site = get_current_site(request)
    talk = get_object_or_404(Talk, site=site, slug=talk)
    if not talk.is_moderable_by(request.user):
        raise PermissionDenied()
    if request.method == 'POST':
        # Does we need to send a notification to the proposer?
        m = request.POST.get('message', '').strip()
        if m:
            participation = Participation.objects.get(site=site, user=talk.proposer)
            conversation = ConversationWithParticipant.objects.get(participation=participation)
            Message.objects.create(conversation=conversation, author=request.user, content=m)
        # Save the decision in the talk's conversation
        conversation = ConversationAboutTalk.objects.get(talk=talk)
        if accepted:
            note = "The talk has been accepted."
        else:
            note = "The talk has been declined."
        Message.objects.create(conversation=conversation, author=request.user, content=note)
        talk.accepted = accepted
        talk.save()
        messages.success(request, _('Decision taken in account'))
        return redirect('show-talk', slug=talk.slug)
    return render(request, 'proposals/talk_decide.html', {
        'talk': talk,
        'accept': accepted,
    })


@staff_required
def speaker_list(request):
    show_filters = False
    site = get_current_site(request)
    filter_form = SpeakerFilterForm(request.GET or None, site=site)
    talks = Talk.objects.filter(site=site)
    # Filtering
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if len(data['status']):
            show_filters = True
            talks = talks.filter(reduce(lambda x, y: x | y, [Q(accepted=dict(STATUS_VALUES)[status]) for status in data['status']]))
        if len(data['topic']):
            show_filters = True
            talks = talks.filter(reduce(lambda x, y: x | y, [Q(topics__slug=topic) for topic in data['topic']]))
        if len(data['track']):
            show_filters = True
            q = Q()
            if 'none' in data['track']:
                data['track'].remove('none')
                q |= Q(track__isnull=True)
            if len(data['track']):
                q |= Q(track__slug__in=data['track'])
            talks = talks.filter(q)
    speakers = Participation.objects.filter(site=site,user__talk__in=talks).order_by('pk').distinct()
    if filter_form.is_valid():
        data = filter_form.cleaned_data
        if len(data['transport']):
            show_filters = True
            q = Q()
            if 'unanswered' in data['transport']:
                data['transport'].remove('unanswered')
                q |= Q(need_transport=None)
            if 'unspecified' in data['transport']:
                data['transport'].remove('unspecified')
                speakers = speakers.annotate(transport_count=Count('transport'))
                q |= Q(need_transport=True, transport_count=0)
            if len(data['transport']):
                q |= (Q(need_transport=True) & Q(reduce(lambda x, y: x | y, [Q(transport__pk=pk) for pk in data['transport']])))
            speakers = speakers.filter(q)
        if len(data['accommodation']):
            show_filters = True
            accommodations = list(map(lambda x: None if x == 'unknown' else x, data['accommodation']))
            speakers = speakers.filter(reduce(lambda x, y: x | y, [Q(accommodation=value) for value in accommodations]))
        if data['sound'] != None:
            show_filters = True
            speakers = speakers.filter(sound=data['sound'])
        if data['transport_booked'] != None:
            show_filters = True
            speakers = speakers.filter(need_transport=True).filter(transport_booked=data['transport_booked'])
        if data['accommodation_booked'] != None:
            show_filters = True
            speakers = speakers.exclude(accommodation=Participation.ACCOMMODATION_NO).filter(accommodation_booked=data['accommodation_booked'])
    return render(request, 'proposals/speaker_list.html', {
        'speaker_list': speakers,
        'filter_form': filter_form,
        'show_filters': show_filters,
    })


@login_required
def user_details(request, username):
    user = get_object_or_404(User, username=username)
    participation = get_object_or_404(Participation, user=user, site=get_current_site(request))
    return render(request, 'proposals/user_details.html', {
        'profile': user.profile,
        'participation': participation,
        'talk_list': allowed_talks(Talk.objects.filter(site=get_current_site(request), speakers=user), request),
    })
