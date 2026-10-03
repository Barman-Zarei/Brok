from __future__ import annotations

import enum


class AvatarState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    TYPING = "typing"
    CODING = "coding"
    WORKING = "working"
    SPEAKING = "speaking"
    HAPPY = "happy"
    CONFUSED = "confused"
    ERROR = "error"
    SUCCESS = "success"
    SLEEPING = "sleeping"
    NOTIFICATION = "notification"


#: Higher wins when two sources request a state at once (an error must not be hidden by "typing").
PRIORITY = {
    AvatarState.SLEEPING: 0, AvatarState.IDLE: 1, AvatarState.HAPPY: 2, AvatarState.LISTENING: 3,
    AvatarState.TYPING: 4, AvatarState.WORKING: 5, AvatarState.CODING: 5, AvatarState.THINKING: 6,
    AvatarState.SPEAKING: 7, AvatarState.CONFUSED: 8, AvatarState.SUCCESS: 8, AvatarState.NOTIFICATION: 9,
    AvatarState.ERROR: 10,
}
#: Transient states that fall back to IDLE after N seconds.
TRANSIENT_SECONDS = {AvatarState.HAPPY: 3.0, AvatarState.SUCCESS: 3.0, AvatarState.ERROR: 5.0,
                     AvatarState.CONFUSED: 4.0, AvatarState.NOTIFICATION: 6.0}
