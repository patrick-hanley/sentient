"""No models or devices required: streaming, scheduling, timing and failure tests."""
from __future__ import annotations

import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from brain import config
from brain.atoms import Atom, AtomHub, encode_for_atom
from brain.director import Director, ReplyLines
from brain.latency import TurnTrace
from brain.llm import GenieXBackend, LlamaCppBackend, LiteRTBackend, _sse, _text, make_backend
from brain.pipeline import SpeechPipeline
from brain.vad import Segmenter, Utterance, arbitrate


class FakeVoices:
    def __init__(self):
        self.rendered = []

    def render(self, toy, text):
        self.rendered.append((toy, text))
        return b"\0\0" * 320


class FakeHub:
    def __init__(self, toys=("dyno", "sage")):
        self.toys = list(toys)
        self.response_active = threading.Event()
        self.played = []
        self.started = threading.Event()

    def online(self):
        return self.toys.copy()

    def play(self, toy, pcm, *, on_dispatch=None, raise_on_error=False):
        if on_dispatch:
            on_dispatch()
        self.played.append(toy)
        self.started.set()
        return .02


class Backend:
    hears_audio = True

    def stream(self, *_, **__):
        yield "HEARD: hello\nDYNO: Hello, friend!\n"
        yield "SAGE: Shall we play?"


def make_director(backend=None, hub=None, voices=None):
    hub, voices = hub or FakeHub(), voices or FakeVoices()
    eyes = types.SimpleNamespace(views={}, scene_text=lambda: "DYNO sees the child.")
    return Director(hub, voices, eyes, backend or Backend(), {})


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.lines, self.heard = [], []
        self.parser = ReplyLines(["dyno", "sage"], lambda *x: self.lines.append(x), self.heard.append)

    def test_partial_tokens_are_not_spoken(self):
        self.parser.feed("HEA")
        self.parser.feed("RD: hi\nDY")
        self.parser.feed("NO: Hello")
        self.assertEqual(self.lines, [])
        self.parser.feed(" there!\n")
        self.assertEqual(self.lines, [("dyno", "Hello there!")])
        self.assertEqual(self.heard, ["hi"])

    def test_empty_heard_header_still_streams(self):
        # Idle-banter turns have no child speech; Gemma writes a bare "HEARD:".
        self.parser.feed("HEARD:\nDYNO: Let's play!\n")
        self.assertEqual(self.lines, [("dyno", "Let's play!")])

    def test_thought_blocks_unknown_toys_and_extra_lines_are_ignored(self):
        for delta in ["<thi", "nk>\nHEARD: draft\nDYNO: secret\n</think>\n", "HEARD: hi\n",
                      "PENNY: offline\nDYNO: First.\nSAGE: Second.\nDYNO: Third.\n"]:
            self.parser.feed(delta)
        self.parser.finish()
        self.assertEqual(self.lines, [("dyno", "First."), ("sage", "Second.")])
        self.assertEqual(self.heard, ["hi"])

    def test_eof_flushes_only_a_labelled_line(self):
        self.parser.feed("DYNO: This has no header.")
        self.assertFalse(self.lines)
        self.parser.finish()
        self.assertEqual(self.lines, [("dyno", "This has no header.")])
        parser = ReplyLines(["dyno"], lambda *x: self.fail("unlabelled text was spoken"), lambda _: None)
        parser.feed("Here are my private notes without any toy labels.")
        parser.finish()

    def test_later_draft_cannot_add_a_second_answer(self):
        self.parser.feed("HEARD: hi\nDYNO: Hello.\nHEARD: revised\nSAGE: A different answer.\n")
        self.assertEqual(self.lines, [("dyno", "Hello.")])

    def test_prompt_label_echo_is_removed_from_spoken_text(self):
        self.parser.feed("HEARD: hi\nDYNO: HEARD BY DYNO: Hello there.\n")
        self.assertEqual(self.lines, [("dyno", "Hello there.")])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        config.apply_latency_profile("responsive")

    def tearDown(self):
        config.apply_latency_profile("responsive")

    def test_first_audio_is_dispatched_before_model_finishes(self):
        hub = FakeHub()

        class GatedBackend(Backend):
            def stream(self, *args, **kwargs):
                yield "HEARD: hello\nDYNO: Hello, friend!\n"
                if not hub.started.wait(2):
                    raise AssertionError("Model waited for playback but nothing was dispatched")
                yield "SAGE: Shall we play?"
        director = make_director(GatedBackend(), hub)
        director._turn(event="hello")
        milestones = director.last_trace["milestones_ms"]
        self.assertEqual(director.last_trace["status"], "ok")
        self.assertLess(milestones["first_audio_post_ms"], milestones["model_done_ms"])
        self.assertEqual(hub.played, ["dyno", "sage"])
        self.assertFalse(hub.response_active.is_set())
        self.assertFalse(director.busy)

    def test_second_synthesis_overlaps_first_playback_and_preserves_order(self):
        second_rendered = threading.Event()

        class Voices(FakeVoices):
            def render(self, toy, text):
                if toy == "sage":
                    second_rendered.set()
                return super().render(toy, text)

        class Hub(FakeHub):
            def play(self, toy, pcm, **kwargs):
                if toy == "dyno" and not second_rendered.wait(2):
                    raise AssertionError("Second line was not synthesized during first playback")
                return super().play(toy, pcm, **kwargs)
        director = make_director(voices=Voices(), hub=Hub())
        director._turn(event="hello")
        self.assertEqual(director.last_trace["status"], "ok")
        self.assertEqual(director.hub.played, ["dyno", "sage"])

    def test_failed_synthesis_cleans_up_and_next_turn_can_run(self):
        voices = FakeVoices()
        voices.render = Mock(side_effect=RuntimeError("test synthesis failure"))
        director = make_director(voices=voices)
        with self.assertLogs("director", level="ERROR"):
            director._turn(event="hello")
        self.assertEqual(director.last_trace["status"], "failed")
        self.assertEqual(director.hub.played, [])
        self.assertFalse(director.hub.response_active.is_set())
        director.voices = FakeVoices()
        director._turn(event="hello again")
        self.assertEqual(director.last_trace["status"], "ok")

    def test_partial_stream_is_not_retried_and_completed_line_plays_once(self):
        class BrokenBackend(Backend):
            def stream(self, *args, **kwargs):
                yield "HEARD: hello\nDYNO: Hello, friend!\nSAGE: An incomplete"
                raise RuntimeError("test connection lost")
        director = make_director(BrokenBackend())
        with self.assertLogs("director", level="ERROR"):
            director._turn(event="hello")
        self.assertEqual(director.hub.played, ["dyno"])
        self.assertEqual(director.last_trace["status"], "failed")

    def test_audio_and_image_temp_files_are_deleted_and_stale_images_skipped(self):
        paths = []

        class InspectBackend(Backend):
            def stream(self, *args, **kwargs):
                for value in kwargs.values():
                    if value:
                        self.assert_file(value)
                        paths.append(value)
                yield from super().stream()

            @staticmethod
            def assert_file(path):
                assert Path(path).is_file()
        director = make_director(InspectBackend())
        director.eyes.views["sage"] = types.SimpleNamespace(jpeg=b"jpeg", ts=time.time())
        now = time.monotonic()
        utt = Utterance("sage", time.time()-1, time.time(), np.ones(16000, np.int16), 5000, now-.5, now)
        director._turn(utt=utt)
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(not Path(path).exists() for path in paths))
        self.assertEqual(director.last_trace["reference"], "last_voiced_frame_received")
        self.assertGreaterEqual(director.last_trace["milestones_ms"]["utterance_ready_ms"], 490)
        paths.clear()
        director.eyes.views["sage"].ts = time.time()-30
        director._turn(utt=utt)
        self.assertEqual(len(paths), 1)

    def test_canned_scene_does_not_interleave_a_model_response(self):
        director = make_director()
        director._turn_lock.acquire()
        try:
            director.run_canned()
        finally:
            director._turn_lock.release()
        self.assertFalse(director.hub.played)

    def test_penny_can_answer_accurately_and_another_toy_can_follow(self):
        class PennyBackend(Backend):
            def stream(self, *args, **kwargs):
                yield "HEARD: Penny, how many feet do penguins have?\nPENNY: Two feet for a tiny penguin parade!\n"
                yield "SAGE: Penguins use their feet to walk on land."
        director = make_director(PennyBackend(), FakeHub(("penny", "sage")))
        director._turn(event="question")
        self.assertEqual(director.last_trace["status"], "ok")
        self.assertEqual(director.hub.played, ["penny", "sage"])
        self.assertEqual(director.voices.rendered[0], ("penny", "Two feet for a tiny penguin parade!"))

    def test_penny_followup_also_works_when_heard_header_is_missing(self):
        class PennyBackend(Backend):
            hears_audio = False
            def transcribe(self, wav):
                return "Penny, how many feet do penguins have?"
            def stream(self, *args, **kwargs):
                yield "PENNY: Two feet for a tiny penguin parade!\nSAGE: Penguins use their feet to walk on land."
        director = make_director(PennyBackend(), FakeHub(("penny", "sage")))
        now = time.monotonic()
        utterance = Utterance("penny", time.time()-1, time.time(), np.ones(16000,np.int16), 5000, now-.5, now)
        director._turn(utt=utterance)
        self.assertEqual(director.last_trace["status"], "ok")
        self.assertEqual(director.hub.played, ["penny", "sage"])

    def test_penny_spelling_and_child_corrections_reach_tts_unchanged(self):
        for question, reply in [
            ("Penny, spell dog.", "Dog is spelled D-O-G. A tiny word with a wagging tail!"),
            ("Penny, you spelled it wrong. It is D-O-G.", "You are right: D-O-G. Thank you for checking!"),
            ("Penny, spell it.", "It is spelled I-T."),
        ]:
            with self.subTest(question=question):
                class PennyBackend(Backend):
                    hears_audio = False

                    def transcribe(self, wav):
                        return question

                    def stream(self, *args, **kwargs):
                        yield f"HEARD: {question}\nPENNY: {reply}\n"
                director = make_director(PennyBackend(), FakeHub(("penny",)))
                now = time.monotonic()
                utterance = Utterance("penny", time.time()-1, time.time(), np.ones(16000,np.int16),
                                      5000, now-.5, now)
                director._turn(utt=utterance)
                self.assertEqual(director.last_trace["status"], "ok")
                self.assertEqual(director.voices.rendered, [("penny", reply)])
                self.assertEqual(director.hub.played, ["penny"])

    def test_audio_failure_does_not_report_a_playback_ack(self):
        hub = FakeHub()
        hub.play = Mock(side_effect=OSError("test offline"))
        pipeline = SpeechPipeline(hub, FakeVoices(), TurnTrace())
        pipeline.submit("dyno", "Hello")
        with self.assertRaisesRegex(RuntimeError, "Speech output failed"):
            pipeline.finish()
        self.assertNotIn("last_playback_ack_ms", pipeline.trace.snapshot()["milestones_ms"])

    def test_filler_wait_is_separate_from_audio_transport(self):
        clock = [0.]
        hub = FakeHub()
        def wait():
            clock[0] += .3
        def play(*args, on_dispatch, **kwargs):
            on_dispatch()
            clock[0] += .2
        hub.play = play
        with patch("brain.latency.time.monotonic", side_effect=lambda: clock[0]):
            trace = TurnTrace(origin=0.)
            pipeline = SpeechPipeline(hub, FakeVoices(), trace, before_play=wait)
            pipeline.submit("dyno", "Hi")
            pipeline.finish()
        stages = trace.snapshot()["stage_work_ms"]
        self.assertEqual(stages["filler_wait_ms"], 300.)
        self.assertEqual(stages["audio_post_and_playback_ms"], 200.)


class BackendTests(unittest.TestCase):
    def test_sse_multiline_unicode_reasoning_and_history(self):
        events = [{"choices": [{"delta": {"reasoning_content": "secret"}}]},
                  {"choices": [{"delta": {"content": "HEARD: hi\n"}}]},
                  {"choices": [{"delta": {"content": "DYNO: Hello, café!"}}]}]
        payload = b": keepalive\n\n" + b"".join(
            ("data: " + json.dumps(e, ensure_ascii=False) + "\r\n\r\n").encode() for e in events) + b"data: [DONE]\n\n"
        backend = object.__new__(LlamaCppBackend)
        backend.system, backend.history = "system", []
        backend.http = types.SimpleNamespace(open=Mock(return_value=io.BytesIO(payload)))
        result = "".join(backend.stream("prompt"))
        self.assertEqual(result, "HEARD: hi\nDYNO: Hello, café!")
        request = backend.http.open.call_args.args[0]
        self.assertTrue(json.loads(request.data)["stream"])
        self.assertFalse(json.loads(request.data)["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(backend.history[-1]["content"], result)
        multiline = io.BytesIO(b'data: {"choices":\ndata: []}\n\ndata: [DONE]\n\n')
        self.assertEqual(list(_sse(multiline)), [{"choices": []}])

    def test_truncated_or_error_sse_never_updates_history(self):
        backend = object.__new__(LlamaCppBackend)
        backend.system, backend.history = "system", []
        backend.http = types.SimpleNamespace(open=Mock(return_value=io.BytesIO(b'data: {"choices": []}\n\n')))
        with self.assertRaisesRegex(RuntimeError, "before"):
            list(backend.stream("prompt"))
        self.assertEqual(backend.history, [])
        with self.assertRaisesRegex(RuntimeError, "stream error"):
            list(_sse(io.BytesIO(b'data: {"error": "failed"}\n\n')))

    def test_token_limit_does_not_flush_an_incomplete_last_line(self):
        events = [{"choices": [{"delta": {"content": "HEARD: hi\nDYNO: Hello!\nSAGE: This is unfinished"}}]},
                  {"choices": [{"delta": {}, "finish_reason": "length"}]}]
        payload = b"".join(("data: " + json.dumps(e) + "\n\n").encode() for e in events) + b"data: [DONE]\n\n"
        backend = object.__new__(LlamaCppBackend)
        backend.system, backend.history = "system", []
        backend.http = types.SimpleNamespace(open=Mock(return_value=io.BytesIO(payload)))
        director = make_director(backend)
        with self.assertLogs("director", level="ERROR"):
            director._turn(event="hello")
        self.assertEqual(director.hub.played, ["dyno"])
        self.assertEqual(director.last_trace["status"], "failed")
        self.assertEqual(backend.history, [])

    def test_geniex_checks_model_and_uses_native_no_thinking_option(self):
        model_list = io.BytesIO(json.dumps({"data": [{"id": config.GENIEX_MODEL}]}).encode())
        response = {"choices": [{"delta": {"content": "DYNO: Hi!"}, "finish_reason": "stop"}]}
        payload = ("data: " + json.dumps(response) + "\n\ndata: [DONE]\n\n").encode()
        opener = types.SimpleNamespace(open=Mock(side_effect=[model_list, io.BytesIO(payload)]))
        with patch("brain.llm.urllib.request.build_opener", return_value=opener), \
                patch.object(GenieXBackend, "_init_transcriber") as transcriber:
            backend = make_backend("geniex", "system", gpu=True)
            self.assertEqual(backend.ask("hello"), "DYNO: Hi!")
        transcriber.assert_called_once()
        self.assertEqual(opener.open.call_args_list[0].args[0], config.GENIEX_URL + "/v1/models")
        req = opener.open.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, config.GENIEX_URL + "/v1/chat/completions")
        self.assertEqual(body["model"], config.GENIEX_MODEL)
        self.assertFalse(body["enable_think"])
        self.assertEqual(body["reasoning_format"], "deepseek")
        self.assertNotIn("chat_template_kwargs", body)

    def test_geniex_unavailable_or_missing_model_never_launches_cpu_fallback(self):
        for result, message in ((OSError("offline"), "unavailable"), (io.BytesIO(b'{"data": []}'), "not cached")):
            opener = types.SimpleNamespace(open=Mock(side_effect=[result]))
            with patch("brain.llm.urllib.request.build_opener", return_value=opener), \
                    patch("brain.llm.subprocess.Popen") as launch, \
                    patch.object(GenieXBackend, "_init_transcriber") as transcriber:
                with self.assertRaisesRegex(RuntimeError, message):
                    GenieXBackend("system")
            launch.assert_not_called()
            transcriber.assert_not_called()

    def test_litert_stream_fallback_and_retry_before_output(self):
        backend = object.__new__(LiteRTBackend)
        backend.turns = 0
        backend.conv = types.SimpleNamespace(send_message_async=Mock(side_effect=RuntimeError("context")))
        good = types.SimpleNamespace(send_message_async=lambda _: iter([{"content":[{"type":"text","text":"Hi"}]}]))
        backend.new_conversation = Mock(side_effect=lambda: setattr(backend, "conv", good))
        self.assertEqual(list(backend.stream("prompt")), ["Hi"])
        self.assertEqual(backend.new_conversation.call_count, 1)
        backend.conv = types.SimpleNamespace(send_message=lambda _: {"content": "legacy"})
        self.assertEqual(backend.ask("prompt"), "legacy")

    def test_litert_does_not_retry_after_visible_output(self):
        def broken(_):
            yield {"content": "DYNO: Hello"}
            raise RuntimeError("test stream failed")
        backend = object.__new__(LiteRTBackend)
        backend.turns = 0
        backend.conv = types.SimpleNamespace(send_message_async=broken)
        backend.new_conversation = Mock()
        stream = backend.stream("prompt")
        self.assertEqual(next(stream), "DYNO: Hello")
        with self.assertRaises(RuntimeError):
            next(stream)
        self.assertEqual(backend.new_conversation.call_count, 1)  # cleanup, no resend

    def test_thought_channel_is_excluded(self):
        self.assertEqual(_text({"content": [{"type":"thought","text":"secret"},
                                             {"type":"text","text":"hello"}],
                                "channels":{"thought":"private"}}), "hello")


class LocalHTTPTests(unittest.TestCase):
    def test_real_sse_starts_pcm_post_before_llm_finishes(self):
        self._run_streaming_http(LlamaCppBackend)

    def test_geniex_streaming_contract_over_real_http(self):
        self._run_streaming_http(GenieXBackend)

    def test_existing_pcm_and_low_bandwidth_ulaw_options_over_http(self):
        for codec, rate in (("pcm",16000), ("ulaw",8000)):
            with self.subTest(codec=codec, rate=rate), patch.object(config,"PLAY_CODEC",codec), \
                    patch.object(config,"PLAY_RATE",rate):
                self._run_streaming_http(LlamaCppBackend)

    def _run_streaming_http(self, backend_class):
        audio_received = threading.Event()
        received = []
        requests = []
        class ToyHandler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                received.append((self.path,self.rfile.read(int(self.headers['Content-Length']))))
                audio_received.set()
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'OK')
        class ModelHandler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                body=json.dumps({'data':[{'id':config.GENIEX_MODEL}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                def send(text):
                    body={'choices':[{'delta':{'content':text}}]}
                    self.wfile.write(('data: '+json.dumps(body)+'\n\n').encode());self.wfile.flush()
                send('HEARD: hello\nDYNO: Hello, friend!\n')
                if not audio_received.wait(3):
                    self.wfile.write(b'data: {"error":"audio did not start before model continuation"}\n\n')
                else:
                    send('SAGE: Shall we play?')
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        toy_server=ThreadingHTTPServer(('127.0.0.1',0),ToyHandler)
        model_server=ThreadingHTTPServer(('127.0.0.1',0),ModelHandler)
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in (toy_server,model_server)]
        for thread in threads:thread.start()
        hub=object.__new__(AtomHub)  # no UDP socket: never contacts or claims a physical toy
        hub.atoms={t:Atom(t,f'127.0.0.1:{toy_server.server_port}',t,last_seen=time.time()) for t in ('dyno','sage')}
        hub.response_active=threading.Event();hub._play_lock=threading.Lock()
        hub._http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        hub.talking=None;hub.mute_until=0;hub.force_mute=False
        try:
            with patch.object(config,'LLAMA_URL',f'http://127.0.0.1:{model_server.server_port}'), \
                    patch.object(config,'GENIEX_URL',f'http://127.0.0.1:{model_server.server_port}'):
                if backend_class is GenieXBackend:
                    with patch.object(GenieXBackend,'_init_transcriber'):
                        backend=GenieXBackend('system')
                else:
                    backend=object.__new__(LlamaCppBackend)
                    backend.system='system';backend.history=[];backend.http=hub._http
                # An event skips transcription; no model binaries or toy discovery.
                director=make_director(backend,hub)
                director._turn(event='hello')
            self.assertEqual(director.last_trace['status'],'ok')
            self.assertEqual(len(received),2)
            expected, query = encode_for_atom(b'\0\0'*320)
            self.assertTrue(all(path=='/play?'+query and pcm==expected for path,pcm in received))
            self.assertTrue(requests[0]['stream'])
            if backend_class is GenieXBackend:
                self.assertEqual(requests[0]['model'],config.GENIEX_MODEL)
                self.assertFalse(requests[0]['enable_think'])
            milestones=director.last_trace['milestones_ms']
            self.assertLess(milestones['first_audio_post_ms'],milestones['model_done_ms'])
            self.assertFalse(hub.response_active.is_set());self.assertIsNone(hub.talking)
        finally:
            for server in (toy_server,model_server):server.shutdown();server.server_close()
            for thread in threads:thread.join()


class InputTests(unittest.TestCase):
    def tearDown(self):
        config.apply_latency_profile("responsive")

    @staticmethod
    def utterance(toy, rms):
        return Utterance(toy, 10, 11, np.ones(320, np.int16), rms)

    def test_single_toy_never_waits_an_arbitration_window(self):
        pending = Mock()
        first = self.utterance("dyno", 1000)
        self.assertIs(arbitrate(first, pending, expected_toys=["dyno"]), first)
        pending.get.assert_not_called()

    def test_arbitration_picks_loudest_and_stops_after_all_copies(self):
        pending = queue.Queue()
        first, second = self.utterance("dyno", 1000), self.utterance("sage", 2000)
        pending.put(second)
        with patch.object(pending, "get", wraps=pending.get) as get:
            self.assertIs(arbitrate(first, pending, expected_toys=["dyno","sage"]), second)
            self.assertEqual(get.call_count, 1)

    def test_endpoint_profiles_and_host_frame_timestamps(self):
        for profile, end_ms in (("responsive",500), ("patient",700)):
            config.apply_latency_profile(profile)
            out = queue.Queue()
            segmenter = Segmenter("dyno", out)
            segmenter.vad = types.SimpleNamespace(is_speech=lambda pcm, _: np.frombuffer(pcm,np.int16).any())
            clock = [100.]
            def feed(frame):
                clock[0] += .02
                segmenter.feed(frame)
            with patch("brain.vad.time.monotonic", side_effect=lambda: clock[0]):
                for _ in range(40): feed(np.full(320,4000,np.int16))
                last_voice = clock[0]
                for _ in range(end_ms//20-1): feed(np.zeros(320,np.int16))
                self.assertTrue(out.empty())
                feed(np.zeros(320,np.int16))
            utterance = out.get_nowait()
            self.assertAlmostEqual(utterance.last_voiced_received,last_voice)
            self.assertAlmostEqual((utterance.emitted-last_voice)*1000,end_ms,places=5)
            self.assertGreater(len(utterance.pcm),0)

    def test_response_priority_skips_new_camera_requests(self):
        hub = object.__new__(AtomHub)
        hub.response_active = threading.Event()
        hub.response_active.set()
        hub._http = Mock()
        self.assertIsNone(hub.capture("dyno"))
        hub._http.open.assert_not_called()

    def test_trace_is_content_free_and_first_milestones_are_not_overwritten(self):
        trace = TurnTrace(origin=100.,source="speech")
        trace.mark("first_audio_post_ms",when=100.5)
        trace.mark("first_audio_post_ms",when=101.)
        state=trace.snapshot()
        self.assertEqual(state["milestones_ms"]["first_audio_post_ms"],500)
        self.assertFalse(state["audio_onset_measured"])
        self.assertNotIn("text",json.dumps(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
