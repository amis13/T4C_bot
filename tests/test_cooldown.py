from bot.ia import Cooldown


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_unknown_user_has_no_cooldown():
    assert Cooldown(10, clock=FakeClock()).remaining(1) == 0


def test_cooldown_counts_from_the_invocation():
    clock = FakeClock()
    cooldown = Cooldown(10, clock=clock)
    cooldown.touch(1)
    assert cooldown.remaining(1) == 10
    clock.now += 4
    assert cooldown.remaining(1) == 6


def test_cooldown_expires():
    clock = FakeClock()
    cooldown = Cooldown(10, clock=clock)
    cooldown.touch(1)
    clock.now += 10
    assert cooldown.remaining(1) == 0


def test_cooldown_is_per_user():
    cooldown = Cooldown(10, clock=FakeClock())
    cooldown.touch(1)
    assert cooldown.remaining(2) == 0


def test_reset_clears_the_cooldown():
    cooldown = Cooldown(10, clock=FakeClock())
    cooldown.touch(1)
    cooldown.reset(1)
    assert cooldown.remaining(1) == 0
    cooldown.reset(1)
