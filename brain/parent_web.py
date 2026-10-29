"""The Parent Board web server: its own port (8090), its own handler, separate from the toys' open dashboard on 8080.

Security notes (docs/parent-board.md has the full threat list):
  * Every API call except /api/status, /api/setup and /api/login needs a session cookie (HttpOnly, SameSite=Strict,
    5 minutes idle). Every POST also needs the header X-PB: 1 and a JSON body, so a page on another site cannot drive it.
  * The Host header must be an IP address, localhost or a bare / .local name (blocks DNS-rebinding tricks).
  * Plain HTTP: it is meant for the home Wi-Fi. The PIN can be read by anyone who can sniff that network; use a trusted
    network and a PIN you do not reuse. (HTTPS would need a certificate the phone trusts; noted as a later step.)
  * Request bodies are never logged. Nothing here is linked from the toys' dashboard.
"""
from __future__ import annotations

import http.cookies
import json
import logging
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import parent as P
from . import scripted

log = logging.getLogger("parent-web")

HOST_OK = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:]+\]|localhost|[a-z0-9-]+(\.local)?)(:\d+)?$", re.I)
MAX_JSON, MAX_PHOTO = 64 * 1024, 8 * 1024 * 1024
PUBLIC = {"/", "/api/status", "/api/setup", "/api/login"}


def make_handler(parent: P.Parent, director=None):
    class H(BaseHTTPRequestHandler):
        server_version = "ParentBoard"
        sys_version = ""
        timeout = 15   # a stalled or trickling connection is dropped (one thread each otherwise)

        def log_message(self, *a):   # no request logging: paths and bodies can carry a child's details
            pass

        def _send(self, code, body, ctype="application/json", cookie=None):
            b = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ""))
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                        "connect-src 'self'; img-src 'self' data:; form-action 'none'; base-uri 'none'")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(b)

        def _token(self):
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            return c["pb"].value if "pb" in c else None

        def _cookie(self, token):
            return f"pb={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={P.SESSION_IDLE_S}" if token else "pb=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"

        def _guard(self, path, post):
            if not HOST_OK.match(self.headers.get("Host", "")):
                self._send(400, {"error": "bad host"})
                return False
            if post and self.headers.get("X-PB") != "1":
                self._send(403, {"error": "forbidden"})
                return False
            if path not in PUBLIC and not parent.check(self._token()):
                self._send(401, {"error": "locked"})
                return False
            return True

        def _length(self, limit):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ValueError("bad request")
            if n < 0 or n > limit:   # a negative length would make read() consume the whole connection into memory
                raise ValueError("bad request")
            return n

        def _json(self):
            n = self._length(MAX_JSON)
            if "json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError("bad request")
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("bad request")
            return data

        # ---------------- GET ----------------
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if not self._guard(u.path, False):
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/":
                    return self._send(200, PAGE, "text/html")
                if u.path == "/api/status":
                    return self._send(200, parent.status())
                if u.path == "/api/state":
                    parent.sweep()
                    bound = parent.bound_child()
                    return self._send(200, {
                        "children": parent.children(), "bound": bound["id"] if bound else None,
                        "settings": parent.index["settings"], "checkin_due": parent.checkin_due(),
                        "cues": [{"id": k, "label": v["label"]} for k, v in scripted.CUES.items()],
                        "toys_online": list(director.hub.online()) if director else [],
                        "gemma": bool(director and hasattr(director.llm, "complete"))})
                if u.path == "/api/items":
                    return self._send(200, {"items": parent.view(q.get("child", ""))})
                if u.path == "/api/photo/status":
                    return self._send(200, parent.jobs.get(q.get("job", ""), {"status": "unknown"}))
            except P.Locked:
                return self._send(401, {"error": "locked"})
            except KeyError:
                return self._send(404, {"error": "no such child"})
            self._send(404, {"error": "not found"})

        # ---------------- POST ----------------
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if not self._guard(u.path, True):
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/api/photo":
                    n = self._length(MAX_PHOTO)
                    if not (self.headers.get("Content-Type") or "").startswith("image/"):
                        return self._send(400, {"error": "bad photo"})
                    data = self.rfile.read(n)
                    job = parent.read_worksheet(q.get("child", ""), data, director.llm if director else None,
                                                busy=lambda: bool(director and (director.busy or director.child_speaking())))
                    return self._send(200, {"job": job})
                b = self._json()
                return self._post(u.path, b)
            except P.Locked:
                return self._send(401, {"error": "locked"})
            except P.RateLimited as e:
                return self._send(429, {"error": str(e), "wait": int(e.seconds)})
            except P.WrongPin:
                return self._send(403, {"error": "That PIN is not right."})
            except KeyError:
                return self._send(404, {"error": "no such child"})
            except (ValueError, RuntimeError) as e:
                return self._send(400, {"error": str(e)})
            except Exception:  # noqa: BLE001 — never echo internals to a browser
                log.exception("parent board request failed")
                return self._send(500, {"error": "something went wrong"})

        def _post(self, path, b):
            if path == "/api/setup":
                tok = parent.setup(str(b.get("pin", "")), str(b.get("code", "")))
                return self._send(200, {"ok": True}, cookie=self._cookie(tok))
            if path == "/api/login":
                tok = parent.login(str(b.get("pin", "")))
                return self._send(200, {"ok": True}, cookie=self._cookie(tok))
            if path == "/api/logout":
                parent.logout(self._token())
                return self._send(200, {"ok": True}, cookie=self._cookie(None))
            if path == "/api/child/add":
                return self._send(200, parent.add_child(str(b.get("name", ""))))
            if path == "/api/child/delete":
                parent.delete_child(str(b.get("id", "")))
                return self._send(200, {"ok": True})
            if path == "/api/parse":
                res = P.parse_text(str(b.get("text", ""))[:1000])
                return self._send(200, res)
            if path == "/api/items/add":
                return self._send(200, {"added": parent.add_items(str(b.get("child", "")), b.get("cards") or [])})
            if path == "/api/items/delete":
                parent.delete_item(str(b.get("child", "")), str(b.get("id", "")))
                return self._send(200, {"ok": True})
            if path == "/api/items/confirm":
                parent.confirm_item(str(b.get("child", "")), str(b.get("id", "")))
                return self._send(200, {"ok": True})
            if path == "/api/items/clear":
                parent.clear_child(str(b.get("child", "")), b.get("kinds") if isinstance(b.get("kinds"), list) else None)
                return self._send(200, {"ok": True})
            if path == "/api/nowplaying":
                parent.now_playing(b.get("child") or None)
                return self._send(200, {"ok": True})
            if path == "/api/cue":
                if not director:
                    return self._send(503, {"error": "toys are not connected"})
                return self._send(200, director.cue(str(b.get("text", ""))[:200], b.get("cue"), bool(b.get("urgent"))))
            if path == "/api/checkin/done":
                parent.checkin_done()
                return self._send(200, {"ok": True})
            if path == "/api/settings":
                parent.set_settings(checkin_day=b.get("checkin_day"), checkin_hour=b.get("checkin_hour"), notes_on=b.get("notes_on"))
                return self._send(200, {"ok": True})
            if path == "/api/pin/change":
                parent.change_pin(str(b.get("old", "")), str(b.get("new", "")), keep=self._token())
                return self._send(200, {"ok": True})
            if path == "/api/lock":
                parent.lock()
                return self._send(200, {"ok": True}, cookie=self._cookie(None))
            if path == "/api/wipe":
                if b.get("confirm") != "DELETE":
                    return self._send(400, {"error": "type DELETE to confirm"})
                parent.wipe_all(str(b.get("pin", "")))
                return self._send(200, {"ok": True}, cookie=self._cookie(None))
            self._send(404, {"error": "not found"})

    return H


def serve(parent, director=None, port: int = 8090):
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(parent, director))
    threading.Thread(target=srv.serve_forever, daemon=True, name="parent-board").start()
    log.info("Parent Board on port %d (home network only; first visit sets the family PIN)", port)
    return srv


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Parent Board</title>
<style>
:root{--bg:#f7f5f0;--fg:#1d1d1f;--card:#fff;--mut:#6b6b70;--line:#e3e0d8;--acc:#2a6f6b;--bad:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#161618;--fg:#f2f2f4;--card:#222226;--mut:#9a9aa2;--line:#34343a;--acc:#5fb3ad;--bad:#f2b8b5}}
*{box-sizing:border-box;min-width:0}body{margin:0;overflow-x:hidden;font:16px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:640px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 12px}h2{font-size:16px;margin:0 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:0 0 12px}
button,input,select,textarea{font:inherit;color:inherit}button{border:1px solid var(--line);background:var(--card);border-radius:20px;padding:8px 14px;margin:3px 3px 3px 0;cursor:pointer}
button.p{background:var(--acc);color:#fff;border-color:var(--acc)}button.x{color:var(--bad)}button.on{border-color:var(--acc);box-shadow:0 0 0 2px var(--acc) inset}
input,textarea,select{width:100%;max-width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);margin:4px 0}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row>input{flex:1 1 140px}.mut{color:var(--mut);font-size:14px}.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.item{display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-top:1px solid var(--line)}.item:first-child{border-top:0}.stale{opacity:.6}
.banner{background:var(--acc);color:#fff;border-radius:10px;padding:10px 12px;margin:0 0 12px}.err{color:var(--bad)}[hidden]{display:none!important}
</style></head><body><main>
<section id=lock class=card hidden><h1>Parent Board</h1><div id=lockmsg class=mut></div>
<input id=pin type=password inputmode=text autocomplete=off placeholder="Family PIN"><input id=pin2 type=password autocomplete=off placeholder="Type it again" hidden><input id=code autocomplete=off placeholder="Setup code (in the brain's log)" hidden>
<button class=p id=lockbtn>Open</button> <span id=lockerr class=err></span>
<p class=mut id=lockhelp></p></section>
<section id=app hidden>
<div class=row style="justify-content:space-between"><h1>Parent Board</h1><span><button id=lockNow>Lock</button></span></div>
<div id=banner class=banner hidden></div>
<div class=card><h2>Which child is playing?</h2><div id=kids></div><div class=row><input id=newkid placeholder="Add a child (first name only)" style="flex:1"><button id=addkid>Add</button></div>
<div class=mut id=bindnote></div></div>
<div class=card><h2>Say it now</h2><div class=mut>The toys react in their own words. Nothing is saved.</div><div id=cues></div>
<div class=row><input id=cuetext placeholder="or type something, e.g. it is raining, no bikes today" style="flex:1"><button class=p id=cuesend>Send</button></div>
<label class=mut><input type=checkbox id=urgent style="width:auto"> Stop everything now (drops what the toys are saying)</label><div id=cuemsg class=mut></div></div>
<div class=card><h2 id=teach>Tell the toys</h2><textarea id=sentence rows=3 placeholder="e.g. Spelling test Friday, she loves space, and soccer is Tuesdays at four."></textarea>
<div class=row><button class=p id=parse>Make cards</button><label class=mut><input type=file id=photo accept="image/*" capture=environment hidden><button id=photobtn type=button>Photo of homework</button></label></div>
<div id=cards></div>
<div class=mut style="margin-top:8px">Or tap:</div><div id=chips></div></div>
<div class=card><h2 id=notesh>Notes</h2><div id=items></div><button class=x id=clearall>Delete everything for this child</button></div>
<div class=card><h2>Settings</h2>
<label class=mut><input type=checkbox id=noteson style="width:auto"> Toys use the notes</label>
<div class=row><span class=mut>Weekly check-in:</span><select id=cday style="width:auto"></select><select id=chour style="width:auto"></select></div><hr>
<div class=row><input id=oldpin type=password placeholder="Current PIN" style="flex:1"><input id=newpin type=password placeholder="New PIN" style="flex:1"><button id=chpin>Change</button></div>
<div class=mut>Notes live only on the brain, encrypted. After a restart the toys use none until you open this board and enter the PIN.</div><button class=x id=wipe>Delete all profiles</button><div id=setmsg class=mut></div></div>
</section></main>
<script>
const $=id=>document.getElementById(id);let S=null,kid=null,cards=[];const DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
async function api(path,body,raw){const o={method:(body===undefined&&!raw)?"GET":"POST",headers:{"X-PB":"1"}};
 if(raw){o.headers["Content-Type"]=raw.type;o.body=raw}else if(body!==undefined){o.headers["Content-Type"]="application/json";o.body=JSON.stringify(body)}
 const r=await fetch(path,o);let j={};try{j=await r.json()}catch(e){}if(r.status==401){showLock();throw new Error("locked")}if(!r.ok)throw new Error(j.error||"error");return j}
function el(t,txt,cls){const e=document.createElement(t);if(txt!==undefined)e.textContent=txt;if(cls)e.className=cls;return e}
let idle;function bump(){clearTimeout(idle);idle=setTimeout(()=>{api("/api/logout",{}).catch(()=>{});showLock()},300000)}document.addEventListener("click",bump);document.addEventListener("keydown",bump);
async function showLock(){$("app").hidden=true;$("lock").hidden=false;const st=await (await fetch("/api/status")).json();
 $("pin2").hidden=st.configured;$("code").hidden=!st.needs_code;$("pin").value="";$("pin2").value="";$("code").value="";
 $("lockmsg").textContent=!st.crypto?"This brain cannot store profiles yet (the encryption library is missing).":st.configured?(st.unlocked?"Enter the family PIN.":"The brain restarted. Enter the PIN to switch the notes back on."):"First time: choose a family PIN: "+st.min_digits+"+ digits, or a phrase of "+st.min_pin+"+ characters (stronger). Everyone in the household shares it. The setup code is printed in the brain's log when it starts.";
 $("lockbtn").textContent=st.configured?"Open":"Set PIN";$("lockhelp").textContent=st.locked_for?"Too many tries. Wait "+st.locked_for+" seconds.":""}
$("lockbtn").onclick=async()=>{$("lockerr").textContent="";const st=await (await fetch("/api/status")).json();
 try{if(!st.configured){if($("pin").value!==$("pin2").value)throw new Error("The two PINs differ.");await api("/api/setup",{pin:$("pin").value,code:$("code").value})}else await api("/api/login",{pin:$("pin").value});$("lock").hidden=true;await load()}catch(e){if(e.message!="locked")$("lockerr").textContent=e.message}};
async function load(){S=await api("/api/state");$("app").hidden=false;bump();if(!kid||!S.children.find(c=>c.id==kid))kid=S.bound||(S.children[0]||{}).id||null;draw();await items()}
function draw(){const k=$("kids");k.textContent="";S.children.forEach(c=>{const b=el("button","");const d=el("span","","dot");d.style.background=c.color;b.append(d,c.name+(S.bound==c.id?"  ▶ playing":""));if(c.id==kid)b.classList.add("on");b.onclick=()=>{kid=c.id;draw();items()};k.append(b)});
 const c=S.children.find(x=>x.id==kid);$("teach").textContent=c?"Tell the toys about "+c.name:"Tell the toys";$("notesh").textContent=c?c.name+"'s notes":"Notes";
 $("bindnote").textContent=c?(S.bound==kid?c.name+" is playing. The toys use "+c.name+"'s notes (ends after 30 idle minutes).":"Tap “Playing now” so the toys use "+c.name+"'s notes."):"Add a child to begin.";
 if(c){const b=el("button",S.bound==kid?"Stop (play generically)":"Playing now: "+c.name,S.bound==kid?"":"p");b.onclick=async()=>{await api("/api/nowplaying",{child:S.bound==kid?null:kid});await load()};$("bindnote").append(" ",b)}
 const cu=$("cues");cu.textContent="";S.cues.forEach(q=>{const b=el("button",q.label);b.onclick=()=>sendcue({cue:q.id});cu.append(b)});
 $("banner").hidden=!S.checkin_due;if(S.checkin_due){$("banner").textContent="Weekly check-in: tap “still true” on what still applies, delete what does not, then ";const b=el("button","done");b.onclick=async()=>{await api("/api/checkin/done",{});await load()};$("banner").append(b)}
 $("noteson").checked=S.settings.notes_on!==false;const d=$("cday");if(!d.options.length){DAYS.forEach((n,i)=>d.add(new Option(n,i)));for(let h=0;h<24;h++)$("chour").add(new Option(h+":00",h))}d.value=S.settings.checkin_day;$("chour").value=S.settings.checkin_hour;
 chips()}
const CH={Interests:["dinosaurs","space","drawing","music","animals","building","reading","sport"],Boundaries:["quieter voices today","no scary stories","tired today, keep it gentle"],School:["spelling test","times tables","reading practice","maths"]};
function chips(){const w=$("chips");w.textContent="";Object.entries(CH).forEach(([g,list])=>{w.append(el("div",g,"mut"));list.forEach(t=>{const b=el("button",t);b.onclick=()=>addCards([g=="Interests"?{kind:"interest",text:t}:g=="Boundaries"?{kind:"boundary",text:t.replace(" today",""),scope:t.includes("today")?"today":"standing"}:{kind:"school",text:t}]);w.append(b)});w.append(el("br"))})}
async function addCards(cs){if(!kid)return alert("Add a child first.");await api("/api/items/add",{child:kid,cards:cs});await items()}
async function items(){$("items").textContent="";if(!kid)return;const r=await api("/api/items?child="+kid);r.items.forEach(i=>{const row=el("div","","item"+(i.state=="stale"?" stale":""));const l=el("div",i.label);if(i.state=="stale")l.append(el("div","Not used any more: still true?","mut"));
 const a=el("div");if(i.state=="stale"||S.checkin_due){const ok=el("button","still true");ok.onclick=async()=>{await api("/api/items/confirm",{child:kid,id:i.id});await items()};a.append(ok)}
 const x=el("button","delete","x");x.onclick=async()=>{await api("/api/items/delete",{child:kid,id:i.id});await items()};a.append(x);row.append(l,a);$("items").append(row)});if(!r.items.length)$("items").append(el("div","Nothing yet. No notes is fine: the toys play normally.","mut"))}
$("parse").onclick=async()=>{const r=await api("/api/parse",{text:$("sentence").value});cards=r.cards;showCards(r.unparsed)};
function showCards(un){const w=$("cards");w.textContent="";const c=S.children.find(x=>x.id==kid);cards.forEach((cd,i)=>{const row=el("div","","item");row.append(el("div",cd.label));const b=el("button","drop","x");b.onclick=()=>{cards.splice(i,1);showCards(un)};row.append(b);w.append(row)});
 if(un&&un.length)w.append(el("div","Could not turn this into a card: “"+un.join(" / ")+"”. Use the chips below.","mut"));
 if(cards.length){const s=el("button","Save "+cards.length+" for "+(c?c.name:""),"p");s.onclick=async()=>{await addCards(cards);cards=[];$("sentence").value="";showCards([])};w.append(s)}}
async function sendcue(b){$("cuemsg").textContent="";try{const r=await api("/api/cue",Object.assign({urgent:$("urgent").checked},b));$("cuemsg").textContent=r.ok?"Sent"+(r.cue?": "+r.cue:""):r.reason;if(r.ok)$("cuetext").value=""}catch(e){$("cuemsg").textContent=e.message}setTimeout(()=>$("cuemsg").textContent="",4000)}
$("cuesend").onclick=()=>$("cuetext").value.trim()&&sendcue({text:$("cuetext").value});
$("addkid").onclick=async()=>{if($("newkid").value.trim()){const c=await api("/api/child/add",{name:$("newkid").value});kid=c.id;$("newkid").value="";await load()}};
$("clearall").onclick=async()=>{if(kid&&confirm("Delete every note for this child?")){await api("/api/items/clear",{child:kid});await items()}};
$("lockNow").onclick=async()=>{await api("/api/lock",{});showLock()};
$("noteson").onchange=async()=>{await api("/api/settings",{notes_on:$("noteson").checked})};$("cday").onchange=$("chour").onchange=async()=>{await api("/api/settings",{checkin_day:+$("cday").value,checkin_hour:+$("chour").value})};
$("chpin").onclick=async()=>{try{await api("/api/pin/change",{old:$("oldpin").value,new:$("newpin").value});$("setmsg").textContent="PIN changed.";$("oldpin").value=$("newpin").value=""}catch(e){$("setmsg").textContent=e.message}};
$("wipe").onclick=async()=>{if(prompt("This deletes every profile and the PIN. Type DELETE to continue.")=="DELETE"){const pin=prompt("Enter the family PIN to confirm.");if(pin){try{await api("/api/wipe",{confirm:"DELETE",pin:pin});showLock()}catch(e){$("setmsg").textContent=e.message}}}};
$("photobtn").onclick=()=>$("photo").click();$("photo").onchange=async()=>{const f=$("photo").files[0];if(!f||!kid)return;$("cards").textContent="Reading the photo on the brain (it is deleted right after)...";
 try{const r=await api("/api/photo?child="+kid,undefined,f);for(let n=0;n<60;n++){await new Promise(s=>setTimeout(s,2000));const j=await api("/api/photo/status?job="+r.job);if(j.status=="done"){cards=j.cards;showCards(j.unparsed);return}if(j.status!="working"){$("cards").textContent=j.error||"Could not read it.";return}}}catch(e){$("cards").textContent=e.message}$("photo").value=""};
(async()=>{try{await load()}catch(e){if(e.message!="locked")showLock()}})();
</script></body></html>"""
