class Speaker(ndb.Model):
    name            = ndb.StringProperty(required=True)
    intro           = ndb.StringProperty()
    mainEmail       = ndb.StringProperty()
    sessionKeysToAttend = ndb.StringProperty(repeated=True)

class SpeakerForm(messages.Message):
    mame            = messages.StringField(1)
    mainEmail       = messages.StringField(2)
    intro           = messages.StringField(3)
    sessionKeysToAttend = messages.StringField(4, repeated=True)
    websafeKey      = messages.StringField(5)


# - - - Speaker objects - - - - - - - - - - - - - - - - - - -       
    def _copySpeakerToForm(self, speaker):
        sp = SpeakerForm()
        for field in sp.all_fields():
            if hasattr(speaker, field.name):
                setattr(sp, field.name, getattr(speaker, field.name))
            elif field.name == "websafeKey":
                setattr(sp, field.name, speaker.key.urlsafe())
        sp.check_initialized()
        return sp

    def _createSpeaker(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
                raise endpoints.BadRequestException("Session 'name' field required")
        # copy SpeakerForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

    @endpoints.method(SpeakerForm, SpeakerForm, path='speaker',
            http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new session."""
        return self._createSpeaker(request)