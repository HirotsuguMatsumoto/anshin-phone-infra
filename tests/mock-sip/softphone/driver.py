"""JSON stdin control of the same real mobile native C core; fixture only."""
import ctypes as c
import json
import math
import struct
import sys
import time
import wave

class Event(c.Structure):
    _fields_=[('epoch',c.c_uint64),('call',c.c_uint64),('account',c.c_uint64),('kind',c.c_int),('code',c.c_int)]
class Stats(c.Structure):
    _fields_=[('tx',c.c_uint64),('rx',c.c_uint64)]
lib=c.CDLL('/libphone-softphone.so');engine=c.c_void_p()
lib.phone_create.argtypes=[c.c_int,c.POINTER(c.c_void_p)]
lib.phone_configure.argtypes=[c.c_void_p,c.c_char_p,c.c_char_p,c.c_char_p,c.POINTER(c.c_uint64)]
lib.phone_dial.argtypes=[c.c_void_p,c.c_char_p,c.POINTER(c.c_uint64)]
lib.phone_poll.argtypes=[c.c_void_p,c.POINTER(Event)]
lib.phone_fixture_media.argtypes=[c.c_void_p,c.c_uint64,c.c_char_p,c.c_char_p]
lib.phone_get_media_stats.argtypes=[c.c_void_p,c.c_uint64,c.POINTER(Stats)]
for name in ('phone_answer','phone_hangup'):getattr(lib,name).argtypes=[c.c_void_p,c.c_uint64]
for name in ('phone_revoke','phone_reconnect','phone_destroy'):getattr(lib,name).argtypes=[c.c_void_p]
pending=[]
with wave.open('/tmp/softphone-tone.wav','wb') as wav:
    wav.setparams((1,2,8000,0,'NONE','not compressed'))
    wav.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*660*i/8000))) for i in range(8000)))
def wait(kind,code=None,timeout=15,minimum=None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        event=Event()
        while lib.phone_poll(engine,c.byref(event))==1:
            value={name:getattr(event,name) for name,_ in event._fields_}
            pending.append(value)
        for index,value in enumerate(pending):
            if value['kind']==kind and (code is None or value['code']==code) and (minimum is None or value['code']>=minimum):return pending.pop(index)
        time.sleep(.02)
    raise RuntimeError('event_timeout')
def invoke(request):
    command=request['command']
    if command=='initialize':return {'status':lib.phone_create(1,c.byref(engine))}
    if command=='configure':
        pending.clear(); generation=c.c_uint64()
        status=lib.phone_configure(engine,request['server'].encode(),request['username'].encode(),request['password'].encode(),c.byref(generation))
        return {'status':status,'account':generation.value}
    if command=='wait':return wait(request['kind'],request.get('code'),request.get('timeout',15),request.get('minimum'))
    if command=='dial':
        token=c.c_uint64();status=lib.phone_dial(engine,request['number'].encode(),c.byref(token));return {'status':status,'call':token.value}
    if command in ('answer','hangup'):return {'status':getattr(lib,'phone_'+command)(engine,request['call'])}
    if command in ('reconnect','revoke'):pending.clear();return {'status':getattr(lib,'phone_'+command)(engine)}
    if command=='media':
        status=lib.phone_fixture_media(engine,request['call'],b'/tmp/softphone-tone.wav',('/tmp/received-'+str(request['call'])+'.wav').encode())
        if status:return {'status':status}
        time.sleep(1.2);stats=Stats();status=lib.phone_get_media_stats(engine,request['call'],c.byref(stats))
        return {'status':status,'tx':stats.tx,'rx':stats.rx}
    if command=='wave':
        with wave.open('/tmp/received-'+str(request['call'])+'.wav','rb') as wav:
            assert wav.getsampwidth()==2 and wav.getframerate()==8000 and wav.getnchannels()==1
            raw=wav.readframes(wav.getnframes()); samples=struct.unpack('<'+'h'*(len(raw)//2),raw)
        rms=math.sqrt(sum(x*x for x in samples)/max(1,len(samples)))
        # Carrier source is the pre-existing 440 Hz tone, different from our 660 Hz.
        # Measure 440 energy to prove reception is not a local loopback or silence.
        window=samples[800:8800]
        energy=abs(sum(x*complex(math.cos(2*math.pi*440*i/8000),-math.sin(2*math.pi*440*i/8000)) for i,x in enumerate(window)))/max(1,len(window))
        return {'samples':len(samples),'rms':round(rms,2),'carrier_440_energy':round(energy,2)}
    if command=='dispose':
        status=lib.phone_destroy(engine);engine.value=None;return {'status':status}
    raise ValueError('unknown_command')
try:
    for line in sys.stdin:
        try: result=invoke(json.loads(line))
        except Exception: result={'error':'fixture_command_failed'}
        print('PHONE_JSON '+json.dumps(result),flush=True)
finally:
    if engine.value:lib.phone_destroy(engine)
