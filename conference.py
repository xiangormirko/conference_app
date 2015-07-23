#!/usr/bin/env python


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize

from models import Session
from models import SessionForm
from models import SessionForms
from models import Wishlist
from models import WishlistForm

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKERS"
SPEAKER_TPL = ('Check out our feature speaker %s hosting the'
               'following sessions %s, and the latest %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

# Default values and conversions
DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

STANDARDS = {
    "highlights": "highlights",
    "speaker": "conference speaker",
    "duration": "as conference",
    "typeOfSession": ["Default", "Type"],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS = {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

# ResourceContainers for the various functions
CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1, required=True),
    typeOfSession=messages.StringField(2)
)

SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

WISH_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeKey=messages.StringField(1),
)

TIME_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    startTime=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(
    name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID,
                        ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE]
    )
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object,
        returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name'"
                                                "field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing
        # (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects;
        # set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10],
                                                  "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10],
                                                "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(
            params={
                'email': user.email(),
                'conferenceInfo': repr(request)
                },
            url='/tasks/send_confirmation_email'
            )
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey
                )

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(
            ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference'
            )
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(
            CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference'
            )
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(
            CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference'
            )
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey
                )
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(
            message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated'
            )
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(conf, getattr(prof, 'displayName'))
                for conf in confs
                ]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"],
                                                   filtr["operator"],
                                                   filtr["value"]
                                                   )
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {
                field.name: getattr(f, field.name)
                for field in f.all_fields()
                }

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains"
                                                    "invalid field"
                                                    "or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been
                # used in previous filters
                # disallow the filter if inequality was performed
                # on a different field before
                # track the field on which the inequality operation
                # is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality"
                                                        "filter is allowed on"
                                                        "only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(
            ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences'
            )
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [
            (ndb.Key(Profile, conf.organizerUserId))
            for conf in conferences
            ]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(
                    conf, names[conf.organizerUserId]
                    ) for conf in conferences]
        )

# - - - Session objects - - - - - - - - - - - - - - - - - - -
    # Copy Sessions to the relative form
    def _copySessionToForm(self, session):
        """Copy relevant fields from Conference to ConferenceForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if (field.name.endswith('date') or
                        field.name.endswith('startTime')):
                    setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf

    # Create a session object
    def _createSessionObject(self, request):
            """Create or update Session object,"""
            """returning SessionForm/request."""
            # preload necessary data items
            user = endpoints.get_current_user()
            if not user:
                raise endpoints.UnauthorizedException('Authorization required')
            user_id = getUserId(user)

            if not request.name:
                raise endpoints.BadRequestException(
                    "Session 'name' field required"
                    )

            conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
            # check that conference exists
            if not conf:
                raise endpoints.NotFoundException(
                    'No conference found with key: %s'
                    % request.websafeConferenceKey
                    )

            if user_id != conf.organizerUserId:
                raise endpoints.ForbiddenException(
                    'Only the owner can add sessions.')

            # copy SessionForm/ProtoRPC Message into dict
            data = {
                field.name: getattr(request, field.name)
                for field in request.all_fields()
                }

            # add default values for those missing
            # (both data model & outbound Message)
            for st in STANDARDS:
                if data[st] in (None, []):
                    data[st] = STANDARDS[st]
                    setattr(request, st, STANDARDS[st])

            # convert dates from strings to Date objects;
            # set month based on start_date
            if data['date']:
                data['date'] = datetime.strptime(
                    data['date'][:10], "%Y-%m-%d").date()
            if data['startTime']:
                data['startTime'] = datetime.strptime(
                    data['startTime'][:5], "%H:%M").time()

            # generate Profile Key based on user ID and Conference
            # ID based on Profile key get Conference key from ID
            c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
            if not c_key:
                raise endpoints.NotFoundException(
                    'No conference found with key: %s'
                    % request.websafeConferenceKey
                    )
            s_id = Session.allocate_ids(size=1, parent=c_key)[0]
            s_key = ndb.Key(Session, s_id, parent=c_key)
            data['key'] = s_key

            del data['websafeConferenceKey']
            del data['websafeKey']

            Session(**data).put()

            # Converting a ProtoRPC Listfield to string
            speakerName = str(data['speaker'])
            lenght = len(speakerName)
            speakerName = speakerName[3:lenght-2]

            speakerSessions = Session.query(
                Session.speaker == speakerName
                ).fetch(projection=[Session.name])
            # Join the name of the speaker
            # and the conference names in a message
            if len(speakerSessions) > 1:
                speaker = SPEAKER_TPL % (
                    speakerName, ', '.join(
                        speaker.name for speaker in speakerSessions
                        ), data['name']
                    )
                # set memcache with key
                memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, speaker)
                print "A new speaker has been added"
                "in featured speakers memcache"

            return request

    @endpoints.method(
            SessionForm, SessionForm, path='session',
            http_method='POST', name='createSession'
            )
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

    @endpoints.method(
            SESSION_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='getSession'
            )
    def getConferenceSessions(self, request):
        """Return all sessions for given conference"""
        """(by websafeConferenceKey)."""
        # get Session object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey
                )
        sessions = Session.query(ancestor=conf.key).fetch()
        # return ConferenceForm
        return SessionForms(
                items=[
                    self._copySessionToForm(session) for session in sessions
                    ]
            )

    @endpoints.method(
            SESSION_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions/{typeOfSession}',
            http_method='GET', name='getSessionByType'
            )
    def getConferenceSessionsByType(self, request):
        """Return all sessions for given conference"""
        """(by websafeConferenceKey)."""
        # get Session object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        print request.typeOfSession
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey
                )
        sessions = Session.query(
            Session.typeOfSession == request.typeOfSession, ancestor=conf.key
            ).fetch()
        # return ConferenceForm
        print sessions
        return SessionForms(
                items=[
                    self._copySessionToForm(session) for session in sessions
                    ]
            )

    @endpoints.method(
            SPEAKER_GET_REQUEST, SessionForms,
            path='conference/sessions/{speaker}',
            http_method='GET', name='getSessionBySpeaker'
            )
    def getConferenceSessionsBySpeaker(self, request):
        """Return all sessions for given speaker (by Speaker name)."""
        # get Session object from request; bail if not found
        sessions = Session.query(Session.speaker == request.speaker).fetch()
        # return ConferenceForm
        print sessions
        return SessionForms(
                items=[
                    self._copySessionToForm(session) for session in sessions
                    ]
            )
# - - - Wishlist objects - - - - - - - - - - - - - - - - - - -

    def _getWishlistFromUser(self):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        w_key = ndb.Key(Wishlist, user_id)
        wishlist = w_key.get()

        if not wishlist:
            wishlist = Wishlist(
                    key=w_key,
                    ownerId=user_id,
                    public=True,
                )
            wishlist.put()
        print wishlist

        return wishlist

    def _copyWishlistToForm(self, wish):
        wl = WishlistForm()
        for field in wl.all_fields():
            if hasattr(wish, field.name):
                setattr(wl, field.name, getattr(wish, field.name))
        wl.check_initialized()
        return wl

    def _doWishlist(self, save_request=None):
        wish = self._getWishlistFromUser()
        mylist = self._copyWishlistToForm(wish)

        if save_request:
            for field in ('sessionsInList', 'public'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(wish, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        wish.put()

        # return ProfileForm
        return self._copyWishlistToForm(wish)

    def _addSessionToWishlist(self, request, reg=True):
        """Add a session to a user wishlist."""
        retval = None
        wish = self._getWishlistFromUser()  # get user Wishlist

        # get conference; check that it exists
        sk = request.websafeKey
        session = ndb.Key(urlsafe=sk).get()
        if not wish:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if sk in wish.sessionsInList:
                raise ConflictException(
                    "You already have this session in your wishlist")
            # check if the object that has been entered is a session
            for field in ('maxAttendees', 'seatsAvailable', 'city'):
                if hasattr(session, field):
                    raise ConflictException(
                        "It appears the object inserted is not a session")

            # add session to list
            wish.sessionsInList.append(sk)
            retval = True

        # unregister
        else:
            # check if user already registered
            if sk in wish.sessionsInList:

                # remove session from list
                wish.sessionsInList.remove(sk)
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        wish.put()
        return BooleanMessage(data=retval)

    @endpoints.method(
            message_types.VoidMessage, WishlistForm,
            path='wishlist', http_method='GET', name='getWishlist'
            )
    def getWishlist(self, request):
        """Return user wishlist."""
        return self._doWishlist()

    @endpoints.method(
            WishlistForm, WishlistForm,
            path='wishlist', http_method='POST', name='saveWishlist'
            )
    def saveWishlist(self, request):
        """Update & return user wishlist."""
        return self._doWishlist(request)

    @endpoints.method(
            WISH_GET_REQUEST, BooleanMessage,
            path='wishlist/{websafeKey}',
            http_method='POST', name='addSessionToWishlist'
            )
    def addSessionToWishlist(self, request):
        """Add given session to wishlist."""
        return self._addSessionToWishlist(request)

    @endpoints.method(
            message_types.VoidMessage, SessionForms,
            path='sessions/wishlisted',
            http_method='GET', name='getSessionsInWishlist'
            )
    def getSessionsInWishlist(self, request):
        """Get list of sessions in the user's wishlist."""
        prof = self._getProfileFromUser()  # get user Profile
        wishlist = self._getWishlistFromUser()  # get wishlist from user
        session_keys = [
            ndb.Key(urlsafe=wsk) for wsk in wishlist.sessionsInList
            ]
        sessions = ndb.get_multi(session_keys)

        # return set of SessionForm objects
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )
# - - - Custom Queries - - - - - - - - - - - - - - - - - - -
    # To get a list of sessions with availble seats in the
    # parent conference. 
    @endpoints.method(
            message_types.VoidMessage, SessionForms,
            path='sessions/available',
            http_method='GET', name='getSessionsWithSeats'
            )
    def getSessionsWithSeats(self, request):
        """Get list of sessions with available"""
        """seats in the respective conference."""
        confs = Conference.query(Conference.seatsAvailable >= 1).fetch()
        if not confs:
            raise endpoints.NotFoundException(
                'No conference found with available seats')
        confs = iter(confs)
        confkeys = [conf.key.urlsafe() for conf in confs]
        sessions = []
        for conf in confkeys:
            results = Session.query(ancestor=ndb.Key(urlsafe=conf)).fetch()
            for result in results:
                sessions.append(result.key.urlsafe())

        session_keys = [ndb.Key(urlsafe=wsk) for wsk in sessions]
        print session_keys
        sessions = ndb.get_multi(session_keys)
        return SessionForms(
                items=[
                    self._copySessionToForm(session)
                    for session in sessions
                    ]
            )
    # Useful to get sessions happing after a given time
    @endpoints.method(
            TIME_GET_REQUEST, SessionForms,
            path='sessions/afterTime/{startTime}',
            http_method='GET', name='getSessionsAfterTime'
            )
    def getSessionsAfterTime(self, request):
        """Get list of sessions after a given time"""
        # insert time in a 4 digit 24h format without colon

        time = request.startTime[:2] + ":" + request.startTime[2:]
        givenTime = datetime.strptime(time[:5], "%H:%M").time()
        sessions = Session.query(Session.startTime > givenTime).fetch()

        # return set of SessionForm objects
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(
                        pf, field.name, getattr(
                            TeeShirtSize, getattr(prof, field.name)
                            )
                        )
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore,"""
        """creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(
            message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile'
            )
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(
            ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile'
            )
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(
            message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement'
            )
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or ""
            )

# - - - Feature Speaker - - - - - - - - - - - - - - - - - -
    # Method to get a feature speaker from memecache
    @endpoints.method(
            message_types.VoidMessage, StringMessage,
            path='session/featuredSpeaker/get',
            http_method='GET', name='getFeaturedSpeaker'
            )
    def getFeaturedSpeaker(self, request):
        """Return featured speaker from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or ""
            )


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(
            message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend'
            )
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [
            ndb.Key(urlsafe=wsck)
            for wsck in prof.conferenceKeysToAttend
            ]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [
            ndb.Key(Profile, conf.organizerUserId)
            for conf in conferences
            ]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[
                self._copyConferenceToForm(conf, names[conf.organizerUserId])
                for conf in conferences
                ]
        )

    @endpoints.method(
            CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference'
            )
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(
            CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference'
            )
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(
            message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground'
            )
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


api = endpoints.api_server([ConferenceApi])  # register API
