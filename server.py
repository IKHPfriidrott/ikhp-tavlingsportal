#!/usr/bin/env python3
"""IKHP portal. Python 3.10+, no third-party packages."""
import os, json, sqlite3, secrets, hashlib, hmac, smtplib, ssl, urllib.request, urllib.error, threading
from datetime import datetime, timezone, date, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

BASE=Path(__file__).resolve().parent
DB=os.environ.get("IKHP_DB",str(BASE/"portal.sqlite3"))
ADMIN=os.environ.get("IKHP_ADMIN_PASSWORD","")
CLUB=os.environ.get("IKHP_CLUB_PASSWORD","")
BANKGIRO=os.environ.get("IKHP_BANKGIRO","XXX-SSS")
SMTP_HOST=os.environ.get("SMTP_HOST","")
SMTP_PORT=int(os.environ.get("SMTP_PORT","587"))
SMTP_USER=os.environ.get("SMTP_USER","")
SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD","")
SMTP_FROM=os.environ.get("SMTP_FROM","")
SMTP_SSL=os.environ.get("SMTP_SSL","false").lower()=="true"
EXTERNAL_URL=os.environ.get("IKHP_EXTERNAL_API_URL","")
EXTERNAL_TOKEN=os.environ.get("IKHP_EXTERNAL_API_TOKEN","")
PORT=int(os.environ.get("PORT","8080"))
sessions={}
login_attempts={}
lock=threading.Lock()
TEST_MODE=True
SESSION_LIFETIME=timedelta(hours=8)
def hash_pw(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    return salt.hex()+":"+hashlib.pbkdf2_hmac("sha256",password.encode(),salt,260000).hex()
def verify(password,stored):
    try:
        salt,expected=stored.split(":")
        actual=hash_pw(password,bytes.fromhex(salt)).split(":")[1]
        return hmac.compare_digest(actual,expected)
    except (ValueError,TypeError):return False
def connect():
    c=sqlite3.connect(DB,timeout=20)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c
def init():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS competitions(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,date TEXT NOT NULL,regular_deadline TEXT NOT NULL,final_deadline TEXT NOT NULL,url TEXT DEFAULT '',published INTEGER DEFAULT 0,source TEXT DEFAULT 'Manuell',classes TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS registrations(id INTEGER PRIMARY KEY AUTOINCREMENT,competition_id INTEGER NOT NULL,name TEXT NOT NULL,birth_year INTEGER NOT NULL,gender TEXT NOT NULL,email TEXT NOT NULL,class_name TEXT NOT NULL,events TEXT NOT NULL,regular_total INTEGER NOT NULL,late_surcharge INTEGER NOT NULL,total INTEGER NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',external_reference TEXT DEFAULT '',email_status TEXT DEFAULT 'pending',email_error TEXT DEFAULT '',FOREIGN KEY(competition_id) REFERENCES competitions(id));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,registration_id INTEGER NOT NULL,action TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(registration_id) REFERENCES registrations(id));
        """)
        if not c.execute("SELECT 1 FROM settings WHERE key='club_hash'").fetchone():
            c.execute("INSERT INTO settings VALUES('club_hash',?)",(hash_pw(CLUB),))
        if not c.execute("SELECT 1 FROM competitions").fetchone():
            demo_competitions=[
                ("Junespelen – DEMO","2027-06-13","2027-06-01","2027-06-08","",1,[
                    {"name":"F15","gender":"F","age":15,"events":[{"name":"100 m","fee":100,"late_fee":200},{"name":"Längd","fee":100,"late_fee":200},{"name":"Kula","fee":100,"late_fee":200}]},
                    {"name":"P15","gender":"P","age":15,"events":[{"name":"100 m","fee":100,"late_fee":200},{"name":"200 m","fee":100,"late_fee":200}]},
                    {"name":"F14","gender":"F","age":14,"events":[{"name":"Höjd","fee":100,"late_fee":200},{"name":"Längd","fee":100,"late_fee":200}]}
                ]),
                ("IKHP Sommarspel – DEMO","2027-06-27","2027-06-18","2027-06-23","",1,[
                    {"name":"F13","gender":"F","age":13,"events":[{"name":"60 m","fee":90,"late_fee":180},{"name":"Längd","fee":90,"late_fee":180}]},
                    {"name":"P13","gender":"P","age":13,"events":[{"name":"60 m","fee":90,"late_fee":180},{"name":"Längd","fee":90,"late_fee":180}]}
                ])
            ]
            ids=[]
            for name,day,regular,deadline,url,published,classes in demo_competitions:
                cur=c.execute("INSERT INTO competitions(name,date,regular_deadline,final_deadline,url,published,classes,source) VALUES(?,?,?,?,?,?,?,?)",
                              (name,day,regular,deadline,url,published,json.dumps(classes,ensure_ascii=False),"Demodata"))
                ids.append(cur.lastrowid)
            demo_entries=[
                (ids[0],"Anna Testperson",2012,"F","anna@example.invalid","F15",["100 m","Längd"],200,"pending"),
                (ids[0],"Erik Exempel",2012,"P","erik@example.invalid","P15",["200 m"],100,"confirmed"),
                (ids[1],"Sara Test",2014,"F","sara@example.invalid","F13",["60 m"],90,"pending")
            ]
            for cid,name,birth,gender,email,cl,events,fee,status in demo_entries:
                c.execute("""INSERT INTO registrations
                (competition_id,name,birth_year,gender,email,class_name,events,regular_total,late_surcharge,total,created_at,status,email_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid,name,birth,gender,email,cl,json.dumps(events,ensure_ascii=False),fee,0,fee,now(),status,"demo"))
def now():return datetime.now(timezone.utc).isoformat()
def event_info(comp,cl,chosen):
    byname={e['name']:e for e in cl['events']}
    if not chosen or len(set(chosen))!=len(chosen) or any(x not in byname for x in chosen):raise ValueError("Välj giltiga grenar")
    late=date.today()>date.fromisoformat(comp["regular_deadline"])
    if date.today()>date.fromisoformat(comp["final_deadline"]):raise ValueError("Sista anmälningsdag har passerat")
    regular=sum(int(byname[x]["fee"]) for x in chosen)
    surcharge=sum(max(0,int(byname[x].get("late_fee",byname[x]["fee"]))-int(byname[x]["fee"])) for x in chosen) if late else 0
    return regular,surcharge,regular+surcharge
def send_mail(reg,comp):
    if TEST_MODE:
        raise RuntimeError("Testläge: e-postutskick är avstängt")
    if not SMTP_HOST or not SMTP_FROM:raise RuntimeError("SMTP är inte konfigurerad")
    msg=EmailMessage()
    msg["From"]=SMTP_FROM
    msg["To"]=reg["email"]
    msg["Subject"]="Bekräftelse på tävlingsanmälan – IKHP Huskvarna"
    lines=["Hej!","", "Din anmälan har registrerats i IKHP:s anmälningsportal.",
           f"Tävling: {comp['name']}",f"Tävlingsdatum: {comp['date']}",
           f"Deltagare: {reg['name']}",f"Klass: {reg['class_name']}",
           f"Grenar: {', '.join(json.loads(reg['events']))}",
           f"Ordinarie anmälningsavgift: {reg['regular_total']} kr",
           f"Efteranmälningsavgift: {reg['late_surcharge']} kr",
           f"Total anmälningsavgift: {reg['total']} kr","",
           "IKHP står för ordinarie anmälningsavgift."]
    if reg["late_surcharge"]:
        lines+=["",f"IKHP står för ordinarie avgift. Efteranmälningsavgiften på {reg['late_surcharge']} kr ska betalas in till IKHP:s bankgiro {BANKGIRO}. Ange efteranmälan + namn på inbetalningen."]
    lines+=["","Anmälan är mottagen av IKHP men ännu inte nödvändigtvis registrerad hos tävlingsarrangören.","","IKHP Huskvarna Friidrott"]
    msg.set_content("\n".join(lines))
    if SMTP_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST,SMTP_PORT,timeout=15,context=ssl.create_default_context()) as smtp:
            if SMTP_USER:smtp.login(SMTP_USER,SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if SMTP_USER:smtp.login(SMTP_USER,SMTP_PASSWORD)
            smtp.send_message(msg)
def competition_public(c):
    d=dict(c);d["classes"]=json.loads(d["classes"]);return d
def valid_class(cl,gender,birth,year):
    if cl.get("gender")!=gender:return False
    age=year-birth
    # Class age must be specified by the admin; younger athletes may move up through 22,
    # older athletes may move down within veteran classes from 30 upward.
    target=int(cl.get("age",0))
    if not target:return False
    if age<22:return age<=target<=22
    if age>30:return 30<=target<=age
    return target==age
class Handler(BaseHTTPRequestHandler):
    def json(self,code,obj):
        b=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def body(self):
        size=int(self.headers.get("Content-Length","0"))
        if size>200000:raise ValueError("För stor förfrågan")
        return json.loads(self.rfile.read(size) or b"{}")
    def token(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get("Cookie",""))
        except Exception:return ""
        return cookie.get("ikhp_session").value if "ikhp_session" in cookie else ""
    def admin(self):
        token=self.token()
        with lock:
            expiry=sessions.get(token)
            if expiry is None:return False
            if datetime.now(timezone.utc)>expiry:
                sessions.pop(token,None)
                return False
            return True
    def require_admin(self):
        if not self.admin():self.json(403,{"error":"Administratörsinloggning krävs"});return False
        return True
    def do_GET(self):
        p=urlparse(self.path).path
        if p=="/health":return self.json(200,{"ok":True,"test_mode":True})
        if p=="/":
            b=(BASE/"index.html").read_bytes()
            self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b);return
        if p=="/api/me":return self.json(200,{"admin":self.admin(),"smtp_ready":False,"external_ready":False,"test_mode":True})
        if p=="/api/competitions":
            with connect() as c:
                rows=c.execute("SELECT * FROM competitions WHERE published=1 ORDER BY date").fetchall()
            return self.json(200,[competition_public(x) for x in rows])
        if p.startswith("/api/public-entries/"):
            try:cid=int(p.rsplit("/",1)[1])
            except ValueError:return self.json(400,{"error":"Ogiltigt id"})
            with connect() as c:
                rows=c.execute("SELECT name,class_name,events FROM registrations WHERE competition_id=? ORDER BY created_at",(cid,)).fetchall()
            return self.json(200,[dict(name=r["name"],class_name=r["class_name"],events=json.loads(r["events"])) for r in rows])
        if p=="/api/admin/competitions":
            if not self.require_admin():return
            with connect() as c:rows=c.execute("SELECT * FROM competitions ORDER BY date DESC").fetchall()
            return self.json(200,[competition_public(x) for x in rows])
        if p=="/api/admin/registrations":
            if not self.require_admin():return
            with connect() as c:
                rows=c.execute("""SELECT r.*,c.name AS competition_name,c.date AS competition_date
                 FROM registrations r JOIN competitions c ON c.id=r.competition_id ORDER BY r.created_at DESC""").fetchall()
            return self.json(200,[dict(dict(x),events=json.loads(x["events"])) for x in rows])
        return self.json(404,{"error":"Sidan finns inte"})
    def do_POST(self):
        p=urlparse(self.path).path
        # Basic same-origin check for browser requests.
        origin=self.headers.get("Origin","")
        if origin:
            parsed=urlparse(origin)
            if parsed.netloc!=self.headers.get("Host","") or parsed.scheme not in ("https","http"):
                return self.json(403,{"error":"Otillåtet ursprung"})
        try:
            data=self.body()
            if p=="/api/login":
                if not ADMIN:return self.json(503,{"error":"Administratörslösenord saknas i serverkonfigurationen"})
                ip=self.client_address[0]
                with lock:
                    recent=[t for t in login_attempts.get(ip,[]) if (datetime.now(timezone.utc)-t).total_seconds()<900]
                    login_attempts[ip]=recent
                    if len(recent)>=8:return self.json(429,{"error":"För många inloggningsförsök. Försök senare."})
                if not hmac.compare_digest(str(data.get("password","")),ADMIN):
                    with lock:login_attempts[ip].append(datetime.now(timezone.utc))
                    return self.json(401,{"error":"Fel lösenord"})
                token=secrets.token_urlsafe(32)
                with lock:
                    sessions[token]=datetime.now(timezone.utc)+SESSION_LIFETIME
                    login_attempts.pop(ip,None)
                self.send_response(200);self.send_header("Set-Cookie",f"ikhp_session={token}; HttpOnly; SameSite=Strict; Path=/"+("; Secure" if os.environ.get("IKHP_HTTPS")=="1" else ""))
                self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(b'{"ok":true}');return
            if p=="/api/logout":
                with lock:sessions.pop(self.token(),None)
                self.send_response(200);self.send_header("Set-Cookie","ikhp_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(b'{"ok":true}');return
            if p=="/api/register":
                cid=int(data["competition_id"]);name=str(data["name"]).strip();email=str(data["email"]).strip()
                birth=int(data["birth_year"]);gender=str(data["gender"]);klass=str(data["class_name"])
                events=data["events"];password=str(data.get("club_password",""))
                if not data.get("publication_ack"):raise ValueError("Bekräfta att namn, klass och grenar visas offentligt")
                if not name or len(name)>120 or "@" not in email or len(email)>254 or not 1900<=birth<=date.today().year or gender not in ("F","P"):raise ValueError("Kontrollera deltagaruppgifterna")
                with connect() as c:
                    stored=c.execute("SELECT value FROM settings WHERE key='club_hash'").fetchone()["value"]
                    if not verify(password,stored):return self.json(403,{"error":"Felaktigt klubb-lösenord"})
                    comp=c.execute("SELECT * FROM competitions WHERE id=? AND published=1",(cid,)).fetchone()
                    if not comp:raise ValueError("Tävlingen är inte publicerad")
                    cl=next((x for x in json.loads(comp["classes"]) if x["name"]==klass),None)
                    if not cl:raise ValueError("Vald klass erbjuds inte i tävlingen")
                    regular,surcharge,total=event_info(comp,cl,events)
                    cur=c.execute("""INSERT INTO registrations(competition_id,name,birth_year,gender,email,class_name,events,regular_total,late_surcharge,total,created_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(cid,name,birth,gender,email,klass,json.dumps(events,ensure_ascii=False),regular,surcharge,total,now()))
                    rid=cur.lastrowid
                    c.execute("INSERT INTO audit(registration_id,action,created_at) VALUES(?,?,?)",(rid,"Mottagen internt",now()))
                    reg=c.execute("SELECT * FROM registrations WHERE id=?",(rid,)).fetchone()
                email_status="demo"
                error="E-postutskick är avstängt i testmiljön"
                with connect() as c:c.execute("UPDATE registrations SET email_status=?,email_error=? WHERE id=?",(email_status,error,rid))
                return self.json(201,{"id":rid,"email_status":email_status,"regular_total":regular,"late_surcharge":surcharge,"total":total})
            if p=="/api/admin/competitions":
                if not self.require_admin():return
                name=str(data["name"]).strip();date.fromisoformat(data["date"]);date.fromisoformat(data["regular_deadline"]);date.fromisoformat(data["final_deadline"])
                if not name or data["regular_deadline"]>data["final_deadline"]:raise ValueError("Kontrollera tävlingens datum")
                classes=data["classes"]
                if not classes or any(not x.get("name") or int(x.get("age",0))<1 or not x.get("events") for x in classes):raise ValueError("Lägg till giltiga klasser och grenar")
                with connect() as c:
                    cur=c.execute("INSERT INTO competitions(name,date,regular_deadline,final_deadline,url,published,classes) VALUES(?,?,?,?,?,?,?)",(name,data["date"],data["regular_deadline"],data["final_deadline"],str(data.get("url","")),int(bool(data.get("published",False))),json.dumps(classes,ensure_ascii=False)))
                return self.json(201,{"id":cur.lastrowid})
            if p.startswith("/api/admin/edit-competition/"):
                if not self.require_admin():return
                cid=int(p.rsplit("/",1)[1])
                name=str(data["name"]).strip()
                day=str(data["date"]);regular=str(data["regular_deadline"]);final=str(data["final_deadline"])
                for d in (day,regular,final):date.fromisoformat(d)
                if not name or len(name)>200 or regular>final:raise ValueError("Kontrollera namn och datum")
                classes=data["classes"]
                if not isinstance(classes,list) or not classes:raise ValueError("Minst en klass krävs")
                names=set()
                for cl in classes:
                    cn=str(cl["name"]).strip();age=int(cl["age"])
                    if not cn or cn in names or cl["gender"] not in ("F","P") or not 1<=age<=120:raise ValueError("Ogiltig eller dubblerad klass")
                    names.add(cn)
                    events=cl["events"]
                    if not isinstance(events,list) or not events:raise ValueError("Alla klasser måste ha minst en gren")
                    seen=set()
                    for ev in events:
                        en=str(ev["name"]).strip();fee=int(ev["fee"]);late=int(ev["late_fee"])
                        if not en or en in seen or fee<0 or late<fee:raise ValueError("Kontrollera gren och avgifter")
                        seen.add(en)
                with connect() as c:
                    old=c.execute("SELECT source FROM competitions WHERE id=?",(cid,)).fetchone()
                    if not old:raise ValueError("Tävlingen finns inte")
                    if old["source"] not in ("Manuell","Demodata"):return self.json(403,{"error":"Endast manuellt registrerade tävlingar kan ändras"})
                    c.execute("UPDATE competitions SET name=?,date=?,regular_deadline=?,final_deadline=?,url=?,published=?,classes=? WHERE id=?",(name,day,regular,final,str(data.get("url", "")),int(bool(data.get("published",False))),json.dumps(classes,ensure_ascii=False),cid))
                return self.json(200,{"ok":True})
            if p.startswith("/api/admin/competition/"):
                if not self.require_admin():return
                cid=int(p.rsplit("/",1)[1])
                with connect() as c:
                    if c.execute("UPDATE competitions SET published=? WHERE id=?",(int(bool(data["published"])),cid)).rowcount==0:raise ValueError("Tävlingen finns inte")
                return self.json(200,{"ok":True})
            if p.startswith("/api/admin/mark/"):
                if not self.require_admin():return
                rid=int(p.rsplit("/",1)[1])
                with connect() as c:
                    r=c.execute("SELECT status FROM registrations WHERE id=?",(rid,)).fetchone()
                    if not r:raise ValueError("Anmälan finns inte")
                    if r["status"]=="confirmed":raise ValueError("Redan bekräftad")
                    c.execute("UPDATE registrations SET status='confirmed' WHERE id=?",(rid,))
                    c.execute("INSERT INTO audit(registration_id,action,created_at) VALUES(?,?,?)",(rid,"Manuellt bekräftad som officiellt registrerad",now()))
                return self.json(200,{"ok":True})
            if p.startswith("/api/admin/send/"):
                if not self.require_admin():return
                if TEST_MODE:return self.json(409,{"error":"Vidareanmälan är avstängd i testmiljön"})
                if not EXTERNAL_URL or not EXTERNAL_TOKEN:return self.json(409,{"error":"Ingen verifierad integration för vidareanmälan är konfigurerad"})
                rid=int(p.rsplit("/",1)[1])
                with connect() as c:
                    r=c.execute("SELECT * FROM registrations WHERE id=?",(rid,)).fetchone()
                    if not r:raise ValueError("Anmälan finns inte")
                    if r["status"]=="confirmed":return self.json(409,{"error":"Anmälan är redan officiellt registrerad"})
                    comp=c.execute("SELECT * FROM competitions WHERE id=?",(r["competition_id"],)).fetchone()
                payload=json.dumps({"registration_id":rid,"competition":comp["name"],"name":r["name"],"birth_year":r["birth_year"],"gender":r["gender"],"class_name":r["class_name"],"events":json.loads(r["events"])},ensure_ascii=False).encode()
                request=urllib.request.Request(EXTERNAL_URL,data=payload,headers={"Content-Type":"application/json","Authorization":"Bearer "+EXTERNAL_TOKEN,"Idempotency-Key":str(rid)},method="POST")
                try:
                    with urllib.request.urlopen(request,timeout=20) as response:
                        result=json.load(response)
                    if result.get("status")!="confirmed" or not result.get("reference"):raise ValueError("Extern tjänst bekräftade inte anmälan")
                except (urllib.error.URLError,ValueError) as ex:
                    with connect() as c:c.execute("INSERT INTO audit(registration_id,action,created_at) VALUES(?,?,?)",(rid,"Överföringsförsök misslyckades: "+str(ex)[:150],now()))
                    return self.json(502,{"error":"Överföringen kunde inte bekräftas. Kontrollera mottagarsystemet före nytt försök."})
                with connect() as c:
                    c.execute("UPDATE registrations SET status='confirmed',external_reference=? WHERE id=?",(str(result["reference"]),rid))
                    c.execute("INSERT INTO audit(registration_id,action,created_at) VALUES(?,?,?)",(rid,"Externt bekräftad: "+str(result["reference"]),now()))
                return self.json(200,{"ok":True,"reference":result["reference"]})
            return self.json(404,{"error":"Okänd adress"})
        except (ValueError,KeyError,TypeError,OverflowError) as ex:return self.json(400,{"error":str(ex)})
        except Exception as ex:
            print("Server error:",repr(ex))
            return self.json(500,{"error":"Serverfel. Kontrollera serverloggen."})
if __name__=="__main__":
    if not ADMIN or not CLUB:raise SystemExit("Ange IKHP_ADMIN_PASSWORD och IKHP_CLUB_PASSWORD som miljövariabler före start.")
    init()
    print(f"IKHP-portal körs på http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()
