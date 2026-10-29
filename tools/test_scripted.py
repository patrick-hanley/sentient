"""Director behaviour for IMU reactions, parent cues, the leak guard and parent notes (fake hub, voices and model)."""
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_latency as TL  # noqa: E402
from brain import scripted  # noqa: E402
from brain.director import Director  # noqa: E402


class Voices(TL.FakeVoices):
    def render(self, toy, text, persist=False):
        return super().render(toy, text)


class Hub(TL.FakeHub):
    def __init__(self, toys=("dyno", "sage", "penny")):
        super().__init__(toys)
        self.stopped = 0

    def stop_all(self):
        self.stopped += 1


def make(backend=None, toys=("dyno", "sage", "penny")):
    hub, voices = Hub(toys), Voices()
    eyes = types.SimpleNamespace(views={}, scene_text=lambda: "nothing in particular")
    d = Director(hub, voices, eyes, backend or TL.Backend(), {})
    return d, hub, voices


def wait(cond, secs=3.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class ImuReactionTests(unittest.TestCase):
    def test_sleep_gets_two_friend_lines_once_per_episode_and_wake_is_quiet_when_both_already_spoke(self):
        d, hub, voices = make()
        d.on_imu("dyno", "sleep")
        self.assertTrue(wait(lambda: len(hub.played) == 2))
        self.assertNotIn("dyno", hub.played)               # the moved toy made its own sound from flash
        d.on_imu("dyno", "sleep")                           # a second sleep in the same episode is ignored
        time.sleep(0.3)
        self.assertEqual(len(hub.played), 2)
        d._reactions.clear(); d.imu["dyno"]["last"].clear()
        d.on_imu("dyno", "woken")                           # both friends already commented: nobody comments twice
        time.sleep(0.3)
        self.assertEqual(len(hub.played), 2)
        self.assertFalse(d.imu["dyno"]["asleep"])

    def test_woken_without_sleep_is_ignored_and_unknown_events_too(self):
        d, hub, _ = make()
        d.on_imu("sage", "woken"); d.on_imu("sage", "explode"); d.on_imu("nobody", "tossed")
        time.sleep(0.3)
        self.assertEqual(hub.played, [])

    def test_a_flurry_of_tosses_becomes_one_reaction(self):
        d, hub, _ = make()
        d.on_imu("dyno", "tossed"); d.on_imu("sage", "tossed"); d.on_imu("penny", "spun")
        self.assertTrue(wait(lambda: len(hub.played) >= 1))
        time.sleep(0.5)
        self.assertEqual(len(hub.played), 2)                # one reaction (two friends), the rest were dropped
        d.on_imu("dyno", "shaken", force=True)              # the dashboard test button bypasses the limits
        self.assertTrue(wait(lambda: len(hub.played) == 3))

    def test_no_reaction_while_a_child_is_speaking_or_a_turn_is_running(self):
        d, hub, _ = make()
        d.segs = {"dyno": types.SimpleNamespace(active=True)}
        with patch.object(Director, "play_scripted", wraps=d.play_scripted) as ps:
            d.on_imu("sage", "tossed")
            time.sleep(0.4)
        self.assertEqual(hub.played, [])
        d.segs = {}
        d.paused = True
        d._reactions.clear()
        d.on_imu("sage", "dropped")
        time.sleep(0.2)
        self.assertEqual(hub.played, [])

    def test_friend_lines_name_the_moved_toy_and_vary(self):
        d, hub, voices = make()
        seen = set()
        for _ in range(12):
            d._reactions.clear(); d.imu.clear()
            voices.rendered.clear()
            d.on_imu("penny", "tossed", force=True)
            wait(lambda: len(voices.rendered) >= 2)
            seen.update(t for _, t in voices.rendered)
        self.assertGreater(len(seen), 3)
        self.assertTrue(all("{" not in t for t in seen))


class CueTests(unittest.TestCase):
    def test_known_cue_plays_fixed_lines_for_every_toy_without_gemma(self):
        class NoLlm(TL.Backend):
            def stream(self, *a, **k):
                raise AssertionError("a tier-1 cue must not call Gemma")
        d, hub, voices = make(NoLlm())
        r = d.cue("time for dinner")
        self.assertEqual((r["ok"], r["mode"], r["cue"]), (True, "fixed", "dinner"))
        self.assertTrue(wait(lambda: len(hub.played) == 3))
        self.assertEqual(set(hub.played), {"dyno", "sage", "penny"})
        said = " ".join(t for _, t in voices.rendered).lower()
        self.assertNotIn("time for dinner", said)           # the toys react, they never repeat the sentence
        self.assertFalse(d.cue_hold.is_set())

    def test_chip_id_wins_and_nothing_is_queued_when_no_toy_is_online(self):
        d, hub, _ = make(toys=())
        self.assertFalse(d.cue("", "bath")["ok"])
        self.assertEqual(hub.played, [])

    def test_freeform_cue_goes_to_gemma_and_a_leaky_line_is_replaced(self):
        class Llm(TL.Backend):
            def complete(self, prompt, system, image=None, max_tokens=200):
                self.prompt = prompt
                return "DYNO: Your mum said it is raining!\nSAGE: Rain, rain, stay inside and read!\nPENNY: Splash! Hee hee!"
        llm = Llm()
        d, hub, voices = make(llm)
        r = d.cue("it is raining, no bikes today")
        self.assertEqual((r["ok"], r["mode"]), (True, "gemma"))
        self.assertTrue(wait(lambda: len(hub.played) == 3))
        said = [t for _, t in voices.rendered]
        self.assertIn(scripted.SAFE_DEFLECT["dyno"], said)
        self.assertFalse(any("your mum" in t.lower() for t in said))
        self.assertIn("Do NOT repeat it word for word", llm.prompt)

    def test_freeform_cue_needs_gemma_and_empty_text_is_rejected(self):
        d, hub, _ = make()   # the plain Backend has no complete()
        self.assertFalse(d.cue("it is raining")["ok"])
        self.assertFalse(d.cue("   ")["ok"])

    def test_cue_pauses_a_running_reply_at_a_line_boundary_then_it_resumes(self):
        gate = threading.Event()

        class Slow(TL.Backend):
            def stream(self, *a, **k):
                yield "HEARD: hi\nDYNO: First line here.\n"
                gate.wait(3)
                yield "SAGE: Second line here."
        d, hub, voices = make(Slow())
        t = threading.Thread(target=d._turn, kwargs={"event": "test"}, daemon=True)
        t.start()
        self.assertTrue(wait(lambda: hub.played == ["dyno"]))
        d.cue("", "snack")
        self.assertTrue(wait(lambda: len(hub.played) == 4))        # dyno's line, then the three cue lines
        gate.set()
        t.join(5)
        self.assertEqual(hub.played[0], "dyno")
        self.assertEqual(hub.played[-1], "sage")                   # the reply resumed after the cue
        self.assertEqual(len(hub.played), 5)

    def test_interrupt_drops_the_rest_of_a_reply(self):
        gate = threading.Event()

        class Slow(TL.Backend):
            def stream(self, *a, **k):
                yield "HEARD: hi\nDYNO: First line here.\n"
                gate.wait(3)
                yield "SAGE: Second line here.\nPENNY: Third line here."
        d, hub, _ = make(Slow())
        t = threading.Thread(target=d._turn, kwargs={"event": "test"}, daemon=True)
        t.start()
        self.assertTrue(wait(lambda: hub.played == ["dyno"]))
        d.interrupt()
        self.assertEqual(hub.stopped, 1)
        gate.set()
        t.join(5)
        self.assertEqual(hub.played, ["dyno"])


class TurnTests(unittest.TestCase):
    def test_a_toy_line_that_quotes_a_parent_is_replaced_once(self):
        class Leaky(TL.Backend):
            def stream(self, *a, **k):
                yield "HEARD: hi\nDYNO: Your dad said you have a spelling test!\nSAGE: Mum told me you love space.\n"
        d, hub, voices = make(Leaky())
        d._turn(event="x")
        self.assertEqual([t for _, t in voices.rendered], [scripted.SAFE_DEFLECT["dyno"]])

    def test_parent_notes_reach_the_model_but_never_the_log(self):
        seen = {}

        class Spy(TL.Backend):
            def stream(self, prompt, **k):
                seen["prompt"] = prompt
                yield "HEARD: -\nDYNO: Hi!\n"
        d, hub, _ = make(Spy())
        d.parent = types.SimpleNamespace(notes_block=lambda: "[PRIVATE NOTES: x] loves zebras; spelling test Friday")
        with self.assertLogs("director", level="INFO") as cm:
            d._turn(event="Nobody has talked for a while.")
        self.assertIn("loves zebras", seen["prompt"])
        self.assertNotIn("zebras", "\n".join(cm.output))
        self.assertNotIn("PRIVATE NOTES", "\n".join(cm.output))

    def test_event_can_exclude_the_moved_toy_from_speaking(self):
        class Echo(TL.Backend):
            def stream(self, prompt, **k):
                yield "HEARD: -\nDYNO: Should not speak.\nSAGE: I can speak.\n"
        d, hub, voices = make(Echo())
        d._turn(event={"text": "Dyno was tossed.", "exclude": ["dyno"]})
        self.assertEqual(hub.played, ["sage"])


class HubMessageTests(unittest.TestCase):
    def hub(self):
        from brain.atoms import Atom, AtomHub
        h = object.__new__(AtomHub)
        a = Atom(mac="AA", ip="10.0.0.5", toy="dyno")
        h.atoms, h.by_ip, h.by_addr = {"dyno": a}, {"10.0.0.5": a}, {}
        h.talking, h.mute_until, h.force_mute = None, 0.0, False
        h.on_playback, h.on_imu, h.monitor = None, None, None
        h.events = []
        h.on_imu = lambda toy, ev: h.events.append((toy, ev))
        return h, a

    def test_imu_messages_reach_the_director_and_calibration_updates_the_flag(self):
        h, a = self.hub()
        h._handle(b"IMU tossed", "10.0.0.5", 5006)
        h._handle(b"IMU calibrated", "10.0.0.5", 5006)
        self.assertEqual(h.events, [("dyno", "tossed")])
        self.assertEqual(a.flags["imu"], "2")
        h._handle(b"IMU provisional", "10.0.0.5", 5006)
        self.assertEqual(a.flags["imu"], "1")

    def test_a_toys_own_clip_mutes_the_mics_per_toy_and_a_brain_play_cannot_unmute_it(self):
        h, a = self.hub()
        h.muted = types.MethodType(__import__("brain.atoms", fromlist=["AtomHub"]).AtomHub.muted, h)
        self.assertFalse(h.muted())
        h._handle(b"PLAYING 123", "10.0.0.5", 5006)         # nobody told this toy to talk: it is playing from its own flash
        self.assertTrue(h.muted())
        self.assertGreater(a.local_until, time.time() + 5)
        h.mute_until = time.time() + 0.4                    # another toy's brain-initiated line finishes: its tail must not unmute
        self.assertTrue(h.muted())
        h._handle(b"PLAYED 456", "10.0.0.5", 5006)
        self.assertLess(a.local_until, time.time() + 2)     # bounded, not a minute
        h.talking = "dyno"                                   # a brain-initiated line manages the mute itself
        a.local_until = 0.0
        h._handle(b"PLAYING 789", "10.0.0.5", 5006)
        self.assertEqual(a.local_until, 0.0)


class ReviewFixTests(unittest.TestCase):
    def test_changing_the_notes_resets_the_toys_conversation(self):
        resets = []

        class Spy(TL.Backend):
            def reset_conversation(self):
                resets.append(1)
        d, hub, _ = make(Spy())
        notes = ["", "[PRIVATE NOTES] loves space", "[PRIVATE NOTES] loves space", "[PRIVATE NOTES] loves trains", ""]
        for n in notes:
            d.parent = types.SimpleNamespace(notes_block=lambda n=n: n)
            d._turn(event="x")
        self.assertEqual(len(resets), 3)   # none at first, then: notes appear, notes change, notes disappear (the repeat is left alone)

    def test_a_typed_cue_is_never_written_to_the_disk_cache_but_a_chip_cue_is(self):
        class Llm(TL.Backend):
            def complete(self, prompt, system, image=None, max_tokens=200):
                return "DYNO: Rain, rain!\nSAGE: Cozy day.\nPENNY: Splash!"
        d, hub, voices = make(Llm())
        flags = []
        orig = voices.render
        voices.render = lambda toy, text, persist=False: (flags.append(persist), orig(toy, text))[1]
        d.cue("it is raining")
        self.assertTrue(wait(lambda: len(flags) == 3))
        self.assertEqual(flags, [False, False, False])
        flags.clear(); hub.played.clear()
        d.cue("", "snack")
        self.assertTrue(wait(lambda: len(flags) == 3))
        self.assertEqual(flags, [True, True, True])

    def test_urgent_cue_does_not_release_a_lock_it_does_not_hold(self):
        d, hub, _ = make()
        d._turn_lock.acquire()                  # a running turn holds it for longer than the cue waits
        t = threading.Thread(target=d._run_cue, args=([("dyno", "Hi!")], "", ["dyno"], True), daemon=True)
        t.start()
        t.join(6)
        self.assertFalse(t.is_alive())
        self.assertTrue(d._turn_lock.locked())  # still ours: the cue gave up waiting and did not release it
        d._turn_lock.release()                  # and our own release works (no RuntimeError)

    def test_a_lost_wake_up_cannot_silence_later_sleep_reactions(self):
        d, hub, _ = make()
        d.on_imu("dyno", "sleep")
        self.assertTrue(wait(lambda: len(hub.played) == 2))
        d.paused = True                          # the wake-up arrives while the brain is paused: it used to leave asleep=True
        d.on_imu("dyno", "woken")
        self.assertFalse(d.imu["dyno"]["asleep"])
        d.paused = False
        d._reactions.clear(); d.imu["dyno"]["last"].clear()
        d.on_imu("dyno", "sleep")
        self.assertTrue(wait(lambda: len(hub.played) == 4))
        d.imu["dyno"]["since"] -= 4000           # and a wake-up that never comes at all expires
        d._reactions.clear(); d.imu["dyno"]["last"].clear()
        d.on_imu("dyno", "sleep")
        self.assertTrue(wait(lambda: len(hub.played) == 6))

    def test_a_toys_own_clip_does_not_mark_the_running_turns_latency(self):
        d, hub, _ = make()
        trace = types.SimpleNamespace(marks=[], mark=lambda *a, **k: trace.marks.append(a[0]), events={})
        d.active_trace = trace
        hub.talking = "sage"
        d._atom_playback("dyno", "PLAYING", 1.0)   # dyno yelled from its own flash while sage was speaking for the turn
        self.assertEqual(trace.marks, [])
        d._atom_playback("sage", "PLAYING", 1.0)
        self.assertEqual(trace.marks, ["atom_first_sample_ms"])


class ImuClipSyncTests(unittest.TestCase):
    def setup_fakes(self, tmp, used=100_000):
        from brain import config as cfg
        cfg_patch = patch.object(cfg, "DATA", Path(tmp))
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        voices = Voices()
        voices.clip_id = lambda toy, text: "c" + str(abs(hash((toy, text))))[:10]
        atom = types.SimpleNamespace(fs=(1_500_000, used), flags={"fw": "toy-client-3.5"}, clips={})
        hub = types.SimpleNamespace(atoms={"dyno": atom}, cleared=0, put=[])
        hub.list_clips = lambda toy: dict(atom.clips)

        def clear(toy):
            hub.cleared += 1
            atom.clips.clear()
            atom.fs = (atom.fs[0], 0)
        hub.clear_clips = clear

        def put(toy, name, pcm):
            hub.put.append(name)
            atom.clips[name] = len(pcm) / 32000
            atom.fs = (atom.fs[0], atom.fs[1] + len(pcm) // 2)
            return True
        hub.put_clip = put
        return hub, voices, atom

    def test_missing_motion_clips_are_uploaded_and_a_second_sync_uploads_nothing(self):
        import tempfile
        from brain.main import sync_imu_clips
        with tempfile.TemporaryDirectory() as tmp:
            hub, voices, atom = self.setup_fakes(tmp)
            have = sync_imu_clips(hub, voices, "dyno", {})
            self.assertEqual(sorted(hub.put), sorted(f"imu_{e}" for e in scripted.IMU_EVENTS))
            self.assertEqual(hub.cleared, 0)
            hub.put.clear()
            sync_imu_clips(hub, voices, "dyno", have)
            self.assertEqual(hub.put, [])                    # nothing changed: nothing re-sent

    def test_changed_voice_text_reuploads_only_that_clip(self):
        import tempfile
        from brain.main import sync_imu_clips
        with tempfile.TemporaryDirectory() as tmp:
            hub, voices, atom = self.setup_fakes(tmp)
            have = sync_imu_clips(hub, voices, "dyno", {})
            hub.put.clear()
            with patch.dict(scripted.IMU_LOCAL["tossed"], {"dyno": "Whee, higher!"}):
                sync_imu_clips(hub, voices, "dyno", have)
            self.assertEqual(hub.put, ["imu_tossed"])

    def test_a_full_flash_is_cleared_once_to_make_room(self):
        import tempfile
        from brain.main import sync_imu_clips
        with tempfile.TemporaryDirectory() as tmp:
            hub, voices, atom = self.setup_fakes(tmp, used=1_490_000)
            atom.clips["c_old_sound"] = 2.0
            sync_imu_clips(hub, voices, "dyno", dict(atom.clips))
            self.assertEqual(hub.cleared, 1)
            self.assertEqual(len(hub.put), len(scripted.IMU_EVENTS))
            self.assertNotIn("c_old_sound", atom.clips)

    def test_firmware_version_gate(self):
        from brain.main import _fw_at_least
        self.assertTrue(_fw_at_least({"fw": "toy-client-3.5"}, 3, 5))
        self.assertTrue(_fw_at_least({"fw": "toy-client-3.10"}, 3, 5))
        self.assertFalse(_fw_at_least({"fw": "toy-client-3.4"}, 3, 5))
        self.assertFalse(_fw_at_least({"fw": "toy-client-3"}, 3, 5))
        self.assertFalse(_fw_at_least({}, 3, 5))


if __name__ == "__main__":
    unittest.main(verbosity=2)
