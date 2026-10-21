"""Decode only inbound PCMU RTP on the isolated carrier; aggregate audio only."""
import audioop
import json
import math
import socket
import struct
import sys
import time

seconds=float(sys.argv[1]);deadline=time.monotonic()+seconds
sock=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x0800));sock.settimeout(.2)
samples=[];packets=0
try:
    while time.monotonic()<deadline:
        try:frame=sock.recv(65535)
        except socket.timeout:continue
        if len(frame)<54 or frame[12:14]!=b'\x08\x00':continue
        ip=frame[14:];ihl=(ip[0]&15)*4
        if ip[9]!=17 or ip[12:16]!=socket.inet_aton('10.254.250.50') or ip[16:20]!=socket.inet_aton('10.254.250.10'):continue
        udp=ip[ihl:];rtp=udp[8:]
        if len(rtp)<12 or rtp[0]>>6!=2 or rtp[1]&127!=0:continue
        offset=12+4*(rtp[0]&15)
        if rtp[0]&16:
            if len(rtp)<offset+4:continue
            offset+=4+4*int.from_bytes(rtp[offset+2:offset+4],'big')
        payload=rtp[offset:len(rtp)-(rtp[-1] if rtp[0]&32 else 0)]
        if not payload:continue
        pcm=audioop.ulaw2lin(payload,2);samples.extend(struct.unpack('<'+'h'*(len(pcm)//2),pcm));packets+=1
finally:sock.close()
window=samples[1600:9600]
rms=math.sqrt(sum(x*x for x in samples)/max(1,len(samples)))
energy=abs(sum(x*complex(math.cos(2*math.pi*660*i/8000),-math.sin(2*math.pi*660*i/8000)) for i,x in enumerate(window)))/max(1,len(window))
result={'packets':packets,'samples':len(samples),'rms':round(rms,2),'softphone_660_energy':round(energy,2)}
print(json.dumps(result,sort_keys=True),flush=True)
if packets<20 or len(samples)<8000 or rms<100 or energy<100:raise SystemExit('carrier did not decode expected Softphone audio')
