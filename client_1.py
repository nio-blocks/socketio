import json
from .client import SocketIOWebSocketClient
from nio.modules.threading import Thread


class SocketIOWebSocketClientV1(SocketIOWebSocketClient):

    """ A client for 1.0 socket.io servers """

    def __init__(self, url, logger, room, listen,
                 restart_handler, data_handler):
        super(SocketIOWebSocketClient, self).__init__(url, None, None)
        self._th = Thread(target=self.run, name='SocketIOWebSocketClient')
        self._logger = logger
        self._room = room
        self._listen = listen
        self._restart_handler = restart_handler
        self._data_handler = data_handler

    def handshake_ok(self):
        self._th.start()
        self._th.join(timeout=1.0)

    def opened(self):
        self._logger.info("Socket connection open")
        # Send a connection request
        self._send_packet(52)

    def closed(self, code, reason=None):
        self._logger.info(
            "Socket connection closed {0}:{1}".format(code, reason))
        self.handle_disconnect()

    def handle_disconnect(self):
        self._logger.info("Disconnection detected")
        self._restart_handler()

    def received_message(self, m):
        # The message type comes as the first two digits
        try:
            message_type = int(str(m)[:2])
        except ValueError:
            self._logger.warning(
                "Received an improperly formatted message: %s" % m)
            return

        message_data = str(m)[2:]

        self._logger.debug("Received a message: {}".format(message_data))

        # Handle the different types
        message_handlers = {
            40: self._recv_connect,
            41: self._recv_disconnect,
            42: self._recv_event
        }

        if message_type not in message_handlers:
            self._logger.warning(
                "Message type %s is not a valid message type" % message_type)
            return

        message_handlers[message_type](message_data)

    def send_msg(self, msg):
        self._send_packet(3, '', '', msg)

    def send_dict(self, data):
        self._send_packet(4, '', '', json.dumps(data))

    def send_event(self, event, data):
        self._send_packet(42, event, data)

    def _send_packet(self, code, path='', data='', id=''):
        if path or data:
            packet_text = "{}{}".format(code, json.dumps([path, data]))
        else:
            packet_text = "{}".format(code)

        self._logger.debug("Sending packet: %s" % packet_text)
        try:
            self.send(packet_text)
        except Exception as e:
            self._logger.error(
                "Error sending packet: {0}: {1}".format(type(e).__name__,
                                                        str(e))
            )

    def _send_heartbeat(self):
        self._logger.debug("Sending heartbeat message")
        self._send_packet(2)

    def _parse_message(self, message):
        """parses a message, if it can"""
        try:
            obj = json.loads(message)
        except Exception:
            obj = {'message': message}

        return obj

    def _recv_disconnect(self, data=None):
        self.handle_disconnect()

    def _recv_connect(self, data=None):
        self._logger.info("Socket.io connection confirmed")

        self._logger.debug("Joining room %s" % self._room)
        self.send_event('ready', self._room)

    def _recv_heartbeat(self, data=None):
        # When we get a heartbeat from the server, send one back!
        self._send_heartbeat()

    def _recv_msg(self, data=None):
        self._data_handler(self._parse_message(data))

    def _recv_json(self, data=None):
        self._data_handler(self._parse_message(data))

    def _recv_event(self, data=None):
        # when we receive an event, we get a dictionary containing the event
        # name, and a list of arguments that come with it. we only care about
        # the first item in the list of arguments
        if not self._listen:
            self._logger.debug("Ignoring incoming data from web socket")
            return

        event_data = json.loads(data)
        self._data_handler({
            'event': event_data[0],
            'data': self._parse_message(event_data[1])
        })

    def _recv_ack(self, data=None):
        pass

    def _recv_error(self, data=None):
        pass

    def _recv_noop(self, data=None):
        pass
