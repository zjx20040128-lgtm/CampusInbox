"""Run: python server.py [--host 127.0.0.1] [--port 8765] [--data-dir data]."""
import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from courseinbox.core import Inbox
from courseinbox.http import create_server
from courseinbox.agent import AgentError

def browser_url(port,view='today'):
    if view not in ('today','sync'):raise ValueError('unsupported initial view')
    return f'http://127.0.0.1:{port}'+('' if view=='today' else '/#sync')

def main():
    parser=argparse.ArgumentParser(description='CourseInbox local task hub')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--reminder-port',type=int,default=8766)
    parser.add_argument('--open-browser',action='store_true')
    parser.add_argument('--open-view',choices=('today','sync'),default='today')
    parser.add_argument('--data-dir',default=str(Path(__file__).resolve().parent/'data'))
    args=parser.parse_args()
    if not 0<=args.reminder_port<=65535:parser.error('--reminder-port must be 0 to 65535')
    root=Path(__file__).resolve().parent
    directory=Path(args.data_dir).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    token_path=directory/'access-token.txt'
    token=os.environ.get('CI_ACCESS_TOKEN','').strip()
    if not token:
        if token_path.exists(): token=token_path.read_text(encoding='utf-8-sig').strip()
        else:
            token=secrets.token_urlsafe(32)
            token_path.write_text(token,encoding='utf-8')
    if len(token)<24:
        parser.error('CI_ACCESS_TOKEN must contain at least 24 characters')
    try:
        server=create_server(args.host,args.port,Inbox(directory/'inbox.sqlite3'),token,root,reminder_port=args.reminder_port)
    except (OSError,ValueError,AgentError) as error:
        print(f'Cannot start CourseInbox: {error}',file=sys.stderr)
        return 1
    print(f'CourseInbox ready: http://127.0.0.1:{server.server_port}',flush=True)
    print(f'Data: {directory}\nMobile token file: {token_path}',flush=True)
    if args.host=='0.0.0.0':
        print('LAN mode enabled; remote clients require the access token.',flush=True)
        print('Paired computer: '+server.discovery.identity['name'],flush=True)
    if args.open_browser:
        opener=threading.Timer(0.6,lambda:webbrowser.open(browser_url(server.server_port,args.open_view)))
        opener.daemon=True
        opener.start()
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nCourseInbox stopped.',flush=True)
    finally: server.server_close()
    return 0

if __name__=='__main__': sys.exit(main())
