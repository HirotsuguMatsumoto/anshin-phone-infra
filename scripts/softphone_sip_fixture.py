"""Softphone branch of the existing isolated SIP fixture, not a new runtime owner."""
import json
import os
from pathlib import Path
import select
import subprocess
import time

PIN='5a457451fa2712ba18e12b01738e8ff3af2b26fd'
def prepare_softphone_override(root, directory, env, run):
    mobile=Path(env.get('PHONE_SOFTPHONE_ROOT',''))
    sdk=Path(env.get('PHONE_PJSIP_SOURCE',''))
    if not mobile.is_absolute() or not sdk.is_absolute() or not (mobile/'ios/anshin_phone_softphone/Sources/PhoneNative/phone_sip.cpp').is_file():
        raise RuntimeError('process-start=0: explicit Softphone package and pinned SDK required')
    if run(['git','-C',str(sdk),'rev-parse','HEAD'],env=env).stdout.strip()!=PIN or run(['git','-C',str(sdk),'status','--porcelain'],env=env).stdout.strip():
        raise RuntimeError('process-start=0: SDK source pin or cleanliness mismatch')
    source=directory/'sdk';source.mkdir()
    archive=subprocess.run(['git','-C',str(sdk),'archive','HEAD'],capture_output=True,check=True)
    subprocess.run(['tar','-x','-C',str(source)],input=archive.stdout,check=True)
    (source/'phone-sdk-commit.txt').write_text(PIN+'\n')
    path=directory/'softphone-compose.json'
    path.write_text(json.dumps({'services':{'mock-smartphone':{'build':{
        'context':str(root/'tests/mock-sip/softphone'),
        'additional_contexts':{'mock_sip_runtime':'service:mock-carrier','phone_sdk':str(source),'phone_native':str(mobile/'ios/anshin_phone_softphone/Sources/PhoneNative')}
    }}}}))
    return path

def run_softphone_flow(base,env,endpoint,configuration,backend_request,run,exec_background,finish):
    process=subprocess.Popen(base+['exec','-T','mock-smartphone','python3','-u','/softphone-driver.py'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    def command(command,**kwargs):
        process.stdin.write(json.dumps({'command':command,**kwargs})+'\n');process.stdin.flush()
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if not select.select([process.stdout],[],[],max(0,deadline-time.monotonic()))[0]:break
            line=process.stdout.readline()
            if not line:break
            if line.startswith('PHONE_JSON '):
                result=json.loads(line.removeprefix('PHONE_JSON '))
                if 'error' in result:raise RuntimeError('Softphone SDK fixture command failed')
                return result
        raise RuntimeError('Softphone SDK fixture command timeout')
    def ok(value):
        if value.get('status')!=0:raise RuntimeError('Softphone SDK command rejected: '+str(value.get('status')))
        return value
    def registration():
        result=command('wait',kind=1,code=200)
        if result['code']!=200:raise RuntimeError('Softphone registration rejected')
    credentials={'server':'10.254.250.40:5060','username':'2001','password':configuration['endpoints'][0]['password']}
    peers=[]
    try:
        ok(command('initialize'));ok(command('configure',**credentials));registration()
        print('PASS: actual PJSIP 2.17 core -> existing SBC/PBX REGISTER',flush=True)
        old_call=None
        for direction in ('inbound','outbound'):
            probe=exec_background(base,'mock-carrier',['python3','/softphone-carrier-audio-probe.py','6'],env)
            peers.append(probe);time.sleep(.25)
            if direction=='inbound':
                peer=exec_background(base,'mock-carrier',['sipp','-nostdin','10.254.250.40:5060','-sf','/scenarios/carrier_inbound_uac.xml','-i','10.254.250.10','-p','5060','-m','1','-timeout','20s'],env)
                peers.append(peer);incoming=command('wait',kind=2);token=incoming['call'];ok(command('answer',call=token))
            else:
                peer=exec_background(base,'mock-carrier',['sipp','-nostdin','-sf','/scenarios/carrier_outbound_uas.xml','-i','10.254.250.10','-p','5060','-m','1','-timeout','20s'],env)
                peers.append(peer);time.sleep(.5);token=ok(command('dial',number='0300000000'))['call']
                if old_call is not None and command('hangup',call=old_call)['status']!=-3:raise RuntimeError('Old call identity controlled new call')
            command('wait',kind=5)
            media=ok(command('media',call=token))
            if min(media['rx'],media['tx'])<20:raise RuntimeError('Softphone requires both RTP directions')
            if direction=='outbound':ok(command('hangup',call=token))
            command('wait',kind=6);finish(peer,'SDK mock carrier '+direction)
            decoded=command('wave',call=token)
            if decoded['samples']<8000 or decoded['rms']<100 or decoded['carrier_440_energy']<100:raise RuntimeError('Softphone received audio is silent or not carrier tone')
            print('PASS: PJSIP '+direction+' PCMU actual RTP and decoded 440Hz carrier audio '+json.dumps({**media,**decoded},sort_keys=True),flush=True)
            finish(probe,'carrier decoded Softphone 660Hz '+direction)
            old_call=token
        ok(command('reconnect'));registration()
        print('PASS: same engine actual SIP registration after transport restart (not device network switching)',flush=True)
        backend_request(base,env,'PATCH',f"/api/v1/sip-endpoints/{endpoint['id']}",{'status':'suspended'})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if 'Endpoint:  2001' not in run(base+['exec','-T','asterisk','asterisk','-rx','pjsip show endpoints'],env=env).stdout:break
            time.sleep(.2)
        else:raise RuntimeError('Softphone suspended endpoint provisioning timeout')
        ok(command('configure',**credentials));rejection=command('wait',kind=1,minimum=300)
        if rejection['code']<300:raise RuntimeError('Old SDK credential accepted while suspended')
        backend_request(base,env,'PATCH',f"/api/v1/sip-endpoints/{endpoint['id']}",{'status':'active'})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if 'Endpoint:  2001' in run(base+['exec','-T','asterisk','asterisk','-rx','pjsip show endpoints'],env=env).stdout:break
            time.sleep(.2)
        ok(command('configure',**credentials));registration()
        ok(command('revoke'))
        if command('dial',number='2002')['status']!=-4:raise RuntimeError('Revoked SDK dial accepted')
        ok(command('dispose'));ok(command('initialize'))
        if command('hangup',call=old_call)['status']!=-3:raise RuntimeError('Old engine call token accepted')
        ok(command('dispose'))
        print('PASS: suspended SDK credential rejected, active endpoint reconnects, revoke denies new call, destroy/reinit and stale call rejection',flush=True)
    finally:
        if process.stdin:process.stdin.close()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
        for peer in peers:
            if peer.poll() is None:peer.terminate();peer.communicate(timeout=5)
