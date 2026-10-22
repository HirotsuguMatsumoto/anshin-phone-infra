"""Softphone branch of the existing isolated SIP fixture, not a new runtime owner."""
import json
import os
from pathlib import Path
import select
import subprocess
import time
import ipaddress
import re
import socket
import uuid
import shlex

PIN='5a457451fa2712ba18e12b01738e8ff3af2b26fd'
def prepare_softphone_override(root, directory, env, run):
    mobile=Path(env.get('PHONE_SOFTPHONE_ROOT',''))
    sdk=Path(env.get('PHONE_PJSIP_SOURCE',''))
    if not mobile.is_absolute() or not sdk.is_absolute() or not (mobile/'ios/anshin_phone_softphone/Sources/PhoneNative/phone_sip.cpp').is_file():
        raise RuntimeError('process-start=0: explicit Softphone package and pinned SDK required')
    if env.get('PHONE_SOFTPHONE_SIMULATOR'):
        return prepare_simulator(root, directory, env, mobile)
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


def simulator_template(root, host, port, source):
    """Fixture-only listener. Production template and carrier path stay intact."""
    ip = ipaddress.IPv4Address(source)
    if not ip.is_private or ip.is_unspecified or not 1024 <= port <= 65535:
        raise RuntimeError('invalid observed fixture source or binding')
    template = (root/'deploy/kamailio/config/kamailio.cfg.template').read_text()
    template = template.replace('request_route {', '''request_route {
    force_rport();
    if ($Rp == 5070 && src_ip != SOURCE/32) {
        sl_send_reply("403", "Fixture Source Mismatch"); exit;
    }
'''.replace('SOURCE', source))
    template = template.replace('alias=kamailio:5060', f'''alias=kamailio:5060
listen=udp:__SBC_EDGE_IP__:5070 advertise {host}:{port}
alias={host}:{port}
alias=127.0.0.1:{port}''')
    template = template.replace('    if (!(src_ip __TRUSTED_SOURCE_CONDITION__))', '''    if ($Rp == 5070 && src_ip == SOURCE/32) {
        if ($hdr(Contact) =~ ";alias=") {
            sl_send_reply("400", "Fixture Contact Alias Forbidden"); exit;
        }
        if (is_method("REGISTER")) add_contact_alias();
        route(TO_PBX); exit;
    }

    if (!(src_ip __TRUSTED_SOURCE_CONDITION__))'''.replace('SOURCE', source))
    template = template.replace('$fs = "udp:__SBC_EDGE_IP__:5060";\n                handle_ruri_alias();', 'route(FIXTURE_TARGET);')
    template = template.replace('$fs = "udp:__SBC_EDGE_IP__:5060";\n            handle_ruri_alias();', 'route(FIXTURE_TARGET);')
    template = template.replace('''    $fs = "udp:__SBC_EDGE_IP__:5060";
    if (loose_route()) {
        handle_ruri_alias();
    }''', '    route(FIXTURE_TARGET);')
    # Only PBX-originated branches above invoke this route. Incoming Contact
    # aliases are added from the actual device tuple, never accepted from input.
    target = '''route[FIXTURE_TARGET] {
    $fs = "udp:__SBC_EDGE_IP__:5060";
    if ($ru =~ ";alias=") {
        if (!($ru =~ ";alias=SOURCE~[0-9]{1,5}~1$") || $ru =~ ";alias=.*;alias=") {
            sl_send_reply("403", "Fixture Alias Mismatch"); exit;
        }
        $fs = "udp:__SBC_EDGE_IP__:5070";
        handle_ruri_alias();
        if ($dp < 1 || $dp > 65535) { sl_send_reply("400", "Fixture Port Invalid"); exit; }
    }
}
'''.replace('SOURCE', source.replace('.', '[.]'))
    return template.replace('route[TO_PBX] {', target+'\nroute[TO_PBX] {')


def prepare_simulator(root, directory, env, mobile):
    platform = env['PHONE_SOFTPHONE_SIMULATOR']
    if platform not in ('android', 'ios'):
        raise RuntimeError('process-start=0: unsupported owned Simulator')
    device = env.get('PHONE_SOFTPHONE_DEVICE', '')
    if platform == 'android':
        if device != 'emulator-5558':
            raise RuntimeError('process-start=0: owned Android identity required')
        result = subprocess.run(['adb','-s',device,'emu','avd','name'],capture_output=True,text=True,check=True)
        if result.stdout.splitlines()[0] != 'phone-softphone-20261022':
            raise RuntimeError('process-start=0: foreign Android runtime')
    else:
        devices = json.loads(subprocess.check_output(['xcrun','simctl','list','devices','--json']))
        found = [d for group in devices['devices'].values() for d in group if d['udid'] == device]
        if len(found) != 1 or found[0]['name'] != 'phone-softphone-sip-20261022' or found[0]['state'] != 'Booted':
            raise RuntimeError('process-start=0: owned booted iOS Simulator required')
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    host = '10.0.2.2' if platform == 'android' else '127.0.0.1'
    path = directory/'simulator-kamailio.template'
    path.write_text(simulator_template(root,host,port,'127.0.0.1')); path.chmod(0o444)
    env['PHONE_SIM_TEMPLATE'] = str(path)
    env['PHONE_SIM_PORT'] = str(port)
    env['PHONE_SIM_HOST'] = host
    override = directory/'softphone-compose.json'
    override.write_text(json.dumps({'services':{'kamailio':{
        'ports':[f'127.0.0.1:{port}:5070/udp'],
        'volumes':[f'{path}:/opt/anshin-phone/templates/kamailio.cfg.template:ro']
    }}}))
    return override


def observe_source(port):
    """Uncredentialed OPTIONS; exact transaction binding, not authentication."""
    nonce = uuid.uuid4().hex
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1',0)); sock.settimeout(3)
        local = sock.getsockname()[1]
        request = (f'OPTIONS sip:127.0.0.1:{port} SIP/2.0\r\n'
                   f'Via: SIP/2.0/UDP 127.0.0.1:{local};branch=z9hG4bK{nonce};rport\r\n'
                   f'From: <sip:probe@localhost>;tag={nonce}\r\nTo: <sip:probe@localhost>\r\n'
                   f'Call-ID: {nonce}\r\nCSeq: 1 OPTIONS\r\nMax-Forwards: 8\r\nContent-Length: 0\r\n\r\n')
        sock.sendto(request.encode(),('127.0.0.1',port))
        response = sock.recv(8192).decode()
    if not response.startswith('SIP/2.0 200 ') or f'Call-ID: {nonce}\r\n' not in response or f'branch=z9hG4bK{nonce}' not in response or '\r\nCSeq: 1 OPTIONS\r\n' not in response:
        raise RuntimeError('fixture OPTIONS transaction mismatch')
    received = re.findall(r';received=([0-9.]+)',response)
    if len(received) != 1 or not ipaddress.IPv4Address(received[0]).is_private:
        raise RuntimeError('fixture NAT source unknown')
    return received[0]


def run_simulator_flow(base,env,endpoint,configuration,run,exec_background,finish):
    platform, device = env['PHONE_SOFTPHONE_SIMULATOR'], env['PHONE_SOFTPHONE_DEVICE']
    port = int(env['PHONE_SIM_PORT'])
    binding = run(base+['port','--protocol','udp','kamailio','5070'],env=env).stdout.strip()
    if binding != f'127.0.0.1:{port}':
        raise RuntimeError('fixture actual binding disagrees with advertised port')
    source = observe_source(port)
    template = Path(env['PHONE_SIM_TEMPLATE'])
    template.chmod(0o600)
    template.write_text(simulator_template(Path(__file__).resolve().parents[1],env['PHONE_SIM_HOST'],port,source))
    template.chmod(0o444)
    run(base+['restart','kamailio'],env=env)
    time.sleep(2)
    if observe_source(port) != source:
        raise RuntimeError('fixture NAT tuple changed')
    print('PASS: loopback-only actual binding and observed exact NAT source; PBX owns SIP Digest',flush=True)
    example = Path(env['PHONE_SOFTPHONE_ROOT'])/'example'
    app = 'care.anshin.phone.anshin_phone_softphone_example' if platform == 'android' else 'care.anshin.phone.anshinPhoneSoftphoneExample'
    process = subprocess.Popen(['flutter','test','--no-pub','integration_test/sip_simulator_test.dart','-d',device,'--reporter','expanded'],cwd=example,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    peers = []; app_temp = None; passed = False; transcript = []
    def private_file(name, payload=None):
        if app_temp is None: return
        if platform == 'android':
            # Exact package-private cache; no shared /sdcard fallback.
            action = f'cat > cache/{name}' if payload is not None else f'rm -f cache/{name}'
            if payload is not None: action = f'test ! -e cache/{name} && umask 077 && '+action
            subprocess.run(['adb','-s',device,'shell','run-as '+app+' sh -c '+shlex.quote(action)],input=payload,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=10)
        else:
            path = app_temp/name
            if payload is None: path.unlink(missing_ok=True)
            else:
                fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as file:file.write(payload)
    try:
        deadline = time.monotonic()+300
        while time.monotonic()<deadline:
            if not select.select([process.stdout],[],[],1)[0]:
                if process.poll() is not None:break
                continue
            line = process.stdout.readline()
            if not line:break
            transcript.append(line)
            if 'PHONE_SIM ' not in line:continue
            data = json.loads(line.split('PHONE_SIM ',1)[1]); phase = data['phase']
            print('phase=simulator-'+platform+' state='+phase,flush=True)
            if phase == 'awaiting_input':
                if platform == 'android':
                    if data['temp'] != f'/data/user/0/{app}/cache':
                        raise RuntimeError('fixture app-private cache mismatch')
                    app_temp = Path(data['temp'])
                else:
                    container = Path(subprocess.check_output(['xcrun','simctl','get_app_container',device,app,'data'],text=True).strip()).resolve()
                    app_temp = Path(data['temp']).resolve()
                    if app_temp != container/'tmp':raise RuntimeError('fixture iOS app-private tmp mismatch')
                private_file('phone-sip-input.json',json.dumps({'endpoint_id':endpoint['id'],'server':f"{env['PHONE_SIM_HOST']}:{port}",'username':'2001','password':configuration['endpoints'][0]['password']}))
            elif phase == 'registered':
                peers.append(exec_background(base,'mock-carrier',['sipp','-nostdin','10.254.250.40:5060','-sf','/scenarios/carrier_inbound_uac.xml','-i','10.254.250.10','-p','5060','-m','1','-timeout','35s'],env))
            elif phase == 'outbound_ready':
                finish(peers[-1],'Simulator inbound carrier')
                peers.append(exec_background(base,'mock-carrier',['sipp','-nostdin','-sf','/scenarios/carrier_outbound_uas.xml','-i','10.254.250.10','-p','5060','-m','1','-timeout','35s'],env))
                time.sleep(.5); private_file('phone-sip-go','ready')
            elif phase == 'passed':passed = True
        process.wait(timeout=15)
        if not passed or process.returncode:
            # Keep test assertion context, never credential input or VM service URLs.
            safe = [line for line in transcript if ('phase=' in line or 'Expected:' in line or 'Actual:' in line or 'Error:' in line or 'EXCEPTION' in line)]
            print(''.join(safe)[-3000:],flush=True)
            raise RuntimeError('Simulator native SIP consumer failed')
        for peer in peers:finish(peer,'Simulator mock carrier')
        print('PASS: '+platform+' native SIP incoming UI/answer/BYE, outbound, reconnect/revoke/stale call IDs; media-active only, RTP audio unqualified',flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for peer in peers:
            if peer.poll() is None:peer.terminate();peer.communicate(timeout=5)
        for name in ('phone-sip-input.json','phone-sip-go'):private_file(name)

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
