import sys

p = sys.argv[1]
t = open(p).read()


def rep(old, new):
    global t
    assert t.count(old) == 1, old[:60]
    t = t.replace(old, new)


assert 'D21 local' not in t
rep("""    def begin_sleep_record(self):
        self.sleep_record += 1""", """    def button_wakes(self):
        \"\"\"D21 local: wake events of the SMC buttons. The kernel swallows the KEY_POWER of the
        press that ends a sleep (macsmc-input wakeup_mode), so that press shows only here.\"\"\"
        total = 0
        for source in Path('/sys/class/wakeup').glob('*'):
            try:
                if (source / 'name').read_text().strip() == 'macsmc-input':
                    total += int((source / 'event_count').read_text())
            except (OSError, ValueError):
                pass
        return total

    def begin_sleep_record(self):
        self.wakes_before = self.button_wakes()
        self.sleep_record += 1""")
rep("""        self.feed('sleep-aborted' if result == 'aborted' else 'sleep-ended')""",
    """        self.feed('sleep-aborted' if result == 'aborted' else 'sleep-ended')
        # D21 local: a button ended (or aborted) the sleep, but its key never arrived.
        pressed = self.button_wakes() - getattr(self, 'wakes_before', 0)
        if result != 'not-entered' and pressed > 0:
            log(f'sleep-ended by a button: {pressed} wake event(s)')
            self.feed('power')""")
open(p, 'w').write(t)
