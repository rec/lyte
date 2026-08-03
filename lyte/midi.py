class MidiIn(BaseModel, frozen=True):
    channel: int | None = None
    device_name: str | list[str] | None = None


class Listener(BaseModel):
    patch: Patch
    note_on: mido.Message

    """
    When playing a note, the WX7 sends

    1. A note on with a positive velocity, then:
    2. A series of breath control messages, then:
    3. Either a note off: a note on with zero velocity, when the player stops blowing
    4. Or a new note on: when the player changes fingering while blowing

    A Listener is created

    """
    # Classes optionally override the below
    def breath_control(self, msg: mido.Message) -> None: ...
    def pitch_bend(self, msg: mido.Message) -> None: ...
    def close(self) -> None: ...


class Patch[Config: BaseModel, ListenerClass: type[Listener]](BaseModel):
    config: Config  # frozen
    state: State  # mutable
    listener: ListenerClass | None = None

    def make_listener(self, msg: mido.Message) -> ListenerClass:
        # How to get generic base??

    def receive(self, msg: mido.Message) -> None:
        match msg.type:
            case 'note_on':
                self.listener and self.listener.close()
                self.listener = self.make_listener(self, msg)
            case 'breath_control':
                self.listener and self.listener.breath_control(msg)
            case 'pitch_bend':
                self.listener and self.listener.pitch_bend(msg)
