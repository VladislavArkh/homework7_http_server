import socket
import os
import threading
from datetime import datetime
import mimetypes
import magic
from pathlib import Path
import re
import urllib.parse
from optparse import OptionParser

SOCKET_TIMEOUT = 1000
RECONNECT_MAX_ATTEMPTS = 3
RECONNECT_DELAY = 3
MAX_LINE = 100
MAX_HEADERS = 10
STATUS_REASON = {
    200: "OK",
    403: "Forbidden",
    404: "Not Found",
    405: "MethodNotAllowed"
}


class MyHTTPServer:
    def __init__(self, host, port, workers, doc_root,
                socket_timeout=SOCKET_TIMEOUT,
                reconnect_max_attempts=RECONNECT_MAX_ATTEMPTS,
                reconnect_delay=RECONNECT_DELAY):
        self._host = host
        self._port = port
        self.workers = workers
        self.doc_root = doc_root
        self.socket_timeout = socket_timeout
        self.reconnect_delay = reconnect_delay
        self.reconnect_max_attempts = reconnect_max_attempts
        self._socket = None


    def start_server(self):
        """
        Метод запускает сервер, создает сокет и ждет подключений клиентов,
        масштабируется на несколько воркеров (задается параметром командной строки)
        """
        try:
            if self._socket:
                self._socket.close()
                self._socket = socket.socket()
            else:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.socket_timeout)
            self._socket.bind((self._host, self._port))
            self._socket.listen()
            for i in range (self.workers):
                try:
                    connection = Connection(self._socket)
                    client_handler = threading.Thread(
                                    target=connection.wait_connection,)
                    client_handler.start()
                except Exception as e:
                    raise Exception(f"Error {e} in connection")
        except socket.error as e:
            raise Exception(f"Error {e} in socket creation")


class Connection:
    """
    Класс ожидания и создания соединения пользователя с клиентом
    """
    def __init__(self, socket):
        self._socket = socket

    def wait_connection(self):
        """
        Метод, в котором принимается соединение от клиента,
        а также создаются объекты классов для обработки запроса и создания ответа 
        """
        while True:
            conn, address = self._socket.accept()
            # Обрабатываем запрос
            request = Request(conn)
            method, target, ver, headers = request.read_request()
            # Генерируем и отправляем ответ
            send_response = SendResponse(conn, method, target, ver)
            send_response.make_response()
            send_response.send_response()
            conn.close()
      

class Request:
    """
    Класс обработки запроса клиента
    """
    def __init__(self, connection):
        self._conn = connection

    def read_request(self):
        """
        Метод, в котором получаем запрос клиента и разбиваем его на параметры 
        (метод запроса, версию протокола, запрашиваемый ресурс 
        и остальные параметры запроса)
        """
        rfile = self._conn.makefile('rb')
        # Работаем с первой строкой запроса
        raw = rfile.readline(MAX_LINE + 1)
        req_line = str(raw, 'iso-8859-1')
        if not req_line:
            raise Exception("Empty request")
        req_line = req_line.rstrip('\r\n')
        # Разделяем регуляркой на метод, версию протокола и запрашиваемый ресурс
        method, ver = re.split(r' /[a-zA-z \.\d%\/-]*\.?[a-z\/]*[ ?]*[\S]* ', 
                                req_line)
        target = re.findall(r' (/[a-zA-z \.\d%\/-]*\.?[a-z\/]*)[ ?]*[\S]* ', 
                                req_line)[0].lstrip().rstrip()
        target = urllib.parse.unquote_plus(target, encoding='utf-8',
                          errors='replace')
        # Работаем с остальными строками запроса, разбиваем 
        # на название парметра запроса и его значение
        headers = {}
        while True:
            raw = rfile.readline(MAX_LINE + 1)
            if raw in (b'\r\n', b'\n', b'', b'\r\n\r\n'):
                break
            key, value = raw.decode('iso-8859-1').split(':',1)
            headers[key] = value
        return method, target, ver, headers


class SendResponse:
    """
    Класс создания ответа и отправки его клиенту
    parameters: 
            - connection - клиентское подключение
            - method - метод запроса
            - target - запрашиваемый ресурс
            - ver - версию протокола
            - resp - объект класса Response (сформированный ответ клиенту)
    """
    def __init__(self, connection, method, target, ver):
            self._conn = connection
            self.method = method
            self.target = target
            self.ver = ver
            self.resp = None

    def make_response(self):
        """
        Метод создания ответа на запрос клиента
        """
        status = 200
        headers = {}
        headers['Connectoin'] = "keep alive"
        headers['Server'] = "My_Super_Server"
        now = datetime.now()
        headers['Date'] = now.strftime("%m/%d/%Y, %H:%M:%S")
        if self.method not in ['GET', 'HEAD'] or self.ver != 'HTTP/1.1':
            status = 405
            self.resp = Response(status, STATUS_REASON[status], headers)
            return self.resp
        # если в запрашивамом ресурсе клиент пытаеься выйти из директории проекта
        # что "схлопываем все ../"
        target = self.target.replace('../', '')
        file_path = opts.doc_root+target
        # Если запрашивается директория - возвращаем файл index.html
        if Path(file_path).is_dir():
            file_path+='index.html'
        else:
            # Если после запрашиваемого файла клиент поставил /
            if target[len(target)-1] == '/':
                status = 404
                self.resp = Response(status, STATUS_REASON[status], headers)
                return self.resp
        # Проверяем метод запроса и выбираем, считывать ли файл
        if self.method == "GET":
            # Считываем данные из запрашиваемого файла
            try:
                file = open(file_path, 'rb')
                # Считаем размер файла, а также определяем его тип
                headers['Content-Length'] = os.stat(file_path).st_size
                headers['Content-Type'] = mimetypes.guess_type(file_path)[0]
            except:
                status = 404
                self.resp = Response(status, STATUS_REASON[status], headers)
                return self.resp
            data = file.read() 
            self.resp = Response(status, STATUS_REASON[status], headers, data)
        if self.method == "HEAD":
            self.resp = Response(status, STATUS_REASON[status], headers)
        return self.resp


    def send_response(self):
        """
        Метод отправки запроса
            
        """
        wfile = self._conn.makefile('wb')
        status_line = f'HTTP/1.1 {self.resp.status} {self.resp.reason}\r\n'
        wfile.write(status_line.encode('iso-8859-1'))
        if self.resp.headers:
            for key, value in self.resp.headers.items():
                header_line = f'{key}: {value}\r\n'
                wfile.write(header_line.encode('iso-8859-1'))
        wfile.write(b'\r\n')
        if self.resp.body:
            wfile.write(self.resp.body)
        wfile.flush()
        wfile.close()


class Response():
    """
    Класс описывает параметры ответа сервера
    """
    def __init__(self, status, reason, headers=None, body=None):
        self.status = status
        self.reason = reason
        self.headers = headers
        self.body = body


if __name__ == '__main__':
    op = OptionParser()
    op.add_option("-l", "--host", action="store", default='localhost')
    op.add_option("-p", "--port", action="store", type=int, default=8080)
    op.add_option("-r", "--doc_root", action="store", default="")
    op.add_option("-u", "--url", action="store", default='localhost')
    op.add_option("-w", "--workers", action="store", default=1)
    (opts, args) = op.parse_args()
    serv = MyHTTPServer(opts.host, opts.port, opts.workers, opts.doc_root)
    try:
        serv.start_server()
    except KeyboardInterrupt:
        pass
