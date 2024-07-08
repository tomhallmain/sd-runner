from multiprocessing.connection import Listener
import time

from utils.config import config
from utils.globals import WorkflowType

class SDRunnerServer:
    TYPE_RENOISER = 'renoiser'
    TYPE_CONTROL_NET = 'control_net'
    TYPE_IP_ADAPTER = 'ip_adapter'

    def __init__(self, run_callback, host='localhost', port=config.server_port):
        self._running = False
        self._is_stopping = False
        self._host = host
        self._port = port
        self.listener = None
        self._conn = None
        self.run_callback = run_callback

    def start(self):
        self.listener = Listener((self._host, self._port), authkey=str.encode(config.server_password))
        self._running = True
        while self._running and not self._is_stopping:
            self._conn = self.listener.accept()
            print('connection accepted from', self.listener.last_accepted)

            while not self._is_stopping:
                try:
                    msg = self._conn.recv()
                    if msg is None:
                        continue
                    print(msg)
                    if msg == 'close server' or msg == 'close connection':
                        self._conn.close()
                        if msg == 'close server':
                            self._running = False
                        break
                    if msg == 'validate':
                        self._conn.send('valid')
                    elif isinstance(msg, dict):
                        if "command" not in msg or "type" not in msg or "args" not in msg:
                            self._conn.send({"error": "invalid command", "data": msg})
                        else:
                            self.run_command(msg["command"], msg["type"], msg["args"])
                except KeyboardInterrupt:
                    pass
                except Exception as e:
                    print(e)
                    self._conn.send({'error': 'server error', 'data': str(e)})
                    self._conn.close()
                time.sleep(0.5)
        self.listener.close()
        self._running = False
        self._is_stopping = False

    def run_command(self, command, _type, args):
        if self._conn is None:
            raise Exception("connection closed before run command execution")
        if command != 'run':
            self._conn.send({"error": "invalid command", 'data': command})
            return
        try:
            if _type == SDRunnerServer.TYPE_RENOISER:
                resp = self.run_callback(WorkflowType.RENOISER, args)
            elif _type == SDRunnerServer.TYPE_CONTROL_NET:
                resp = self.run_callback(WorkflowType.CONTROLNET, args)
            elif _type == SDRunnerServer.TYPE_IP_ADAPTER:
                resp = self.run_callback(WorkflowType.IP_ADAPTER, args)
            else:
                self._conn.send({"error": "invalid command type", 'data': _type})
                return
            self._conn.send(resp)
            print("After self._conn.send(resp)")
        except Exception as e:
            print(e)
            self._conn.send({'error': 'run error', 'data': str(e)})

    def stop(self):
        self._is_stopping = True
        timeout = 2
        while self._is_stopping and timeout > 0:
            time.sleep(1) # Await other thread to end the start() method
            timeout -= 1
        if timeout == 0:
            raise Exception("Failed to stop, hit timeout")

